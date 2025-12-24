"""
PR #7: Paper Trading Journal & Calibration

This module provides trade journaling and outcome tracking for paper trading.
All metrics are based ONLY on user-logged data — no simulated outcomes.

Storage: SQLite for robustness and query capability.
"""
import sqlite3
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
from enum import Enum


class TradeStatus(Enum):
    """Trade lifecycle status."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class JournalLeg:
    """A single leg of a journaled trade."""
    strike: float
    expiry: str  # ISO date string
    right: str   # 'call' or 'put'
    action: str  # 'buy' or 'sell'
    quantity: int = 1
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "JournalLeg":
        return cls(**d)


@dataclass
class JournalEntry:
    """A complete journal entry for a paper trade.
    
    Contains all information needed for calibration and outcome tracking.
    """
    # Identity
    id: str
    timestamp: str  # ISO timestamp
    
    # Trade basics
    ticker: str
    strategy_name: str
    description: str
    legs: List[JournalLeg]
    
    # Entry pricing
    entry_price: float          # Conservative fill from engine (debit/credit)
    entry_timestamp: str        # When trade was journaled
    
    # Status
    status: str = TradeStatus.OPEN.value
    
    # Exit (populated when closed)
    exit_price: Optional[float] = None
    exit_timestamp: Optional[str] = None
    realized_pnl: Optional[float] = None
    
    # Context at entry
    tradability_status: str = ""
    tradability_reasons: List[str] = field(default_factory=list)
    regime_label: str = ""
    
    # Greeks at entry
    entry_delta: float = 0.0
    entry_gamma: float = 0.0
    entry_vega: float = 0.0
    entry_theta: float = 0.0
    
    # Stress summary at entry
    worst_case_scenario: str = ""
    worst_case_pnl: float = 0.0
    
    # Scoring
    confidence_score: float = 0.0
    confidence_label: str = ""
    pop: Optional[float] = None
    pop_label: str = ""
    
    # Max profit/loss at entry
    max_profit: float = 0.0
    max_loss: float = 0.0
    
    # User notes
    notes: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        d = asdict(self)
        d['legs'] = [leg.to_dict() if isinstance(leg, JournalLeg) else leg for leg in self.legs]
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> "JournalEntry":
        """Create from dictionary."""
        d = d.copy()
        d['legs'] = [JournalLeg.from_dict(leg) if isinstance(leg, dict) else leg for leg in d.get('legs', [])]
        return cls(**d)
    
    @property
    def is_open(self) -> bool:
        return self.status == TradeStatus.OPEN.value
    
    @property
    def is_closed(self) -> bool:
        return self.status == TradeStatus.CLOSED.value
    
    @property
    def is_winner(self) -> bool:
        """True if trade was closed with profit."""
        if self.realized_pnl is None:
            return False
        return self.realized_pnl > 0


# =============================================================================
# JOURNAL DATABASE
# =============================================================================

class JournalDB:
    """SQLite-based trade journal storage."""
    
    DEFAULT_PATH = Path("data/journal.db")
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    entry_price REAL,
                    exit_price REAL,
                    realized_pnl REAL,
                    confidence_score REAL,
                    regime_label TEXT,
                    data JSON NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON journal(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy ON journal(strategy_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ticker ON journal(ticker)
            """)
            conn.commit()
    
    def append(self, entry: JournalEntry) -> str:
        """Append a new journal entry. Returns the entry ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO journal (id, timestamp, ticker, strategy_name, status, 
                                    entry_price, exit_price, realized_pnl, 
                                    confidence_score, regime_label, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id,
                entry.timestamp,
                entry.ticker,
                entry.strategy_name,
                entry.status,
                entry.entry_price,
                entry.exit_price,
                entry.realized_pnl,
                entry.confidence_score,
                entry.regime_label,
                json.dumps(entry.to_dict())
            ))
            conn.commit()
        return entry.id
    
    def get(self, entry_id: str) -> Optional[JournalEntry]:
        """Load a single entry by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT data FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
            if row:
                return JournalEntry.from_dict(json.loads(row['data']))
        return None
    
    def list_entries(
        self,
        status: Optional[str] = None,
        strategy: Optional[str] = None,
        ticker: Optional[str] = None,
        regime: Optional[str] = None,
        limit: int = 100
    ) -> List[JournalEntry]:
        """List journal entries with optional filters."""
        query = "SELECT data FROM journal WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        if strategy:
            query += " AND strategy_name = ?"
            params.append(strategy)
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if regime:
            query += " AND regime_label = ?"
            params.append(regime)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [JournalEntry.from_dict(json.loads(row[0])) for row in rows]
    
    def update(self, entry: JournalEntry) -> bool:
        """Update an existing entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE journal 
                SET status = ?, exit_price = ?, realized_pnl = ?, data = ?
                WHERE id = ?
            """, (
                entry.status,
                entry.exit_price,
                entry.realized_pnl,
                json.dumps(entry.to_dict()),
                entry.id
            ))
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def count(self, status: Optional[str] = None) -> int:
        """Count entries, optionally filtered by status."""
        query = "SELECT COUNT(*) FROM journal"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(query, params).fetchone()[0]
    
    def get_strategies(self) -> List[str]:
        """Get list of unique strategies in journal."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT strategy_name FROM journal ORDER BY strategy_name"
            ).fetchall()
            return [row[0] for row in rows]
    
    def get_regimes(self) -> List[str]:
        """Get list of unique regimes in journal."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT regime_label FROM journal WHERE regime_label != '' ORDER BY regime_label"
            ).fetchall()
            return [row[0] for row in rows]


# =============================================================================
# TRADE LIFECYCLE
# =============================================================================

class TradeJournal:
    """High-level interface for trade journaling and outcome tracking."""
    
    def __init__(self, db: Optional[JournalDB] = None):
        self.db = db or JournalDB()
    
    def save_trade(self, trade: "CandidateTrade", regime_label: str = "", 
                   stress_summary: Optional[Dict] = None, notes: str = "") -> str:
        """Save a CandidateTrade to the journal.
        
        Args:
            trade: The CandidateTrade to save
            regime_label: Current market regime
            stress_summary: Optional stress test results
            notes: User notes
            
        Returns:
            Journal entry ID
        """
        now = datetime.utcnow().isoformat()
        entry_id = str(uuid.uuid4())[:8]
        
        # Convert legs
        legs = [
            JournalLeg(
                strike=leg.strike,
                expiry=leg.expiry.isoformat() if hasattr(leg.expiry, 'isoformat') else str(leg.expiry),
                right=leg.right,
                action=leg.action,
                quantity=leg.quantity
            )
            for leg in trade.legs
        ]
        
        # Extract stress summary
        worst_scenario = ""
        worst_pnl = 0.0
        if stress_summary:
            worst_scenario = stress_summary.get('worst_case_scenario', '')
            worst_pnl = stress_summary.get('worst_case_pnl', 0.0)
        
        # Extract Greeks
        greeks = trade.greeks or {}
        
        entry = JournalEntry(
            id=entry_id,
            timestamp=now,
            ticker=trade.ticker,
            strategy_name=trade.strategy_name,
            description=trade.description,
            legs=legs,
            entry_price=trade.debit,
            entry_timestamp=now,
            status=TradeStatus.OPEN.value,
            tradability_status=trade.tradability_status,
            tradability_reasons=trade.rejection_reasons,
            regime_label=regime_label,
            entry_delta=greeks.get('delta', 0.0),
            entry_gamma=greeks.get('gamma', 0.0),
            entry_vega=greeks.get('vega', 0.0),
            entry_theta=greeks.get('theta', 0.0),
            worst_case_scenario=worst_scenario,
            worst_case_pnl=worst_pnl,
            confidence_score=trade.confidence_score,
            confidence_label=trade.confidence_label,
            pop=trade.pop,
            pop_label=trade.pop_label,
            max_profit=trade.max_profit,
            max_loss=trade.max_loss if trade.max_loss != float('inf') else 0.0,
            notes=notes
        )
        
        return self.db.append(entry)
    
    def close_trade(self, entry_id: str, exit_price: float, notes: str = "") -> Optional[JournalEntry]:
        """Close a trade with exit price.
        
        Calculates realized P&L as: exit_price - entry_price
        (Positive = profit for credit trades, negative = loss)
        
        For option spreads:
        - Entry debit (negative) + Exit credit (positive) = P&L
        - Entry credit (positive) + Exit debit (negative) = P&L
        
        Args:
            entry_id: Journal entry ID
            exit_price: Closing credit/debit (positive = credit received)
            notes: Optional closing notes
            
        Returns:
            Updated JournalEntry or None if not found
        """
        entry = self.db.get(entry_id)
        if entry is None:
            return None
        
        if entry.is_closed:
            return entry  # Already closed
        
        # Calculate realized P&L
        # entry_price is debit (negative = paid, positive = received credit)
        # exit_price is credit (positive = received, negative = paid)
        # P&L = exit_price - entry_price (simplified for spreads)
        realized_pnl = exit_price - entry.entry_price
        
        entry.status = TradeStatus.CLOSED.value
        entry.exit_price = exit_price
        entry.exit_timestamp = datetime.utcnow().isoformat()
        entry.realized_pnl = round(realized_pnl, 2)
        
        if notes:
            entry.notes = f"{entry.notes}\n[CLOSE] {notes}" if entry.notes else f"[CLOSE] {notes}"
        
        self.db.update(entry)
        return entry
    
    def get_open_trades(self) -> List[JournalEntry]:
        """Get all open trades."""
        return self.db.list_entries(status=TradeStatus.OPEN.value)
    
    def get_closed_trades(self) -> List[JournalEntry]:
        """Get all closed trades."""
        return self.db.list_entries(status=TradeStatus.CLOSED.value)


# =============================================================================
# CALIBRATION METRICS
# =============================================================================

@dataclass
class CalibrationMetrics:
    """Calibration metrics computed from journaled trades.
    
    All metrics are based ONLY on closed, user-logged trades.
    No simulated or inferred outcomes.
    """
    # Summary counts
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    
    # Win/Loss
    winners: int = 0
    losers: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    
    # P&L
    total_pnl: float = 0.0
    average_pnl: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # By strategy
    by_strategy: Dict[str, Dict] = field(default_factory=dict)
    
    # Score calibration (confidence vs outcome)
    score_vs_outcome: Dict[str, Dict] = field(default_factory=dict)
    
    # Stress calibration
    avg_worst_stress_at_entry: float = 0.0
    avg_realized_loss: float = 0.0


class CalibrationEngine:
    """Compute calibration metrics from journal data.
    
    All metrics are truthful — based only on logged outcomes.
    """
    
    def __init__(self, journal: TradeJournal):
        self.journal = journal
    
    def compute_metrics(self) -> CalibrationMetrics:
        """Compute all calibration metrics."""
        metrics = CalibrationMetrics()
        
        all_entries = self.journal.db.list_entries(limit=10000)
        closed_entries = [e for e in all_entries if e.is_closed]
        
        metrics.total_trades = len(all_entries)
        metrics.open_trades = len([e for e in all_entries if e.is_open])
        metrics.closed_trades = len(closed_entries)
        
        if not closed_entries:
            return metrics
        
        # Win/Loss analysis
        winners = [e for e in closed_entries if e.realized_pnl and e.realized_pnl > 0]
        losers = [e for e in closed_entries if e.realized_pnl and e.realized_pnl < 0]
        breakeven = [e for e in closed_entries if e.realized_pnl == 0]
        
        metrics.winners = len(winners)
        metrics.losers = len(losers)
        metrics.breakeven = len(breakeven)
        metrics.win_rate = len(winners) / len(closed_entries) if closed_entries else 0.0
        
        # P&L analysis
        pnls = [e.realized_pnl for e in closed_entries if e.realized_pnl is not None]
        if pnls:
            metrics.total_pnl = sum(pnls)
            metrics.average_pnl = metrics.total_pnl / len(pnls)
            
            win_pnls = [p for p in pnls if p > 0]
            loss_pnls = [p for p in pnls if p < 0]
            
            metrics.average_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
            metrics.average_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
            metrics.largest_win = max(pnls) if pnls else 0.0
            metrics.largest_loss = min(pnls) if pnls else 0.0
        
        # By strategy
        metrics.by_strategy = self._compute_by_strategy(closed_entries)
        
        # Score calibration
        metrics.score_vs_outcome = self._compute_score_calibration(closed_entries)
        
        # Stress calibration
        stress_entries = [e for e in closed_entries if e.worst_case_pnl != 0]
        if stress_entries:
            metrics.avg_worst_stress_at_entry = sum(e.worst_case_pnl for e in stress_entries) / len(stress_entries)
            loss_entries = [e for e in stress_entries if e.realized_pnl and e.realized_pnl < 0]
            if loss_entries:
                metrics.avg_realized_loss = sum(e.realized_pnl for e in loss_entries) / len(loss_entries)
        
        return metrics
    
    def _compute_by_strategy(self, entries: List[JournalEntry]) -> Dict[str, Dict]:
        """Compute metrics grouped by strategy."""
        by_strategy = {}
        
        strategies = set(e.strategy_name for e in entries)
        for strategy in strategies:
            strat_entries = [e for e in entries if e.strategy_name == strategy]
            pnls = [e.realized_pnl for e in strat_entries if e.realized_pnl is not None]
            winners = [p for p in pnls if p > 0]
            
            by_strategy[strategy] = {
                'count': len(strat_entries),
                'winners': len(winners),
                'win_rate': len(winners) / len(pnls) if pnls else 0.0,
                'total_pnl': sum(pnls) if pnls else 0.0,
                'average_pnl': sum(pnls) / len(pnls) if pnls else 0.0
            }
        
        return by_strategy
    
    def _compute_score_calibration(self, entries: List[JournalEntry]) -> Dict[str, Dict]:
        """Compute score vs outcome calibration.
        
        Bins confidence scores and computes win rate per bin.
        """
        bins = {
            'Low (0-40)': {'entries': [], 'range': (0, 40)},
            'Medium (40-70)': {'entries': [], 'range': (40, 70)},
            'High (70-100)': {'entries': [], 'range': (70, 100)}
        }
        
        for entry in entries:
            score = entry.confidence_score
            for bin_name, bin_data in bins.items():
                low, high = bin_data['range']
                if low <= score < high or (high == 100 and score == 100):
                    bin_data['entries'].append(entry)
                    break
        
        result = {}
        for bin_name, bin_data in bins.items():
            entries_in_bin = bin_data['entries']
            if entries_in_bin:
                winners = [e for e in entries_in_bin if e.realized_pnl and e.realized_pnl > 0]
                pnls = [e.realized_pnl for e in entries_in_bin if e.realized_pnl is not None]
                result[bin_name] = {
                    'count': len(entries_in_bin),
                    'win_rate': len(winners) / len(entries_in_bin),
                    'avg_pnl': sum(pnls) / len(pnls) if pnls else 0.0
                }
            else:
                result[bin_name] = {'count': 0, 'win_rate': 0.0, 'avg_pnl': 0.0}
        
        return result
    
    def get_strategy_report(self) -> str:
        """Generate a text report of strategy performance."""
        metrics = self.compute_metrics()
        
        lines = [
            "=" * 50,
            "PAPER TRADING CALIBRATION REPORT",
            "=" * 50,
            f"Total Trades: {metrics.total_trades}",
            f"  Open: {metrics.open_trades}",
            f"  Closed: {metrics.closed_trades}",
            "",
            "CLOSED TRADE SUMMARY",
            "-" * 30,
            f"Win Rate: {metrics.win_rate:.1%}",
            f"Total P&L: ${metrics.total_pnl:,.2f}",
            f"Average P&L: ${metrics.average_pnl:,.2f}",
            f"Average Win: ${metrics.average_win:,.2f}",
            f"Average Loss: ${metrics.average_loss:,.2f}",
            f"Largest Win: ${metrics.largest_win:,.2f}",
            f"Largest Loss: ${metrics.largest_loss:,.2f}",
            "",
            "BY STRATEGY",
            "-" * 30,
        ]
        
        for strategy, data in metrics.by_strategy.items():
            lines.append(f"{strategy}:")
            lines.append(f"  Trades: {data['count']}, Win Rate: {data['win_rate']:.1%}, Avg P&L: ${data['average_pnl']:,.2f}")
        
        lines.extend([
            "",
            "SCORE CALIBRATION",
            "-" * 30,
        ])
        
        for bin_name, data in metrics.score_vs_outcome.items():
            lines.append(f"{bin_name}: {data['count']} trades, {data['win_rate']:.1%} win rate, ${data['avg_pnl']:,.2f} avg P&L")
        
        lines.extend([
            "",
            "⚠️ All metrics based on user-logged outcomes only.",
            "=" * 50
        ])
        
        return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_journal_entry_from_trade(
    trade: "CandidateTrade",
    regime_label: str = "",
    stress_worst: str = "",
    stress_pnl: float = 0.0,
    notes: str = ""
) -> JournalEntry:
    """Create a JournalEntry from a CandidateTrade without saving."""
    now = datetime.utcnow().isoformat()
    entry_id = str(uuid.uuid4())[:8]
    
    legs = [
        JournalLeg(
            strike=leg.strike,
            expiry=leg.expiry.isoformat() if hasattr(leg.expiry, 'isoformat') else str(leg.expiry),
            right=leg.right,
            action=leg.action,
            quantity=leg.quantity
        )
        for leg in trade.legs
    ]
    
    greeks = trade.greeks or {}
    
    return JournalEntry(
        id=entry_id,
        timestamp=now,
        ticker=trade.ticker,
        strategy_name=trade.strategy_name,
        description=trade.description,
        legs=legs,
        entry_price=trade.debit,
        entry_timestamp=now,
        status=TradeStatus.OPEN.value,
        tradability_status=trade.tradability_status,
        tradability_reasons=trade.rejection_reasons,
        regime_label=regime_label,
        entry_delta=greeks.get('delta', 0.0),
        entry_gamma=greeks.get('gamma', 0.0),
        entry_vega=greeks.get('vega', 0.0),
        entry_theta=greeks.get('theta', 0.0),
        worst_case_scenario=stress_worst,
        worst_case_pnl=stress_pnl,
        confidence_score=trade.confidence_score,
        confidence_label=trade.confidence_label,
        pop=trade.pop,
        pop_label=trade.pop_label,
        max_profit=trade.max_profit,
        max_loss=trade.max_loss if trade.max_loss != float('inf') else 0.0,
        notes=notes
    )
