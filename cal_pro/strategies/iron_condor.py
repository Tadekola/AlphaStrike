import datetime as dt
from typing import List, Dict, Any, Optional
from ..engine.base_strategy import CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED, POP_LABEL_DELTA_PROXY
from ..engine.utils import mid_iv

class IronCondorStrategy:
    def __init__(self, 
                 min_dte: int = 30, 
                 max_dte: int = 60,
                 short_delta: float = 0.20,
                 wing_width_pct: float = 0.05):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.short_delta = short_delta
        self.wing_width_pct = wing_width_pct

    @property
    def name(self) -> str:
        return "Iron Condor"

    def is_eligible(self, market: MarketState) -> bool:
        # Best for high IV rank, range-bound
        
        # 1. Range-bound: ADX < 30
        if market.adx14 > 30:
            return False
            
        # 2. Volatility: Prefer elevated vol to sell
        # If HV20 is extremely low, premiums are cheap, so we might skip IC.
        if market.hv20 < 0.10: # < 10% realized vol is very quiet
            return False
            
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        today = dt.date.today()
        
        valid_exps = [e for e in chains.keys() if self.min_dte <= (e - today).days <= self.max_dte]
        if not valid_exps: return []
        
        expiry = valid_exps[0] 
        chain = chains[expiry]
        
        # Helper to find strikes
        def get_strike_by_delta_approx(c, right, target_delta_proxy):
            # Proxy: for Put, Strike < Spot. For Call, Strike > Spot.
            # We don't have real delta, so we estimate via % OTM
            # 0.20 delta approx 1 std dev OTM? Or just use fixed %?
            # Let's use simple % OTM for robust mock/tradier without full greek stream
            # Short Put ~ 5-8% OTM? Short Call ~ 5-8% OTM?
            return min(c.options, key=lambda o: abs(o.strike - target_delta_proxy)).strike

        # Estimate short strikes based on spot
        # Short Put ~ Spot * (1 - 0.05)
        # Short Call ~ Spot * (1 + 0.05)
        short_put_target = market.spot * 0.95
        short_call_target = market.spot * 1.05
        
        short_put_k = self._snap_strike(chain, short_put_target, "put")
        short_call_k = self._snap_strike(chain, short_call_target, "call")
        
        if not short_put_k or not short_call_k: return []
        
        # Wings
        long_put_target = short_put_k * (1 - self.wing_width_pct)
        long_call_target = short_call_k * (1 + self.wing_width_pct)
        
        long_put_k = self._snap_strike(chain, long_put_target, "put")
        long_call_k = self._snap_strike(chain, long_call_target, "call")
        
        if not long_put_k or not long_call_k: return []
        
        # Pricing
        _, sp_bid = mid_iv(chain, "put", short_put_k) # Use mid for now
        _, lp_ask = mid_iv(chain, "put", long_put_k)
        _, sc_bid = mid_iv(chain, "call", short_call_k)
        _, lc_ask = mid_iv(chain, "call", long_call_k)
        
        # mid_iv returns (mid, iv). Let's grab mids.
        mp_short, _ = mid_iv(chain, "put", short_put_k)
        mp_long, _ = mid_iv(chain, "put", long_put_k)
        mc_short, _ = mid_iv(chain, "call", short_call_k)
        mc_long, _ = mid_iv(chain, "call", long_call_k)
        
        if any(x is None for x in [mp_short, mp_long, mc_short, mc_long]): return []
        
        put_credit = mp_short - mp_long
        call_credit = mc_short - mc_long
        total_credit = put_credit + call_credit
        
        if total_credit <= 0: return []
        
        # Risks
        width_put = short_put_k - long_put_k
        width_call = long_call_k - short_call_k
        max_width = max(width_put, width_call)
        max_loss = max_width - total_credit
        
        legs = [
            Leg(market.ticker, long_put_k, expiry, "put", "buy"),
            Leg(market.ticker, short_put_k, expiry, "put", "sell"),
            Leg(market.ticker, short_call_k, expiry, "call", "sell"),
            Leg(market.ticker, long_call_k, expiry, "call", "buy"),
        ]
        
        # Estimate POP using delta-based proxy
        # For Iron Condor: POP ≈ 1 - |short_put_delta| - |short_call_delta|
        # This assumes deltas approximate probability of expiring ITM
        pop_estimate = self._estimate_pop_delta_proxy(chain, short_put_k, short_call_k)
        
        candidates.append(CandidateTrade(
            strategy_name="Iron Condor",
            ticker=market.ticker,
            legs=legs,
            debit=round(-total_credit * 100, 2), # Credit
            max_loss=round(max_loss * 100, 2),
            max_profit=round(total_credit * 100, 2),
            breakevens=[short_put_k - total_credit, short_call_k + total_credit],
            pop=pop_estimate,
            pop_label=POP_LABEL_DELTA_PROXY if pop_estimate else POP_LABEL_UNVERIFIED,
            description=f"IC {long_put_k}/{short_put_k} | {short_call_k}/{long_call_k}"
        ))
        
        return candidates

    def _snap_strike(self, chain, target, right):
        opts = [o for o in chain.options if o.right == right]
        if not opts: return None
        return min(opts, key=lambda o: abs(o.strike - target)).strike
    
    def _estimate_pop_delta_proxy(self, chain, short_put_k: float, short_call_k: float) -> Optional[float]:
        """Estimate POP using delta as probability proxy.
        
        For an Iron Condor:
        - Short put delta ≈ probability of put expiring ITM (negative value)
        - Short call delta ≈ probability of call expiring ITM (positive value)
        - POP ≈ 1 - P(short put ITM) - P(short call ITM)
        
        This is an APPROXIMATION. Deltas are not exact probabilities.
        """
        short_put = next((o for o in chain.options if o.right == 'put' and o.strike == short_put_k), None)
        short_call = next((o for o in chain.options if o.right == 'call' and o.strike == short_call_k), None)
        
        if not short_put or not short_call:
            return None
        
        # Put delta is negative, represents P(ITM) as absolute value
        put_itm_prob = abs(short_put.delta) if short_put.delta else 0.15
        # Call delta is positive, represents P(ITM) directly
        call_itm_prob = abs(short_call.delta) if short_call.delta else 0.15
        
        # POP = 1 - P(either short expires ITM)
        # Simplified: assumes independence (not perfectly accurate but reasonable estimate)
        pop = 1.0 - put_itm_prob - call_itm_prob
        
        return max(0.0, min(1.0, pop))
