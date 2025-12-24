import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class IronButterflyStrategy:
    def __init__(self, 
                 min_dte: int = 30, 
                 max_dte: int = 60,
                 wing_width_pct: float = 0.05):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.wing_width_pct = wing_width_pct

    @property
    def name(self) -> str:
        return "Iron Butterfly"

    def is_eligible(self, market: MarketState) -> bool:
        # Aggressive neutral strategy
        # Requires solid range environment (ADX < 25) and high vol to pay for the wings
        
        if market.adx14 > 25:
            return False
            
        if market.hv20 < 0.15:
            return False
            
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        
        valid_exps = [e for e in chains.keys() if self.min_dte <= (e - today).days <= self.max_dte]
        if not valid_exps: return []
        
        expiry = valid_exps[0]
        chain = chains[expiry]
        
        # ATM Strike
        atm_k = self._snap_strike(chain, market.spot, "call")
        if not atm_k: return []
        
        # Wings
        lower_target = atm_k * (1 - self.wing_width_pct)
        upper_target = atm_k * (1 + self.wing_width_pct)
        
        lower_k = self._snap_strike(chain, lower_target, "put")
        upper_k = self._snap_strike(chain, upper_target, "call")
        
        if not lower_k or not upper_k: return []
        
        # Prices
        m_atm_call, _ = mid_iv(chain, "call", atm_k)
        m_atm_put, _ = mid_iv(chain, "put", atm_k)
        m_lower_put, _ = mid_iv(chain, "put", lower_k)
        m_upper_call, _ = mid_iv(chain, "call", upper_k)
        
        if any(x is None for x in [m_atm_call, m_atm_put, m_lower_put, m_upper_call]): return []
        
        # Sell Straddle, Buy Wings
        credit_straddle = m_atm_call + m_atm_put
        debit_wings = m_lower_put + m_upper_call
        net_credit = credit_straddle - debit_wings
        
        if net_credit <= 0: return []
        
        width = atm_k - lower_k # Symmetric approx
        max_loss = width - net_credit
        
        legs = [
            Leg(market.ticker, lower_k, expiry, "put", "buy"),
            Leg(market.ticker, atm_k, expiry, "put", "sell"),
            Leg(market.ticker, atm_k, expiry, "call", "sell"),
            Leg(market.ticker, upper_k, expiry, "call", "buy"),
        ]
        
        candidates.append(CandidateTrade(
            strategy_name="Iron Butterfly",
            ticker=market.ticker,
            legs=legs,
            debit=round(-net_credit * 100, 2),
            max_loss=round(max_loss * 100, 2),
            max_profit=round(net_credit * 100, 2),
            breakevens=[atm_k - net_credit, atm_k + net_credit],
            pop=None,  # POP not computed
            pop_label=POP_LABEL_UNVERIFIED,
            description=f"IB {lower_k}/{atm_k}/{upper_k}"
        ))
        
        return candidates

    def _snap_strike(self, chain, target, right):
        opts = [o for o in chain.options if o.right == right]
        if not opts: return None
        return min(opts, key=lambda o: abs(o.strike - target)).strike
