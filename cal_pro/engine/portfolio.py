"""
PR #5: Portfolio Greeks & Exposure Guardrails

This module provides portfolio-level Greeks tracking and exposure management.
It enables AlphaStrike to evaluate trades in portfolio context, not isolation.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import math


class GreeksSource(Enum):
    """Source of Greeks data."""
    BROKER = "BROKER"           # Provider-supplied Greeks (preferred)
    BLACK_SCHOLES = "BS_CALC"   # Black-Scholes calculation (fallback)
    UNKNOWN = "UNKNOWN"


class ExposureStatus(Enum):
    """Exposure check status."""
    SAFE = "SAFE"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass
class LegGreeks:
    """Greeks for a single option leg.
    
    All Greeks are per-share (multiply by 100 for per-contract).
    Sign convention:
    - Long positions: use raw Greeks
    - Short positions: negate Greeks
    """
    delta: float = 0.0      # Position delta (directional exposure)
    gamma: float = 0.0      # Position gamma (delta sensitivity)
    vega: float = 0.0       # Position vega (vol sensitivity)
    theta: float = 0.0      # Position theta (time decay)
    
    # Metadata
    source: GreeksSource = GreeksSource.UNKNOWN
    
    def scale(self, multiplier: float) -> "LegGreeks":
        """Scale Greeks by a multiplier (e.g., for quantity)."""
        return LegGreeks(
            delta=self.delta * multiplier,
            gamma=self.gamma * multiplier,
            vega=self.vega * multiplier,
            theta=self.theta * multiplier,
            source=self.source
        )
    
    def __add__(self, other: "LegGreeks") -> "LegGreeks":
        """Add two LegGreeks together."""
        return LegGreeks(
            delta=self.delta + other.delta,
            gamma=self.gamma + other.gamma,
            vega=self.vega + other.vega,
            theta=self.theta + other.theta,
            source=GreeksSource.UNKNOWN  # Mixed sources
        )


@dataclass
class PositionGreeks:
    """Aggregate Greeks for a position (trade with multiple legs)."""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_vega: float = 0.0
    net_theta: float = 0.0
    
    # Position info
    ticker: str = ""
    strategy_name: str = ""
    num_contracts: int = 0
    
    # Data quality
    source: GreeksSource = GreeksSource.UNKNOWN
    has_missing_data: bool = False
    
    def __add__(self, other: "PositionGreeks") -> "PositionGreeks":
        """Add two PositionGreeks together."""
        return PositionGreeks(
            net_delta=self.net_delta + other.net_delta,
            net_gamma=self.net_gamma + other.net_gamma,
            net_vega=self.net_vega + other.net_vega,
            net_theta=self.net_theta + other.net_theta
        )


@dataclass
class PortfolioGreeks:
    """Aggregate Greeks for entire portfolio."""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_vega: float = 0.0
    net_theta: float = 0.0
    
    # Position count
    num_positions: int = 0
    positions: List[PositionGreeks] = field(default_factory=list)
    
    # Risk metrics
    delta_dollars: float = 0.0  # Delta × spot × 100
    gamma_dollars: float = 0.0  # Gamma × spot² × 100 / 100
    vega_dollars: float = 0.0   # Vega × 100 (per 1% IV move)
    
    @classmethod
    def from_positions(cls, positions: List[PositionGreeks], spot: float = 0.0) -> "PortfolioGreeks":
        """Aggregate Greeks from list of positions."""
        if not positions:
            return cls()
        
        net_delta = sum(p.net_delta for p in positions)
        net_gamma = sum(p.net_gamma for p in positions)
        net_vega = sum(p.net_vega for p in positions)
        net_theta = sum(p.net_theta for p in positions)
        
        # Dollar exposure calculations
        delta_dollars = net_delta * spot * 100 if spot > 0 else 0.0
        gamma_dollars = net_gamma * (spot ** 2) / 100 if spot > 0 else 0.0
        vega_dollars = net_vega * 100  # Per 1 point IV change
        
        return cls(
            net_delta=net_delta,
            net_gamma=net_gamma,
            net_vega=net_vega,
            net_theta=net_theta,
            num_positions=len(positions),
            positions=positions,
            delta_dollars=delta_dollars,
            gamma_dollars=gamma_dollars,
            vega_dollars=vega_dollars
        )


# =============================================================================
# EXPOSURE THRESHOLDS
# =============================================================================

@dataclass
class ExposureThresholds:
    """Configurable exposure thresholds for risk management.
    
    All thresholds are absolute values (magnitude).
    Default values are conservative for a small retail account.
    """
    # Delta thresholds (equivalent shares)
    max_net_delta: float = 50.0          # Max ±50 delta (500 share equivalent)
    warn_net_delta: float = 30.0         # Warn at ±30 delta
    
    # Gamma thresholds (delta change per $1 move)
    max_short_gamma: float = 5.0         # Max short gamma (very dangerous)
    warn_short_gamma: float = 2.0        # Warn at short gamma
    
    # Vega thresholds ($ P/L per 1% IV change)  
    max_net_vega: float = 500.0          # Max ±$500 vega exposure
    warn_net_vega: float = 300.0         # Warn at ±$300
    
    # Concentration thresholds
    max_same_direction_positions: int = 3  # Max positions with same delta sign
    max_same_vega_positions: int = 3       # Max positions with same vega sign
    
    # Behavior
    block_on_exceed: bool = False        # If True, block trades that exceed max


@dataclass
class ExposureCheck:
    """Result of checking portfolio exposure."""
    status: ExposureStatus = ExposureStatus.SAFE
    
    # Individual checks
    delta_status: ExposureStatus = ExposureStatus.SAFE
    gamma_status: ExposureStatus = ExposureStatus.SAFE
    vega_status: ExposureStatus = ExposureStatus.SAFE
    concentration_status: ExposureStatus = ExposureStatus.SAFE
    
    # Warnings/blocks
    warnings: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    
    # Values that triggered
    current_delta: float = 0.0
    current_gamma: float = 0.0
    current_vega: float = 0.0
    
    @property
    def is_blocked(self) -> bool:
        return self.status == ExposureStatus.BLOCKED
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# =============================================================================
# CONCENTRATION DETECTION
# =============================================================================

@dataclass
class ConcentrationAnalysis:
    """Analysis of portfolio concentration risks."""
    
    # Directional concentration
    long_delta_count: int = 0       # Positions with positive delta
    short_delta_count: int = 0      # Positions with negative delta
    directional_bias: str = "NEUTRAL"  # LONG_BIASED, SHORT_BIASED, NEUTRAL
    
    # Volatility concentration
    long_vega_count: int = 0        # Positions that benefit from vol increase
    short_vega_count: int = 0       # Positions that benefit from vol decrease
    vol_bias: str = "NEUTRAL"       # LONG_VOL, SHORT_VOL, NEUTRAL
    
    # Gamma concentration
    long_gamma_count: int = 0       # Long gamma (convexity)
    short_gamma_count: int = 0      # Short gamma (concavity - DANGEROUS)
    gamma_bias: str = "NEUTRAL"
    
    # Warnings
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# PORTFOLIO MANAGER
# =============================================================================

class PortfolioManager:
    """Manages portfolio positions and Greeks calculations."""
    
    def __init__(self, thresholds: Optional[ExposureThresholds] = None):
        self.thresholds = thresholds or ExposureThresholds()
        self.positions: List[PositionGreeks] = []
        self._spot_cache: Dict[str, float] = {}
    
    def add_position(self, position: PositionGreeks) -> None:
        """Add a position to the portfolio."""
        self.positions.append(position)
    
    def clear_positions(self) -> None:
        """Clear all positions."""
        self.positions = []
    
    def get_portfolio_greeks(self, spot: float = 0.0) -> PortfolioGreeks:
        """Calculate aggregate portfolio Greeks."""
        return PortfolioGreeks.from_positions(self.positions, spot)
    
    def calculate_trade_greeks(self, trade: "CandidateTrade") -> PositionGreeks:
        """Calculate Greeks for a CandidateTrade.
        
        Uses provider-supplied Greeks where available,
        marks as BS_CALC fallback where not.
        """
        net_delta = 0.0
        net_gamma = 0.0
        net_vega = 0.0
        net_theta = 0.0
        has_missing = False
        source = GreeksSource.BROKER
        
        # Get Greeks from trade's greeks dict if available
        trade_greeks = trade.greeks
        
        if trade_greeks:
            net_delta = trade_greeks.get('delta', 0.0)
            net_gamma = trade_greeks.get('gamma', 0.0)
            net_vega = trade_greeks.get('vega', 0.0)
            net_theta = trade_greeks.get('theta', 0.0)
            
            # Check if any are missing/zero
            if net_delta == 0 and net_gamma == 0 and net_vega == 0:
                has_missing = True
                source = GreeksSource.UNKNOWN
        else:
            has_missing = True
            source = GreeksSource.UNKNOWN
        
        return PositionGreeks(
            net_delta=net_delta,
            net_gamma=net_gamma,
            net_vega=net_vega,
            net_theta=net_theta,
            ticker=trade.ticker,
            strategy_name=trade.strategy_name,
            num_contracts=len(trade.legs),
            source=source,
            has_missing_data=has_missing
        )
    
    def check_exposure(self, portfolio_greeks: Optional[PortfolioGreeks] = None) -> ExposureCheck:
        """Check portfolio exposure against thresholds."""
        if portfolio_greeks is None:
            portfolio_greeks = self.get_portfolio_greeks()
        
        result = ExposureCheck(
            current_delta=portfolio_greeks.net_delta,
            current_gamma=portfolio_greeks.net_gamma,
            current_vega=portfolio_greeks.net_vega
        )
        
        # Check delta
        delta_mag = abs(portfolio_greeks.net_delta)
        if delta_mag > self.thresholds.max_net_delta:
            result.delta_status = ExposureStatus.BLOCKED if self.thresholds.block_on_exceed else ExposureStatus.WARNING
            msg = f"Net delta ({portfolio_greeks.net_delta:.1f}) exceeds max ({self.thresholds.max_net_delta}). High directional risk."
            if self.thresholds.block_on_exceed:
                result.blocks.append(msg)
            else:
                result.warnings.append(msg)
        elif delta_mag > self.thresholds.warn_net_delta:
            result.delta_status = ExposureStatus.WARNING
            result.warnings.append(
                f"Net delta ({portfolio_greeks.net_delta:.1f}) approaching limit ({self.thresholds.max_net_delta}). Monitor directional exposure."
            )
        
        # Check gamma (short gamma is particularly dangerous)
        if portfolio_greeks.net_gamma < -self.thresholds.max_short_gamma:
            result.gamma_status = ExposureStatus.BLOCKED if self.thresholds.block_on_exceed else ExposureStatus.WARNING
            msg = f"Short gamma ({portfolio_greeks.net_gamma:.2f}) exceeds safe limit. Position will lose on large moves."
            if self.thresholds.block_on_exceed:
                result.blocks.append(msg)
            else:
                result.warnings.append(msg)
        elif portfolio_greeks.net_gamma < -self.thresholds.warn_short_gamma:
            result.gamma_status = ExposureStatus.WARNING
            result.warnings.append(
                f"Elevated short gamma ({portfolio_greeks.net_gamma:.2f}). Vulnerable to sudden moves."
            )
        
        # Check vega
        vega_mag = abs(portfolio_greeks.net_vega)
        if vega_mag > self.thresholds.max_net_vega:
            result.vega_status = ExposureStatus.BLOCKED if self.thresholds.block_on_exceed else ExposureStatus.WARNING
            direction = "long" if portfolio_greeks.net_vega > 0 else "short"
            msg = f"Net vega ({portfolio_greeks.net_vega:.1f}) exceeds max. Heavy {direction} volatility exposure."
            if self.thresholds.block_on_exceed:
                result.blocks.append(msg)
            else:
                result.warnings.append(msg)
        elif vega_mag > self.thresholds.warn_net_vega:
            result.vega_status = ExposureStatus.WARNING
            direction = "long" if portfolio_greeks.net_vega > 0 else "short"
            result.warnings.append(
                f"Elevated {direction} vega ({portfolio_greeks.net_vega:.1f}). Sensitive to IV changes."
            )
        
        # Determine overall status
        statuses = [result.delta_status, result.gamma_status, result.vega_status]
        if ExposureStatus.BLOCKED in statuses:
            result.status = ExposureStatus.BLOCKED
        elif ExposureStatus.WARNING in statuses:
            result.status = ExposureStatus.WARNING
        
        return result
    
    def check_exposure_with_trade(
        self, 
        trade_greeks: PositionGreeks,
        spot: float = 0.0
    ) -> Tuple[ExposureCheck, PortfolioGreeks, PortfolioGreeks]:
        """Check exposure before and after adding a trade.
        
        Returns:
            (exposure_check, before_greeks, after_greeks)
        """
        before = self.get_portfolio_greeks(spot)
        
        # Simulate adding the trade
        after_positions = self.positions + [trade_greeks]
        after = PortfolioGreeks.from_positions(after_positions, spot)
        
        # Check exposure on the "after" state
        check = self.check_exposure(after)
        
        return check, before, after
    
    def analyze_concentration(self) -> ConcentrationAnalysis:
        """Analyze portfolio concentration risks."""
        analysis = ConcentrationAnalysis()
        
        for pos in self.positions:
            # Delta concentration
            if pos.net_delta > 0.1:
                analysis.long_delta_count += 1
            elif pos.net_delta < -0.1:
                analysis.short_delta_count += 1
            
            # Vega concentration
            if pos.net_vega > 0.1:
                analysis.long_vega_count += 1
            elif pos.net_vega < -0.1:
                analysis.short_vega_count += 1
            
            # Gamma concentration
            if pos.net_gamma > 0.01:
                analysis.long_gamma_count += 1
            elif pos.net_gamma < -0.01:
                analysis.short_gamma_count += 1
        
        # Determine biases
        if analysis.long_delta_count > analysis.short_delta_count + 1:
            analysis.directional_bias = "LONG_BIASED"
        elif analysis.short_delta_count > analysis.long_delta_count + 1:
            analysis.directional_bias = "SHORT_BIASED"
        
        if analysis.long_vega_count > analysis.short_vega_count + 1:
            analysis.vol_bias = "LONG_VOL"
        elif analysis.short_vega_count > analysis.long_vega_count + 1:
            analysis.vol_bias = "SHORT_VOL"
        
        if analysis.short_gamma_count > analysis.long_gamma_count + 1:
            analysis.gamma_bias = "SHORT_GAMMA"
        elif analysis.long_gamma_count > analysis.short_gamma_count + 1:
            analysis.gamma_bias = "LONG_GAMMA"
        
        # Generate warnings
        if analysis.long_delta_count >= self.thresholds.max_same_direction_positions:
            analysis.warnings.append(
                f"Directional stacking: {analysis.long_delta_count} long delta positions. Consider hedging."
            )
        if analysis.short_delta_count >= self.thresholds.max_same_direction_positions:
            analysis.warnings.append(
                f"Directional stacking: {analysis.short_delta_count} short delta positions. Consider hedging."
            )
        
        if analysis.short_vega_count >= self.thresholds.max_same_vega_positions:
            analysis.warnings.append(
                f"Volatility stacking: {analysis.short_vega_count} short vega positions. Vulnerable to vol spike."
            )
        
        if analysis.short_gamma_count >= 2:
            analysis.warnings.append(
                f"Short gamma concentration: {analysis.short_gamma_count} positions. High risk on large moves."
            )
        
        return analysis


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_position_greeks_from_trade(trade: "CandidateTrade") -> PositionGreeks:
    """Calculate position Greeks from a CandidateTrade."""
    manager = PortfolioManager()
    return manager.calculate_trade_greeks(trade)


def format_greeks_summary(greeks: PortfolioGreeks) -> str:
    """Format Greeks for display."""
    return (
        f"Δ={greeks.net_delta:+.2f} | "
        f"Γ={greeks.net_gamma:+.3f} | "
        f"V={greeks.net_vega:+.1f} | "
        f"Θ={greeks.net_theta:+.2f}"
    )


def format_exposure_change(before: PortfolioGreeks, after: PortfolioGreeks) -> Dict[str, str]:
    """Format before/after exposure change."""
    return {
        'delta': f"{before.net_delta:+.2f} → {after.net_delta:+.2f}",
        'gamma': f"{before.net_gamma:+.3f} → {after.net_gamma:+.3f}",
        'vega': f"{before.net_vega:+.1f} → {after.net_vega:+.1f}",
        'theta': f"{before.net_theta:+.2f} → {after.net_theta:+.2f}",
    }
