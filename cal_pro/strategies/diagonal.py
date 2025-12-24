import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class DiagonalStrategy:
    def __init__(self, 
                 min_front_dte: int = 20, 
                 max_front_dte: int = 45,
                 min_back_dte: int = 120):
        self.min_front_dte = min_front_dte
        self.max_front_dte = max_front_dte
        self.min_back_dte = min_back_dte

    @property
    def name(self) -> str:
        return "Long Diagonal (PMCC)"

    def is_eligible(self, market: MarketState) -> bool:
        # Bullish strategy. Needs uptrend.
        # Also prefers lower IV for buying the LEAP.
        if market.spot < market.sma20:
            return False
            
        # If Vol is extremely high, buying LEAPS is expensive.
        if market.hv20 > 0.40:
            return False
            
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        exps = sorted(chains.keys())
        
        # 1. Find Front Expiry
        fronts = [e for e in exps if self.min_front_dte <= (e - today).days <= self.max_front_dte]
        if not fronts: return []
        front_exp = fronts[0]
        
        # 2. Find Back Expiry (LEAP)
        backs = [e for e in exps if (e - today).days >= self.min_back_dte]
        if not backs:
            # Fallback: longest available if > 90 days
            if exps[-1] > today + dt.timedelta(days=90):
                backs = [exps[-1]]
            else:
                return []
        back_exp = backs[0] # Pick nearest LEAP to save capital
        
        ch_front = chains[front_exp]
        ch_back = chains[back_exp]
        
        # 3. Select Strikes
        # Long: Deep ITM (~80 Delta). Proxy: Strike ~ Spot * 0.75? or 0.8?
        # Short: OTM (~30 Delta). Proxy: Strike ~ Spot * 1.05?
        
        long_target = market.spot * 0.85 # Approx 70-80 delta
        short_target = market.spot * 1.03 # Approx 30 delta
        
        long_k = self._snap_strike(ch_back, long_target, "call")
        short_k = self._snap_strike(ch_front, short_target, "call")
        
        if not long_k or not short_k: return []
        
        # Ensure Diagonal Width is safe (Strike Distance > Debit Paid ideally, but simpler check here)
        if short_k <= long_k: return [] # Invalid structure
        
        # Pricing
        m_long, _ = mid_iv(ch_back, "call", long_k)
        m_short, _ = mid_iv(ch_front, "call", short_k)
        
        if not m_long or not m_short: return []
        
        debit = m_long - m_short
        
        # Breakeven approx: Long Strike + Debit
        be = long_k + debit
        
        legs = [
            Leg(market.ticker, long_k, back_exp, "call", "buy"),
            Leg(market.ticker, short_k, front_exp, "call", "sell")
        ]
        
        candidates.append(CandidateTrade(
            strategy_name="PMCC / Diagonal",
            ticker=market.ticker,
            legs=legs,
            debit=round(debit * 100, 2),
            max_loss=round(debit * 100, 2),
            max_profit=float("inf"), # Technically capped but complex to calc exact without curves
            breakevens=[be],
            pop=None,  # POP not computed
            pop_label=POP_LABEL_UNVERIFIED,
            description=f"Diag +{long_k}C(LEAP) / -{short_k}C"
        ))
        
        return candidates

    def _snap_strike(self, chain, target, right):
        opts = [o for o in chain.options if o.right == right]
        if not opts: return None
        return min(opts, key=lambda o: abs(o.strike - target)).strike
