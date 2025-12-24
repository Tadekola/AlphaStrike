import datetime as dt
import math
import numpy as np
from typing import List, Dict, Any, Tuple

from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_VERIFIED
from ..engine.utils import pick_exp, mid_iv, nearest_common_strike, round_strike
from ..bs import bs_price

class CalendarStrategy:
    def __init__(self, 
                 front_min: int = 7, 
                 front_max: int = 10, 
                 back_min: int = 56, 
                 back_max: int = 80,
                 pop_min: float = 0.55):
        self.front_min = front_min
        self.front_max = front_max
        self.back_min = back_min
        self.back_max = back_max
        self.pop_min = pop_min

    @property
    def name(self) -> str:
        return "Calendar Spread"

    def is_eligible(self, market: MarketState) -> bool:
        # Gates from original engine + Expert GEX/Regime
        
        # 1. RSI Gate (35-65) - slightly wider
        if not (35 <= market.rsi14 <= 65):
            return False
            
        # 2. HV Gate (HV5 <= HV20) - Expect vol expansion? 
        # Actually Calendars want IV to rise, so entering in low vol is good.
        if market.hv5 > market.hv20 * 1.2: # Allow slight elevation
            return False
            
        # 3. Band Gate
        dist = abs(market.spot - market.sma20)
        limit = max(1.5 * market.atr5, 0.5)
        if dist > limit:
            return False

        # 4. Expert: ADX Gate (Trend Strength)
        # Calendars hurt by strong trends.
        if market.adx14 > 30:
            return False
            
        # 5. Expert: GEX Filter
        # Negative GEX often implies high realized vol/instability.
        # We prefer stability for calendars (unless playing earnings vol crush).
        # For now, just warn/score, but maybe gate if extreme negative gamma?
        # Let's keep it open but use it in scoring.
            
        return True

    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]:
        candidates = []
        
        # Logic adapted from engine.py
        try:
            front, back = pick_exp(self.front_min, self.front_max, self.back_min, self.back_max, list(chains.keys()), relax=True)
        except Exception:
            return []
            
        ch_front = chains[front]
        ch_back = chains[back]
        
        dte_front = (front - dt.date.today()).days
        dte_back = (back - dt.date.today()).days
        
        # Estimate ATM IV
        # Simple approach: Average of first few options or find nearest to spot
        # But here we rely on what we can find.
        # Let's find nearest to spot in front chain
        f_iv = 0.0
        if ch_front.options:
            closest = min(ch_front.options, key=lambda o: abs(o.strike - market.spot))
            f_iv = closest.iv
            
        T1 = max(dte_front / 365.0, 1/365)
        EM = market.spot * f_iv * math.sqrt(T1)
        
        # Strikes
        strike_step = 1.0
        em_multiple = 0.7
        
        raw_K_call = round_strike(market.spot + em_multiple * EM, strike_step)
        raw_K_put = round_strike(market.spot - em_multiple * EM, strike_step)
        
        snap_call = nearest_common_strike(ch_front, ch_back, raw_K_call, "call")
        snap_put = nearest_common_strike(ch_front, ch_back, raw_K_put, "put")
        
        targets = []
        if snap_call: targets.append(("call", snap_call))
        if snap_put: targets.append(("put", snap_put))
        
        for side, K in targets:
            m_front, iv_front = mid_iv(ch_front, side, K)
            m_back, iv_back = mid_iv(ch_back, side, K)
            
            if m_front is None or m_back is None: continue
            
            debit = m_back - m_front
            if debit <= 0: continue
            
            # Payoff analysis
            pl_grid, be_low, be_high, best_pl, best_S, pop = self._analyze_payoff(
                side, K, market.spot, dte_front, dte_back, iv_front or f_iv, iv_back or f_iv, debit
            )
            
            if pop < self.pop_min:
                continue
                
            legs = [
                Leg(market.ticker, K, front, side, "sell", 1),
                Leg(market.ticker, K, back, side, "buy", 1)
            ]
            
            ct = CandidateTrade(
                strategy_name="Calendar",
                ticker=market.ticker,
                legs=legs,
                debit=round(debit * 100, 2),
                max_loss=round(debit * 100, 2),
                max_profit=round(best_pl, 2),
                breakevens=[be_low, be_high],
                pop=pop,
                pop_label=POP_LABEL_VERIFIED,  # Calendar computes POP via Monte Carlo integration
                description=f"{side.upper()} Calendar @ {K}",
                metrics={
                    "front_dte": dte_front,
                    "back_dte": dte_back,
                    "best_S": best_S
                }
            )
            candidates.append(ct)
            
        return candidates

    def _analyze_payoff(self, side, K, S0, front_dte, back_dte, front_iv, back_iv, debit, grid_pct=0.15):
        T1 = max(front_dte / 365.0, 1 / 365)
        T2 = max((back_dte - front_dte) / 365.0, 1 / 365)

        Slo = S0 * (1 - grid_pct)
        Shi = S0 * (1 + grid_pct)
        Sgrid = np.linspace(Slo, Shi, 401)
        pl = np.zeros_like(Sgrid)

        for i, S in enumerate(Sgrid):
            if side == "call":
                short_intr = max(S - K, 0.0)
                long_val = bs_price(S, K, back_iv, T2, right="call")
            else:
                short_intr = max(K - S, 0.0)
                long_val = bs_price(S, K, back_iv, T2, right="put")
            pl[i] = (long_val - short_intr - debit) * 100.0

        sign = np.sign(pl)
        zc = np.where(np.diff(sign))[0]
        be_low = float(Sgrid[zc[0]]) if len(zc) >= 1 else float("nan")
        be_high = float(Sgrid[zc[-1] + 1]) if len(zc) >= 1 else float("nan")

        best_idx = int(np.nanargmax(pl))
        best_pl = float(pl[best_idx])
        best_S = float(Sgrid[best_idx])

        # POP
        sigma = max(front_iv, 1e-6)
        def cdf(x):
            if x <= 0: return 0.0
            d2 = (math.log(S0 / x) - 0.5 * sigma * sigma * T1) / (sigma * math.sqrt(T1))
            return 0.5 * (1.0 - math.erf(d2 / math.sqrt(2.0)))

        weights = []
        for i in range(len(Sgrid) - 1):
            a, b = Sgrid[i], Sgrid[i + 1]
            w = max(0.0, min(1.0, cdf(b) - cdf(a)))
            weights.append(w)
        w = np.array(weights)
        w = w / (w.sum() + 1e-12)

        pos = (pl[:-1] > 0) | (pl[1:] > 0)
        pop = float((w[pos]).sum()) if w.size else 0.0
        
        return pl, be_low, be_high, best_pl, best_S, pop
