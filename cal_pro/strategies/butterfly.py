import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class ButterflyStrategy:
    def __init__(self, 
                 min_dte: int = 20, 
                 max_dte: int = 45,
                 width_pct: float = 0.02):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.width_pct = width_pct

    @property
    def name(self) -> str:
        return "Long Butterfly"

    def is_eligible(self, market: MarketState) -> bool:
        # Neutral strategy. Low Volatility preferred?
        # Actually, buying butterflies is cheaper when IV is high at wings vs center (smile).
        # But generally, we want the stock to stay still.
        if market.adx14 > 25:
            return False
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        
        valid_exps = [e for e in chains.keys() if self.min_dte <= (e - today).days <= self.max_dte]
        if not valid_exps: return []
        expiry = valid_exps[0]
        chain = chains[expiry]
        
        # Helper
        def get_strike(target, right):
            opts = [o for o in chain.options if o.right == right]
            if not opts: return None
            return min(opts, key=lambda o: abs(o.strike - target)).strike

        # Center at ATM
        center_k = get_strike(market.spot, "call")
        
        if not center_k: return []
        
        width = center_k * self.width_pct
        lower_target = center_k - width
        upper_target = center_k + width
        
        lower_k = get_strike(lower_target, "call")
        upper_k = get_strike(upper_target, "call")
        
        if not lower_k or not upper_k: return []
        
        # Check symmetry
        # Ideally lower_k, center_k, upper_k are equidistant
        # If not, it's a "Broken Wing Butterfly" which implies risk
        # Let's try to enforce symmetry or allow slight asymmetry
        
        # Construct Long Call Fly: +1 Lower, -2 Center, +1 Upper
        m_low, _ = mid_iv(chain, "call", lower_k)
        m_cen, _ = mid_iv(chain, "call", center_k)
        m_upp, _ = mid_iv(chain, "call", upper_k)
        
        if m_low and m_cen and m_upp:
            debit = m_low + m_upp - (2 * m_cen)
            
            if debit > 0:
                max_loss = debit
                max_profit = (center_k - lower_k) - debit
                
                legs = [
                    Leg(market.ticker, lower_k, expiry, "call", "buy", 1),
                    Leg(market.ticker, center_k, expiry, "call", "sell", 2),
                    Leg(market.ticker, upper_k, expiry, "call", "buy", 1)
                ]
                
                candidates.append(CandidateTrade(
                    strategy_name="Long Call Butterfly",
                    ticker=market.ticker,
                    legs=legs,
                    debit=round(debit * 100, 2),
                    max_loss=round(max_loss * 100, 2),
                    max_profit=round(max_profit * 100, 2),
                    breakevens=[lower_k + debit, upper_k - debit],
                    pop=None,  # POP not computed
                    pop_label=POP_LABEL_UNVERIFIED,
                    description=f"Fly {lower_k}/{center_k}/{upper_k}"
                ))
                
        return candidates
