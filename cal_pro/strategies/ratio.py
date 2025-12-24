import datetime as dt
from typing import List, Dict, Any
from ..engine.base_strategy import Strategy, CandidateTrade, Leg, MarketState, POP_LABEL_UNVERIFIED
from ..engine.utils import mid_iv

class RatioStrategy:
    def __init__(self, 
                 min_dte: int = 30, 
                 max_dte: int = 60,
                 ratio: tuple = (1, 2)):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.ratio = ratio # Buy 1, Sell 2

    @property
    def name(self) -> str:
        return "Ratio Spread (1x2)"

    def is_eligible(self, market: MarketState) -> bool:
        # Expert strategy. Requires understanding of Skew and Naked Risk.
        # Works best when IV is high (to get credit on the 2 short legs).
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

        # Determine Trend for Direction
        # Bullish -> Put Ratio (Bullish to Neutral) or Call Ratio (Bullish w/ Naked Risk)?
        # Classic "Front Ratio": 
        # Put Ratio: Buy ATM Put, Sell 2 OTM Puts. (Bullish/Neutral/Slightly Bearish). Risk is downside.
        # Call Ratio: Buy ATM Call, Sell 2 OTM Calls. (Bearish/Neutral/Slightly Bullish). Risk is upside.
        
        # Let's implement Call Ratio if Bullish (targeting move to short strike)
        # And Put Ratio if Bearish (targeting move to short strike)
        # Wait, typical Ratio Spread is for credit.
        
        is_bullish = market.spot > market.sma20
        
        # Helper
        def get_strike(target, right):
            opts = [o for o in chain.options if o.right == right]
            if not opts: return None
            return min(opts, key=lambda o: abs(o.strike - target)).strike

        # Target: Buy ~ATM, Sell ~OTM (approx 2 strike steps away)
        # Or Buy 30 Delta, Sell 15 Delta x2
        
        if is_bullish:
            # Call Ratio (Bullish direction, but capped profit, unlimited risk above break even)
            # Actually, Call Ratio is often done for a credit to have zero downside risk.
            # "Call Ratio Backspread" is buy 2, sell 1. 
            # "Call Front Ratio" is Buy 1, Sell 2.
            
            # Implementation: Call Front Ratio (1x2)
            # Buy 1 ATM Call, Sell 2 OTM Calls
            buy_k = get_strike(market.spot * 1.02, "call")
            sell_k = get_strike(market.spot * 1.06, "call")
            
            if buy_k and sell_k and buy_k < sell_k:
                m_buy, _ = mid_iv(chain, "call", buy_k)
                m_sell, _ = mid_iv(chain, "call", sell_k)
                
                if m_buy and m_sell:
                    net = (m_sell * 2) - m_buy
                    
                    # Breakeven upper = Sell Strike + (Width + Net Credit)
                    width = sell_k - buy_k
                    be = sell_k + width + net
                    
                    legs = [
                        Leg(market.ticker, buy_k, expiry, "call", "buy", 1),
                        Leg(market.ticker, sell_k, expiry, "call", "sell", 2)
                    ]
                    
                    candidates.append(CandidateTrade(
                        strategy_name="Call Ratio 1x2",
                        ticker=market.ticker,
                        legs=legs,
                        debit=round(-net * 100, 2), # Credit
                        max_loss=float('inf'),
                        max_profit=round((width + net) * 100, 2),
                        breakevens=[be],
                        pop=None,  # POP not computed
                        pop_label=POP_LABEL_UNVERIFIED,
                        description=f"Call Ratio +{buy_k}/-2x{sell_k}"
                    ))
        
        else:
            # Put Front Ratio (1x2)
            # Buy 1 ATM Put, Sell 2 OTM Puts
            buy_k = get_strike(market.spot * 0.98, "put")
            sell_k = get_strike(market.spot * 0.94, "put")
            
            if buy_k and sell_k and buy_k > sell_k:
                m_buy, _ = mid_iv(chain, "put", buy_k)
                m_sell, _ = mid_iv(chain, "put", sell_k)
                
                if m_buy and m_sell:
                    net = (m_sell * 2) - m_buy
                    
                    width = buy_k - sell_k
                    be = sell_k - (width + net)
                    
                    legs = [
                        Leg(market.ticker, buy_k, expiry, "put", "buy", 1),
                        Leg(market.ticker, sell_k, expiry, "put", "sell", 2)
                    ]
                    
                    candidates.append(CandidateTrade(
                        strategy_name="Put Ratio 1x2",
                        ticker=market.ticker,
                        legs=legs,
                        debit=round(-net * 100, 2),
                        max_loss=float('inf'),
                        max_profit=round((width + net) * 100, 2),
                        breakevens=[be],
                        pop=None,  # POP not computed
                        pop_label=POP_LABEL_UNVERIFIED,
                        description=f"Put Ratio +{buy_k}/-2x{sell_k}"
                    ))
                    
        return candidates
