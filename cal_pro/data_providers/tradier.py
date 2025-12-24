import os
import datetime as dt
import time
import logging
import requests
from typing import List, Dict, Any, Optional
from .base import DataProvider, Bar, Chain, OptionQuote

logger = logging.getLogger(__name__)

# Global cache for reducing API calls
_chain_cache: Dict[str, tuple] = {}  # key -> (timestamp, data)
_CACHE_TTL_SECONDS = 300  # 5 minutes


class TradierProvider:
    """Tradier API provider with retry logic and caching."""
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 1.0  # seconds
    
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.base = os.getenv("TRADIER_BASE", "https://api.tradier.com").rstrip("/")
        tok = os.getenv("TRADIER_TOKEN")
        if not tok: raise RuntimeError("TRADIER_TOKEN missing in .env")
        self.sess = requests.Session()
        self.sess.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/json"})

    def _get(self, path: str, params: dict, use_cache: bool = False) -> dict:
        """Make GET request with retry logic and optional caching."""
        cache_key = f"{path}:{self.ticker}:{str(sorted(params.items()))}"
        
        # Check cache
        if use_cache and cache_key in _chain_cache:
            timestamp, data = _chain_cache[cache_key]
            if time.time() - timestamp < _CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for {cache_key}")
                return data
        
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                r = self.sess.get(self.base + path, params=params, timeout=15)
                
                # Rate limit handling
                if r.status_code == 429:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                    time.sleep(wait_time)
                    continue
                
                if r.status_code != 200:
                    raise RuntimeError(f"Tradier GET {path} failed {r.status_code}: {r.text[:400]}")
                
                try:
                    data = r.json()
                except Exception as e:
                    raise RuntimeError(f"JSON parse error at {path}: {r.text[:400]}") from e
                
                # Cache successful response
                if use_cache:
                    _chain_cache[cache_key] = (time.time(), data)
                
                return data
                
            except requests.exceptions.Timeout:
                last_error = f"Timeout on attempt {attempt + 1}"
                logger.warning(f"Request timeout for {path}, attempt {attempt + 1}/{self.MAX_RETRIES}")
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error for {path}, attempt {attempt + 1}/{self.MAX_RETRIES}")
            except RuntimeError:
                raise  # Re-raise non-retryable errors
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Unexpected error for {path}: {e}, attempt {attempt + 1}/{self.MAX_RETRIES}")
            
            # Exponential backoff
            if attempt < self.MAX_RETRIES - 1:
                wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                time.sleep(wait_time)
        
        raise RuntimeError(f"Failed after {self.MAX_RETRIES} retries: {last_error}")

    def spot(self) -> float:
        js = self._get("/v1/markets/quotes", {"symbols": self.ticker})
        q = js["quotes"]["quote"]
        last = q[0]["last"] if isinstance(q, list) else q["last"]
        return float(last)

    def history(self, days: int=60) -> List[Bar]:
        start = (dt.date.today() - dt.timedelta(days=180)).isoformat()
        js = self._get("/v1/markets/history", {"symbol": self.ticker, "interval": "daily", "start": start})
        data = js.get("history", {}).get("day", [])
        out = []
        for d in data[-days:]:
            out.append(Bar(
                dt.date.fromisoformat(d["date"]), 
                float(d["close"]),
                float(d.get("high", d["close"])),
                float(d.get("low", d["close"]))
            ))
        return out

    def expirations(self) -> List[dt.date]:
        js = self._get("/v1/markets/options/expirations",
                       {"symbol": self.ticker, "includeAllRoots": "true", "strikes": "false"})
        dates = js.get("expirations", {}).get("date", [])
        if isinstance(dates, str): dates = [dates]
        out = []
        for d in dates:
            try: out.append(dt.date.fromisoformat(d))
            except: pass
        return out

    def chain(self, expiry: dt.date) -> Chain:
        """Fetch option chain with caching."""
        js = self._get("/v1/markets/options/chains",
                       {"symbol": self.ticker, "expiration": expiry.isoformat(), "greeks": "true"},
                       use_cache=True)
        opts = js.get("options", {}).get("option", [])
        out = []
        for o in opts or []:
            k = float(o["strike"])
            right = "call" if o.get("option_type","") == "call" else "put"
            g = o.get("greeks", {}) or {}
            iv = g.get("mid_iv") or g.get("iv") or g.get("implied_volatility") or 0.0
            bid = float(o.get("bid", 0) or 0)
            ask = float(o.get("ask", 0) or 0)
            if bid==0 and ask==0:
                mid = float(o.get("last", 0) or 0)
            else:
                mid = (bid+ask)/2 if (bid>0 and ask>0) else max(bid, ask)
            
            # Fields from Tradier
            oi = int(o.get("open_interest", 0) or 0)
            volume = int(o.get("volume", 0) or 0)  # Daily volume
            gamma = float(g.get("gamma", 0.0) or 0.0)
            theta = float(g.get("theta", 0.0) or 0.0)
            delta = float(g.get("delta", 0.0) or 0.0)
            vega = float(g.get("vega", 0.0) or 0.0)
            
            out.append(OptionQuote(
                symbol=o.get("symbol",""),
                strike=k,
                right=right,
                mid=float(mid),
                iv=float(iv),
                bid=bid,
                ask=ask,
                open_interest=oi,
                volume=volume,
                gamma=gamma,
                theta=theta,
                delta=delta,
                vega=vega
            ))
        return Chain(expiry, out)


def clear_cache():
    """Clear the provider cache. Useful for testing."""
    global _chain_cache
    _chain_cache = {}
