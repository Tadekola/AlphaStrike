"""
Public.com Data Provider

Provides real-time market data and trading capabilities via Public.com API.
Supports stocks, ETFs, options, and multi-leg strategies.

IMPORTANT: This provider can execute REAL trades. Use with caution.
"""
import os
import requests
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from .base import DataProvider, Bar, OptionQuote, Chain

# API Configuration
PUBLIC_API_BASE = "https://api.public.com"
AUTH_ENDPOINT = f"{PUBLIC_API_BASE}/userapiauthservice/personal/access-tokens"
TRADING_BASE = f"{PUBLIC_API_BASE}/userapigateway/trading"
MARKET_DATA_BASE = f"{PUBLIC_API_BASE}/userapigateway/marketdata"

# Token cache
_token_cache: Dict[str, Any] = {
    "access_token": None,
    "expires_at": None
}


@dataclass
class PublicAccount:
    """Public.com account information."""
    account_id: str
    account_type: str
    options_level: str
    brokerage_type: str
    trade_permissions: str


class PublicAuthError(Exception):
    """Raised when authentication fails."""


class PublicAPIError(Exception):
    """Raised when API call fails."""


class PublicProvider(DataProvider):
    """
    Data provider using Public.com API.
    
    Provides real-time quotes, option chains with Greeks, and trading capability.
    
    Environment variables required:
    - PUBLIC_API_SECRET: Your API secret key from Public.com settings
    - PUBLIC_ACCOUNT_ID: Your account ID (optional, will be fetched if not set)
    """
    
    def __init__(self, ticker: str, token_validity_minutes: int = 60):
        self.ticker = ticker.upper()
        self.token_validity = token_validity_minutes
        self._account_id: Optional[str] = os.getenv("PUBLIC_ACCOUNT_ID")
        self._secret = os.getenv("PUBLIC_API_SECRET")
        
        if not self._secret:
            raise PublicAuthError(
                "PUBLIC_API_SECRET not set. Get your secret key from "
                "https://public.com/settings/security/api"
            )
    
    def _get_access_token(self) -> str:
        """Get or refresh access token."""
        global _token_cache
        
        # Check if cached token is still valid
        if (_token_cache["access_token"] and 
            _token_cache["expires_at"] and 
            datetime.now() < _token_cache["expires_at"]):
            return _token_cache["access_token"]
        
        # Request new token
        response = requests.post(
            AUTH_ENDPOINT,
            json={
                "validityInMinutes": self.token_validity,
                "secret": self._secret
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code != 200:
            raise PublicAuthError(f"Authentication failed: {response.text}")
        
        data = response.json()
        _token_cache["access_token"] = data["accessToken"]
        _token_cache["expires_at"] = datetime.now() + timedelta(minutes=self.token_validity - 5)
        
        return _token_cache["access_token"]
    
    def _headers(self) -> Dict[str, str]:
        """Get request headers with authorization."""
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, url: str, **kwargs) -> Dict:
        """Make authenticated API request."""
        kwargs["headers"] = self._headers()
        kwargs["timeout"] = kwargs.get("timeout", 15)
        
        response = requests.request(method, url, **kwargs)
        
        if response.status_code == 401:
            # Token expired, clear cache and retry
            _token_cache["access_token"] = None
            kwargs["headers"] = self._headers()
            response = requests.request(method, url, **kwargs)
        
        if response.status_code not in (200, 201):
            raise PublicAPIError(f"API error {response.status_code}: {response.text}")
        
        return response.json()
    
    def get_account(self) -> PublicAccount:
        """Get account information."""
        data = self._request("GET", f"{TRADING_BASE}/account")
        
        if not data.get("accounts"):
            raise PublicAPIError("No accounts found")
        
        acc = data["accounts"][0]
        return PublicAccount(
            account_id=acc["accountId"],
            account_type=acc["accountType"],
            options_level=acc.get("optionsLevel", "NONE"),
            brokerage_type=acc.get("brokerageAccountType", "CASH"),
            trade_permissions=acc.get("tradePermissions", "NONE")
        )
    
    def spot(self) -> float:
        """Get real-time spot price."""
        data = self._request(
            "POST",
            f"{MARKET_DATA_BASE}/quotes",
            json={"symbols": [self.ticker]}
        )
        
        quotes = data.get("quotes", [])
        if not quotes:
            raise PublicAPIError(f"No quote found for {self.ticker}")
        
        quote = quotes[0]
        # Use last price, or mid of bid/ask
        last = quote.get("lastPrice") or quote.get("last")
        if last:
            return float(last)
        
        bid = float(quote.get("bid", 0))
        ask = float(quote.get("ask", 0))
        if bid and ask:
            return (bid + ask) / 2
        
        raise PublicAPIError(f"Could not determine price for {self.ticker}")
    
    def history(self, days: int = 60) -> List[Bar]:
        """Get historical OHLCV bars."""
        # Public.com may not have historical bars endpoint
        # Fall back to a basic implementation or use another source
        # For now, return empty - this will cause MarketState to use defaults
        # TODO: Implement when Public adds historical data endpoint
        return []
    
    def expirations(self) -> List[date]:
        """Get available option expiration dates."""
        data = self._request(
            "POST",
            f"{MARKET_DATA_BASE}/options/expirations",
            json={"symbol": self.ticker}
        )
        
        expirations = data.get("expirations", [])
        result = []
        for exp in expirations:
            if isinstance(exp, str):
                result.append(date.fromisoformat(exp))
            elif isinstance(exp, dict):
                exp_date = exp.get("expirationDate") or exp.get("date")
                if exp_date:
                    result.append(date.fromisoformat(exp_date[:10]))
        
        return sorted(result)
    
    def chain(self, expiry: date) -> Chain:
        """Get option chain with Greeks for a specific expiration."""
        data = self._request(
            "POST",
            f"{MARKET_DATA_BASE}/options/chain",
            json={
                "symbol": self.ticker,
                "expirationDate": expiry.isoformat()
            }
        )
        
        options = []
        chain_data = data.get("options", data.get("chain", []))
        
        for opt in chain_data:
            try:
                bid = float(opt.get("bid", 0))
                ask = float(opt.get("ask", 0))
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(opt.get("last", opt.get("lastPrice", 0)))
                
                options.append(OptionQuote(
                    symbol=opt.get("symbol", ""),
                    strike=float(opt.get("strikePrice", opt.get("strike", 0))),
                    right=opt.get("optionType", opt.get("type", "")).lower(),
                    mid=mid,
                    iv=float(opt.get("impliedVolatility", opt.get("iv", 0))),
                    bid=bid,
                    ask=ask,
                    open_interest=int(opt.get("openInterest", opt.get("oi", 0))),
                    volume=int(opt.get("volume", 0)),
                    delta=float(opt.get("delta", 0)),
                    gamma=float(opt.get("gamma", 0)),
                    theta=float(opt.get("theta", 0)),
                    vega=float(opt.get("vega", 0))
                ))
            except (KeyError, ValueError, TypeError):
                continue
        
        return Chain(
            expiry=expiry,
            options=options
        )


def is_public_configured() -> bool:
    """Check if Public.com API is configured."""
    return bool(os.getenv("PUBLIC_API_SECRET"))
