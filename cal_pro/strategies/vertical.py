import datetime as dt
from typing import List, Dict, Any, Optional
from ..engine.base_strategy import CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

POP_LABEL_DELTA_PROXY = "DELTA_PROXY (estimate only)"

class VerticalStrategy:
    def __init__(self, 
                 width_pct: float = 0.01, # 1% width
                 min_dte: int = 30, 
                 max_dte: int = 45):
        self.width_pct = width_pct
        self.min_dte = min_dte
        self.max_dte = max_dte

    @property
    def name(self) -> str:
        return "Vertical Spread"

    def is_eligible(self, market: MarketState) -> bool:
        # Vertical Spreads work best in trending markets.
        # If ADX is very low, better to do Iron Condor / Calendar.
        if market.adx14 < 20:
            return False
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        
        valid_exps = [e for e in chains.keys() if self.min_dte <= (e - today).days <= self.max_dte]
        if not valid_exps: return []
        
        expiry = valid_exps[0]
        chain = chains[expiry]
        
        # Determine Trend
        is_bullish = market.spot > market.sma20
        
        # Snap helper
        def get_nearest_strike(c, target_k, right):
            opts = [o for o in c.options if o.right == right]
            if not opts: return None
            return min(opts, key=lambda o: abs(o.strike - target_k)).strike

        if is_bullish:
            # Bull Put Spread (Credit)
            raw_short = market.spot * 0.98
            raw_long = market.spot * 0.96
            
            short_k = get_nearest_strike(chain, raw_short, "put")
            long_k = get_nearest_strike(chain, raw_long, "put")
            
            if short_k and long_k and short_k != long_k:
                m_short, _ = mid_iv(chain, "put", short_k)
                m_long, _ = mid_iv(chain, "put", long_k)
                
                if m_short and m_long and m_short > m_long:
                    credit = m_short - m_long
                    width = short_k - long_k
                    max_loss = width - credit
                    
                    if max_loss > 0:
                        legs = [
                            Leg(market.ticker, short_k, expiry, "put", "sell"),
                            Leg(market.ticker, long_k, expiry, "put", "buy")
                        ]
                        # Estimate POP using delta proxy
                        pop_estimate = self._estimate_pop_delta_proxy(chain, short_k, "put")
                        
                        candidates.append(CandidateTrade(
                            strategy_name="Bull Put Vertical",
                            ticker=market.ticker,
                            legs=legs,
                            debit=round(-credit * 100, 2),
                            max_loss=round(max_loss * 100, 2),
                            max_profit=round(credit * 100, 2),
                            breakevens=[short_k - credit],
                            pop=pop_estimate,
                            pop_label=POP_LABEL_DELTA_PROXY if pop_estimate else POP_LABEL_UNVERIFIED,
                            description=f"Bull Put {short_k}/{long_k}"
                        ))
        else:
            # Bear Call Spread (Credit)
            raw_short = market.spot * 1.02
            raw_long = market.spot * 1.04
            
            short_k = get_nearest_strike(chain, raw_short, "call")
            long_k = get_nearest_strike(chain, raw_long, "call")
            
            if short_k and long_k and short_k != long_k:
                m_short, _ = mid_iv(chain, "call", short_k)
                m_long, _ = mid_iv(chain, "call", long_k)
                
                if m_short and m_long and m_short > m_long:
                    credit = m_short - m_long
                    width = long_k - short_k
                    max_loss = width - credit
                    
                    if max_loss > 0:
                        legs = [
                            Leg(market.ticker, short_k, expiry, "call", "sell"),
                            Leg(market.ticker, long_k, expiry, "call", "buy")
                        ]
                        # Estimate POP using delta proxy
                        pop_estimate = self._estimate_pop_delta_proxy(chain, short_k, "call")
                        
                        candidates.append(CandidateTrade(
                            strategy_name="Bear Call Vertical",
                            ticker=market.ticker,
                            legs=legs,
                            debit=round(-credit * 100, 2),
                            max_loss=round(max_loss * 100, 2),
                            max_profit=round(credit * 100, 2),
                            breakevens=[short_k + credit],
                            pop=pop_estimate,
                            pop_label=POP_LABEL_DELTA_PROXY if pop_estimate else POP_LABEL_UNVERIFIED,
                            description=f"Bear Call {short_k}/{long_k}"
                        ))

        return candidates
    
    def _estimate_pop_delta_proxy(self, chain, short_strike: float, right: str) -> Optional[float]:
        """Estimate POP using delta as probability proxy.
        
        For credit spreads:
        - Bull Put: POP ≈ 1 - |short put delta| (probability put expires OTM)
        - Bear Call: POP ≈ 1 - |short call delta| (probability call expires OTM)
        
        This is an APPROXIMATION. Deltas are not exact probabilities.
        """
        short_opt = next((o for o in chain.options if o.right == right and o.strike == short_strike), None)
        
        if not short_opt or short_opt.delta is None:
            return None
        
        # For credit spreads, POP = probability short strike expires OTM
        # Put delta is negative, call delta is positive
        # P(OTM) ≈ 1 - |delta|
        itm_prob = abs(short_opt.delta)
        pop = 1.0 - itm_prob
        
        return max(0.0, min(1.0, round(pop, 2)))
