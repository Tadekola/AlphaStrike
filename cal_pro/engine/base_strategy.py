from dataclasses import dataclass, field
from typing import Protocol, List, Optional, Any, Dict
import datetime as dt
from .market import MarketState

# POP labels for transparency
POP_LABEL_VERIFIED = "VERIFIED"
POP_LABEL_UNVERIFIED = "UNVERIFIED"
POP_LABEL_DELTA_PROXY = "DELTA_PROXY (estimate only)"

# Tradability status labels
TRADABILITY_TRADABLE = "TRADABLE"
TRADABILITY_REJECTED = "REJECTED"

@dataclass
class Leg:
    symbol: str
    strike: float
    expiry: dt.date
    right: str # 'call' or 'put'
    action: str # 'buy' or 'sell'
    quantity: int = 1

@dataclass
class CandidateTrade:
    strategy_name: str
    ticker: str
    legs: List[Leg]
    debit: float
    max_loss: float
    max_profit: float
    breakevens: List[float]
    pop: Optional[float]  # None means not computed
    pop_label: str = POP_LABEL_UNVERIFIED  # VERIFIED, UNVERIFIED, or DELTA_PROXY
    
    # Analysis
    description: str = ""
    confidence_score: float = 0.0
    confidence_label: str = "Low"
    q_score: float = 0.0
    l_score: float = 0.0
    
    # Greeks / Metrics
    greeks: Dict[str, float] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Tradability (PR #2)
    is_tradable: bool = True
    tradability_status: str = TRADABILITY_TRADABLE
    rejection_reasons: List[str] = field(default_factory=list)
    slippage_cost: float = 0.0  # Total slippage in dollars

class Strategy(Protocol):
    @property
    def name(self) -> str: ...

    def is_eligible(self, market: MarketState) -> bool: ...
    
    def propose_trades(self, market: MarketState, chains: Dict[dt.date, Any]) -> List[CandidateTrade]: ...
