import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class JadeLizardStrategy:
    def __init__(self, 
                 min_dte: int = 30, 
                 max_dte: int = 60):
        self.min_dte = min_dte
        self.max_dte = max_dte

    @property
    def name(self) -> str:
        return "Jade Lizard"

    def is_eligible(self, market: MarketState) -> bool:
        # Income strategy, needs High IV to generate enough credit to cover the spread width.
        if market.hv20 < 0.20:
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

        # Standard Jade Lizard (Bullish/Neutral)
        # Sell Put OTM (~Spot * 0.95)
        # Sell Call Spread OTM (~Spot * 1.05)
        
        short_put_k = get_strike(market.spot * 0.95, "put")
        short_call_k = get_strike(market.spot * 1.05, "call")
        long_call_k = get_strike(market.spot * 1.07, "call") # 2% wide
        
        if short_put_k and short_call_k and long_call_k:
            # Check pricing
            m_sp, _ = mid_iv(chain, "put", short_put_k)
            m_sc, _ = mid_iv(chain, "call", short_call_k)
            m_lc, _ = mid_iv(chain, "call", long_call_k)
            
            if m_sp and m_sc and m_lc:
                credit = m_sp + (m_sc - m_lc)
                width = long_call_k - short_call_k
                
                # Eliminate Upside Risk check
                # Ideally Credit > Width.
                # If Credit < Width, there is small upside risk.
                # We will tag it as "Jade Lizard" if risk is eliminated or minimal.
                
                no_upside_risk = credit >= width
                
                legs = [
                    Leg(market.ticker, short_put_k, expiry, "put", "sell"),
                    Leg(market.ticker, short_call_k, expiry, "call", "sell"),
                    Leg(market.ticker, long_call_k, expiry, "call", "buy")
                ]
                
                desc = f"Jade Lizard -{short_put_k}P / -{short_call_k}C+{long_call_k}C"
                if no_upside_risk:
                    desc += " (No Upside Risk)"
                
                candidates.append(CandidateTrade(
                    strategy_name="Jade Lizard",
                    ticker=market.ticker,
                    legs=legs,
                    debit=round(-credit * 100, 2),
                    max_loss=float('inf'), # Naked Put Risk
                    max_profit=round(credit * 100, 2),
                    breakevens=[short_put_k - credit], # Only downside BE if no upside risk
                    pop=None,  # POP not computed
                    pop_label=POP_LABEL_UNVERIFIED,
                    description=desc
                ))
                
        return candidates
