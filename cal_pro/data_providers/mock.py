"""
MOCK DATA PROVIDER
------------------
For testing and development only.
Disabled by default.
Requires ALLOW_MOCK_DATA=true environment variable to activate.

WARNING: NOT FOR REAL TRADING.
This provider generates synthetic data for UI testing and development.
It does not reflect real market conditions and must never be used
to make actual trading decisions.
"""
import datetime as dt
import os
from typing import List
from .base import DataProvider, Bar, Chain, OptionQuote

# Environment variable to explicitly allow mock data
ALLOW_MOCK_DATA_ENV = "ALLOW_MOCK_DATA"


def is_mock_allowed() -> bool:
    """Check if mock data is explicitly allowed via environment variable."""
    return os.getenv(ALLOW_MOCK_DATA_ENV, "").lower() == "true"


class MockProvider:
    def __init__(self, ticker: str):
        self.ticker = ticker

    def spot(self) -> float: 
        return 650.0

    def history(self, days: int=60) -> List[Bar]:
        t = dt.date.today()
        lvl = self.spot() - 1.5
        out = []
        for i in range(days,0,-1):
            lvl += 0.15 if i%7 in (2,3,4) else -0.12
            c = round(lvl, 2)
            out.append(Bar(t - dt.timedelta(days=i), c, round(c*1.01,2), round(c*0.99,2)))
        return out

    def expirations(self) -> List[dt.date]:
        t = dt.date.today()
        first_fri = t + dt.timedelta(days=(4 - t.weekday()) % 7)
        return [first_fri + dt.timedelta(days=7*k) for k in range(1,20)]

    def chain(self, expiry: dt.date) -> Chain:
        s = self.spot(); opts = []
        for k in range(550, 750, 5):
            m = abs(k - s)/s
            iv = 0.18 + 0.08*m
            mid = max(0.15, 4.0 - abs(k-s)/60)
            # Mock bid/ask spread
            spread = mid * 0.05
            bid = mid - spread/2
            ask = mid + spread/2
            
            # Mock fields
            base_oi = int(1000 * (1 - abs(k-s)/(s*0.2)))
            base_oi = max(10, base_oi)
            
            # Skew OI: Puts higher below spot, Calls higher above
            call_oi = int(base_oi * (1.2 if k > s else 0.8))
            put_oi = int(base_oi * (1.2 if k < s else 0.8))
            
            # Mock Greeks (rough approx)
            delta = 0.5 if k==s else (0.8 if (k<s and "call" in opts) else 0.2)
            gamma = 0.02 if k==s else 0.01
            theta = -0.05
            vega = 0.10 if k==s else 0.05  # Mock vega
            
            # Mock volume - higher near ATM
            base_vol = int(500 * (1 - abs(k-s)/(s*0.15)))
            base_vol = max(20, base_vol)
            call_vol = int(base_vol * (1.1 if k > s else 0.9))
            put_vol = int(base_vol * (1.1 if k < s else 0.9))
            
            opts.append(OptionQuote("", float(k), "call", mid, iv, bid, ask, call_oi, call_vol, gamma, theta, delta, vega))
            opts.append(OptionQuote("", float(k), "put",  mid, iv, bid, ask, put_oi, put_vol, gamma, theta, delta-1.0, vega))
        return Chain(expiry, opts)
