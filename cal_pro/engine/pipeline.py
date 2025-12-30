import logging
from typing import List, Optional, Dict, Tuple
from ..data_providers.base import DataProvider, Chain
from .market import MarketState
from .base_strategy import Strategy, CandidateTrade, TRADABILITY_TRADABLE, TRADABILITY_REJECTED
from .scoring import Scorer
from .tradability import TradabilityValidator, TradabilityConfig
from .regime import (
    RegimeDetector, SuitabilityEnforcer, RegimeClassification
)
from .portfolio import (
    PortfolioManager, PortfolioGreeks, PositionGreeks, ExposureThresholds,
    ExposureCheck, ExposureStatus, GreeksSource
)
from .utils import get_quote
from .logging_config import get_logger, audit_logger

logger = get_logger("pipeline")

# Regime rejection status
REGIME_REJECTED = "REJECTED — REGIME UNSUITABLE"
EXPOSURE_REJECTED = "REJECTED — EXPOSURE LIMIT"

class Pipeline:
    """Pipeline for running strategies with tradability and regime suitability validation."""
    
    def __init__(
        self, 
        provider: DataProvider, 
        strategies: List[Strategy],
        tradability_config: Optional[TradabilityConfig] = None,
        enforce_regime_suitability: bool = True
    ):
        self.provider = provider
        self.strategies = strategies
        self.scorer = Scorer()
        self.tradability_validator = TradabilityValidator(tradability_config)
        self.regime_detector = RegimeDetector()
        self.suitability_enforcer = SuitabilityEnforcer()
        self.enforce_regime_suitability = enforce_regime_suitability

    def run(self, ticker: str) -> Tuple[List[CandidateTrade], MarketState, RegimeClassification]:
        """Run pipeline and return (trades, market, regime)."""
        # 1. Build Market State
        try:
            market = MarketState.build(ticker, self.provider)
        except Exception as e:
            print(f"Error building market state for {ticker}: {e}")
            return [], None, None

        # 2. Detect market regime
        regime = self.regime_detector.detect(market.adx14, market.hv5, market.hv20)
        
        # 3. Fetch Chains
        exps = self.provider.expirations()
        chains = {}
        import datetime as dt
        cutoff = dt.date.today() + dt.timedelta(days=90)
        relevant_exps = [e for e in exps if dt.date.today() < e < cutoff]
        
        for e in relevant_exps:
            chains[e] = self.provider.chain(e)
            
        results = []
        regime_rejections: Dict[str, str] = {}  # strategy_name -> rejection_reason
        
        # 4. Run Strategies with regime suitability check
        for strat in self.strategies:
            if not strat.is_eligible(market):
                continue
                
            trades = strat.propose_trades(market, chains)
            
            for trade in trades:
                # 5. Check regime suitability FIRST (PR #4)
                if self.enforce_regime_suitability:
                    suitability = self.suitability_enforcer.check_suitability(
                        trade.strategy_name, regime
                    )
                    
                    if not suitability.is_suitable:
                        # Mark trade as rejected due to regime
                        trade.is_tradable = False
                        trade.tradability_status = REGIME_REJECTED
                        trade.rejection_reasons = [suitability.rejection_reason]
                        trade.metrics['regime_rejection'] = True
                        trade.metrics['regime_violation_trend'] = suitability.trend_violation
                        trade.metrics['regime_violation_vol'] = suitability.vol_violation
                        # Still add to results so UI can show rejections
                        results.append(trade)
                        continue
                    else:
                        # Add warnings to metrics
                        trade.metrics['regime_warnings'] = suitability.warnings
                
                # 6. Validate tradability for each leg (PR #2)
                self._validate_trade_tradability(trade, chains)
                
                # 7. Calculate and populate trade Greeks (PR #5)
                self._calculate_trade_greeks(trade, chains)
                
                # 8. Score
                self.scorer.score(trade, market)
                
                # 9. Audit logging
                audit_logger.log_trade_proposed(
                    ticker=trade.ticker,
                    strategy=trade.strategy_name,
                    confidence=trade.confidence_score,
                    tradable=trade.is_tradable
                )
                
                if not trade.is_tradable:
                    audit_logger.log_trade_rejected(
                        ticker=trade.ticker,
                        strategy=trade.strategy_name,
                        reasons=trade.rejection_reasons
                    )
                
                # Check for missing Greeks
                if trade.greeks:
                    all_zero = all(v == 0 for k, v in trade.greeks.items() if k != 'source')
                    if all_zero:
                        audit_logger.log_greeks_missing(trade.ticker, trade.strategy_name)
                        trade.metrics['greeks_warning'] = "Greeks unavailable - stress test unreliable"
                
                results.append(trade)
                    
        # 10. Sort: tradable first, then by confidence
        results.sort(key=lambda x: (x.is_tradable, x.confidence_score), reverse=True)
        
        return results, market, regime
    
    def _validate_trade_tradability(self, trade: CandidateTrade, chains: dict) -> None:
        """Validate all legs of a trade for tradability.
        
        Updates trade.is_tradable, trade.tradability_status, and trade.rejection_reasons.
        Also recalculates debit using conservative pricing if tradable.
        """
        rejection_reasons = []
        total_debit = 0.0
        total_slippage = 0.0
        all_tradable = True
        
        for leg in trade.legs:
            # Find the chain for this leg's expiry
            chain = chains.get(leg.expiry)
            if chain is None:
                rejection_reasons.append(f"No chain data for expiry {leg.expiry}")
                all_tradable = False
                continue
            
            # Get the quote for this leg
            quote = get_quote(chain, leg.right, leg.strike)
            if quote is None:
                rejection_reasons.append(f"No quote for {leg.right} @ {leg.strike}")
                all_tradable = False
                continue
            
            # Validate this leg
            validation = self.tradability_validator.validate_leg(quote, leg.action)
            
            if not validation.is_valid:
                rejection_reasons.append(validation.rejection_reason)
                all_tradable = False
            else:
                # Accumulate conservative pricing
                if leg.action == 'buy':
                    total_debit += validation.entry_price * leg.quantity * 100
                else:
                    total_debit -= validation.entry_price * leg.quantity * 100
                total_slippage += validation.slippage * leg.quantity * 100
        
        # Update trade with tradability results
        trade.is_tradable = all_tradable
        trade.rejection_reasons = rejection_reasons
        trade.slippage_cost = round(total_slippage, 2)
        
        if all_tradable:
            trade.tradability_status = TRADABILITY_TRADABLE
            # Update debit with conservative pricing
            trade.debit = round(total_debit, 2)
        else:
            trade.tradability_status = TRADABILITY_REJECTED
            # Keep original debit for reference but mark as untradable
    
    def _calculate_trade_greeks(self, trade: CandidateTrade, chains: dict) -> None:
        """Calculate aggregate Greeks for a trade from its legs.
        
        Populates trade.greeks with delta, gamma, vega, theta.
        Uses provider-supplied Greeks where available.
        """
        net_delta = 0.0
        net_gamma = 0.0
        net_vega = 0.0
        net_theta = 0.0
        source = GreeksSource.BROKER
        
        for leg in trade.legs:
            chain = chains.get(leg.expiry)
            if chain is None:
                continue
            
            quote = get_quote(chain, leg.right, leg.strike)
            if quote is None:
                continue
            
            # Get Greeks from quote
            leg_delta = quote.delta
            leg_gamma = quote.gamma
            leg_vega = getattr(quote, 'vega', 0.0)  # May not exist
            leg_theta = quote.theta
            
            # Apply sign convention: long = +, short = -
            multiplier = leg.quantity if leg.action == 'buy' else -leg.quantity
            
            net_delta += leg_delta * multiplier
            net_gamma += leg_gamma * multiplier
            net_vega += leg_vega * multiplier
            net_theta += leg_theta * multiplier
        
        # Populate trade greeks
        trade.greeks = {
            'delta': round(net_delta, 4),
            'gamma': round(net_gamma, 6),
            'vega': round(net_vega, 4),
            'theta': round(net_theta, 4),
            'source': source.value
        }
