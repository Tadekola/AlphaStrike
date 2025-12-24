import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class ShortStrangleStrategy:
    def __init__(self, 
                 min_dte: int = 30, 
                 max_dte: int = 60,
                 delta_target: float = 0.16):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.delta_target = delta_target

    @property
    def name(self) -> str:
        return "Short Strangle"

    def is_eligible(self, market: MarketState) -> bool:
        # Pure volatility play. Requires High IV to justify the undefined risk.
        if market.hv20 < 0.15:
            return False
            
        # Avoid if market is extremely trending (ADX > 40) as strangles get tested
        if market.adx14 > 40:
            return False
            
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        
        valid_exps = [e for e in chains.keys() if self.min_dte <= (e - today).days <= self.max_dte]
        if not valid_exps: return []
        
        expiry = valid_exps[0]
        chain = chains[expiry]
        
        # Target Deltas (approx via Strike vs Spot)
        # 16 Delta Strangle approx 1 Std Dev OTM
        # Put Strike ~ Spot * (1 - IV * sqrt(T))? 
        # Using simple % OTM proxy for now: 16 delta ~ 5-8% OTM usually?
        # Let's use a smarter lookup if we had delta, but here we scan for approx range.
        
        # Use a simple percent OTM based on IV proxy
        # If IV is 20%, 1SD move in 45 days is ~ 20% * sqrt(45/365) = 7%
        iv_est = market.hv20 # Use realized as proxy if implied not avail easily
        dte = (expiry - today).days
        move_est = iv_est * (dte / 365.0)**0.5
        
        target_put_k = market.spot * (1 - move_est)
        target_call_k = market.spot * (1 + move_est)
        
        short_put_k = self._snap_strike(chain, target_put_k, "put")
        short_call_k = self._snap_strike(chain, target_call_k, "call")
        
        if not short_put_k or not short_call_k: return []
        
        mp_short, _ = mid_iv(chain, "put", short_put_k)
        mc_short, _ = mid_iv(chain, "call", short_call_k)
        
        if not mp_short or not mc_short: return []
        
        credit = mp_short + mc_short
        
        # Metrics
        legs = [
            Leg(market.ticker, short_put_k, expiry, "put", "sell"),
            Leg(market.ticker, short_call_k, expiry, "call", "sell")
        ]
        
        candidates.append(CandidateTrade(
            strategy_name="Short Strangle",
            ticker=market.ticker,
            legs=legs,
            debit=round(-credit * 100, 2),
            max_loss=float('inf'), # Undefined risk
            max_profit=round(credit * 100, 2),
            breakevens=[short_put_k - credit, short_call_k + credit],
            pop=None,  # POP not computed - requires delta-based calculation
            pop_label=POP_LABEL_UNVERIFIED,
            description=f"Strangle {short_put_k}/{short_call_k}"
        ))
        
        return candidates

    def _snap_strike(self, chain, target, right):
        opts = [o for o in chain.options if o.right == right]
        if not opts: return None
        return min(opts, key=lambda o: abs(o.strike - target)).strike
