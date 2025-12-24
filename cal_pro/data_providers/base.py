from dataclasses import dataclass
import datetime as dt
from typing import Protocol, List, Optional

@dataclass
class Bar:
    date: dt.date
    close: float
    high: float = 0.0
    low: float = 0.0

@dataclass
class OptionQuote:
    symbol: str
    strike: float
    right: str    # 'call' or 'put'
    mid: float
    iv: float
    bid: float = 0.0
    ask: float = 0.0
    open_interest: int = 0
    volume: int = 0  # Daily option volume
    gamma: float = 0.0
    theta: float = 0.0
    delta: float = 0.0
    vega: float = 0.0
    
    @property
    def spread(self) -> float:
        """Bid-ask spread in dollars."""
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return float('inf')
    
    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as percentage of midpoint."""
        if self.mid > 0 and self.bid > 0 and self.ask > 0:
            return (self.ask - self.bid) / self.mid
        return float('inf')
    
    @property
    def is_quoted(self) -> bool:
        """True if option has valid bid and ask."""
        return self.bid > 0 and self.ask > 0

@dataclass
class Chain:
    expiry: dt.date
    options: List[OptionQuote]

class DataProvider(Protocol):
    def spot(self) -> float: ...
    def history(self, days: int=60) -> List[Bar]: ...
    def expirations(self) -> List[dt.date]: ...
    def chain(self, expiry: dt.date) -> Chain: ...
