"""
PR #6: Portfolio Scenario Stress Testing

This module implements scenario-based stress testing using portfolio Greeks.
Uses second-order Taylor approximation for P&L estimation.

APPROXIMATION ASSUMPTIONS:
- Greeks are assumed constant across the shock (instantaneous move)
- For large moves (>5%), the approximation becomes less reliable
- Cross-gamma effects between positions are not modeled
- Theta decay during the shock period is not included
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum


class ScenarioType(Enum):
    """Type of market scenario."""
    PRICE_SHOCK = "PRICE_SHOCK"
    VOL_SHOCK = "VOL_SHOCK"
    COMBINED = "COMBINED"


@dataclass
class Scenario:
    """A market scenario for stress testing.
    
    Attributes:
        name: Human-readable scenario name
        price_change_pct: Price change as decimal (e.g., -0.02 for -2%)
        vol_change_points: IV change in percentage points (e.g., 10 for +10 IV points)
        scenario_type: Type of scenario
        description: Explanation of the scenario
    """
    name: str
    price_change_pct: float = 0.0      # e.g., -0.05 for -5%
    vol_change_points: float = 0.0     # e.g., 10 for +10 IV points
    scenario_type: ScenarioType = ScenarioType.PRICE_SHOCK
    description: str = ""
    
    @property
    def is_adverse(self) -> bool:
        """True if scenario represents adverse conditions."""
        return self.price_change_pct < -0.02 or self.vol_change_points > 5


# =============================================================================
# PREDEFINED SCENARIOS
# =============================================================================

# Price shock scenarios
SCENARIO_PRICE_UP_1 = Scenario(
    name="Price +1%",
    price_change_pct=0.01,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Mild bullish move"
)

SCENARIO_PRICE_UP_2 = Scenario(
    name="Price +2%",
    price_change_pct=0.02,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Moderate bullish move"
)

SCENARIO_PRICE_UP_5 = Scenario(
    name="Price +5%",
    price_change_pct=0.05,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Strong bullish move (approximation less reliable)"
)

SCENARIO_PRICE_DOWN_1 = Scenario(
    name="Price -1%",
    price_change_pct=-0.01,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Mild bearish move"
)

SCENARIO_PRICE_DOWN_2 = Scenario(
    name="Price -2%",
    price_change_pct=-0.02,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Moderate bearish move"
)

SCENARIO_PRICE_DOWN_5 = Scenario(
    name="Price -5%",
    price_change_pct=-0.05,
    scenario_type=ScenarioType.PRICE_SHOCK,
    description="Strong bearish move (approximation less reliable)"
)

# Volatility shock scenarios
SCENARIO_VOL_UP_5 = Scenario(
    name="IV +5pts",
    vol_change_points=5.0,
    scenario_type=ScenarioType.VOL_SHOCK,
    description="Moderate vol expansion"
)

SCENARIO_VOL_UP_10 = Scenario(
    name="IV +10pts",
    vol_change_points=10.0,
    scenario_type=ScenarioType.VOL_SHOCK,
    description="Strong vol expansion (fear spike)"
)

SCENARIO_VOL_DOWN_5 = Scenario(
    name="IV -5pts",
    vol_change_points=-5.0,
    scenario_type=ScenarioType.VOL_SHOCK,
    description="Vol contraction"
)

# Combined shock scenarios
SCENARIO_CRASH = Scenario(
    name="Crash: -2% + IV+10",
    price_change_pct=-0.02,
    vol_change_points=10.0,
    scenario_type=ScenarioType.COMBINED,
    description="Market selloff with vol spike (typical crash)"
)

SCENARIO_RALLY = Scenario(
    name="Rally: +2% + IV-5",
    price_change_pct=0.02,
    vol_change_points=-5.0,
    scenario_type=ScenarioType.COMBINED,
    description="Market rally with vol crush"
)

SCENARIO_VOL_EXPLOSION = Scenario(
    name="Vol Explosion: 0% + IV+15",
    price_change_pct=0.0,
    vol_change_points=15.0,
    scenario_type=ScenarioType.VOL_SHOCK,
    description="Extreme vol spike without directional move"
)

# Standard scenario set
STANDARD_SCENARIOS: List[Scenario] = [
    SCENARIO_PRICE_DOWN_5,
    SCENARIO_PRICE_DOWN_2,
    SCENARIO_PRICE_DOWN_1,
    SCENARIO_PRICE_UP_1,
    SCENARIO_PRICE_UP_2,
    SCENARIO_PRICE_UP_5,
    SCENARIO_VOL_UP_5,
    SCENARIO_VOL_UP_10,
    SCENARIO_VOL_DOWN_5,
    SCENARIO_CRASH,
    SCENARIO_RALLY,
]


# =============================================================================
# STRESS TEST RESULTS
# =============================================================================

@dataclass
class ScenarioResult:
    """Result of stress testing a single scenario."""
    scenario: Scenario
    estimated_pnl: float              # Estimated P&L in dollars
    delta_contribution: float         # P&L from delta
    gamma_contribution: float         # P&L from gamma (convexity)
    vega_contribution: float          # P&L from vega
    
    # Risk flags
    exceeds_threshold: bool = False
    warning_message: str = ""
    
    # Approximation quality
    approximation_reliable: bool = True
    approximation_note: str = ""
    
    @property
    def is_loss(self) -> bool:
        return self.estimated_pnl < 0
    
    @property
    def severity(self) -> str:
        """Classify severity of P&L impact."""
        if self.estimated_pnl >= 0:
            return "GAIN"
        elif self.estimated_pnl > -100:
            return "MINOR_LOSS"
        elif self.estimated_pnl > -500:
            return "MODERATE_LOSS"
        else:
            return "SEVERE_LOSS"


@dataclass
class StressTestResult:
    """Complete stress test results for a portfolio."""
    scenario_results: List[ScenarioResult] = field(default_factory=list)
    
    # Portfolio info used
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_vega: float = 0.0
    spot_price: float = 0.0
    
    # Summary stats
    worst_case_pnl: float = 0.0
    worst_case_scenario: Optional[Scenario] = None
    best_case_pnl: float = 0.0
    best_case_scenario: Optional[Scenario] = None
    
    # Risk flags
    has_threshold_breach: bool = False
    breach_scenarios: List[str] = field(default_factory=list)
    
    @classmethod
    def from_results(cls, results: List[ScenarioResult], 
                     delta: float, gamma: float, vega: float, 
                     spot: float) -> "StressTestResult":
        """Create StressTestResult from list of scenario results."""
        if not results:
            return cls()
        
        worst = min(results, key=lambda r: r.estimated_pnl)
        best = max(results, key=lambda r: r.estimated_pnl)
        
        breaches = [r.scenario.name for r in results if r.exceeds_threshold]
        
        return cls(
            scenario_results=results,
            net_delta=delta,
            net_gamma=gamma,
            net_vega=vega,
            spot_price=spot,
            worst_case_pnl=worst.estimated_pnl,
            worst_case_scenario=worst.scenario,
            best_case_pnl=best.estimated_pnl,
            best_case_scenario=best.scenario,
            has_threshold_breach=len(breaches) > 0,
            breach_scenarios=breaches
        )


# =============================================================================
# STRESS TEST CONFIGURATION
# =============================================================================

@dataclass
class StressTestConfig:
    """Configuration for stress testing."""
    # Loss thresholds (in dollars)
    max_acceptable_loss: float = 500.0      # Flag scenarios exceeding this loss
    severe_loss_threshold: float = 1000.0   # Flag as severe
    
    # Approximation reliability thresholds
    large_move_threshold: float = 0.05      # >5% move considered "large"
    
    # Contract multiplier
    contract_multiplier: int = 100          # Options are for 100 shares


# =============================================================================
# STRESS TEST ENGINE
# =============================================================================

class StressTestEngine:
    """Engine for running scenario stress tests.
    
    Uses second-order Taylor approximation:
    ΔP&L ≈ Δ × ΔS + 0.5 × Γ × (ΔS)² + V × Δσ
    
    Where:
    - Δ = Position delta
    - Γ = Position gamma
    - V = Position vega
    - ΔS = Price change in dollars
    - Δσ = IV change in percentage points
    """
    
    def __init__(self, config: Optional[StressTestConfig] = None):
        self.config = config or StressTestConfig()
    
    def calculate_scenario_pnl(
        self,
        scenario: Scenario,
        delta: float,
        gamma: float,
        vega: float,
        spot: float
    ) -> ScenarioResult:
        """Calculate estimated P&L for a single scenario.
        
        Args:
            scenario: The market scenario to test
            delta: Net position delta
            gamma: Net position gamma
            vega: Net position vega
            spot: Current spot price
            
        Returns:
            ScenarioResult with estimated P&L breakdown
        """
        # Calculate price change in dollars
        price_change = spot * scenario.price_change_pct
        
        # Taylor approximation components:
        # ΔP&L ≈ Δ × ΔS + 0.5 × Γ × (ΔS)² + V × Δσ
        
        # Delta contribution: Δ × ΔS × 100 (per contract)
        delta_pnl = delta * price_change * self.config.contract_multiplier
        
        # Gamma contribution: 0.5 × Γ × (ΔS)² × 100
        gamma_pnl = 0.5 * gamma * (price_change ** 2) * self.config.contract_multiplier
        
        # Vega contribution: V × Δσ × 100
        # Note: Vega is typically per 1% IV change, so divide by 100
        # But scenario.vol_change_points is in percentage points (e.g., 10 = 10pts)
        # Standard vega convention: $ change per 1 IV point
        vega_pnl = vega * scenario.vol_change_points * self.config.contract_multiplier
        
        # Total estimated P&L
        total_pnl = delta_pnl + gamma_pnl + vega_pnl
        
        # Check approximation reliability
        is_large_move = abs(scenario.price_change_pct) >= self.config.large_move_threshold
        approx_note = ""
        if is_large_move:
            approx_note = f"Large move ({scenario.price_change_pct:.0%}) - approximation less reliable"
        
        # Check threshold breach
        exceeds = total_pnl < -self.config.max_acceptable_loss
        warning = ""
        if total_pnl < -self.config.severe_loss_threshold:
            warning = f"SEVERE: Estimated loss ${abs(total_pnl):.0f} exceeds severe threshold"
        elif exceeds:
            warning = f"WARNING: Estimated loss ${abs(total_pnl):.0f} exceeds max acceptable"
        
        return ScenarioResult(
            scenario=scenario,
            estimated_pnl=round(total_pnl, 2),
            delta_contribution=round(delta_pnl, 2),
            gamma_contribution=round(gamma_pnl, 2),
            vega_contribution=round(vega_pnl, 2),
            exceeds_threshold=exceeds,
            warning_message=warning,
            approximation_reliable=not is_large_move,
            approximation_note=approx_note
        )
    
    def run_stress_test(
        self,
        delta: float,
        gamma: float,
        vega: float,
        spot: float,
        scenarios: Optional[List[Scenario]] = None
    ) -> StressTestResult:
        """Run stress test across multiple scenarios.
        
        Args:
            delta: Net position delta
            gamma: Net position gamma
            vega: Net position vega
            spot: Current spot price
            scenarios: List of scenarios to test (defaults to STANDARD_SCENARIOS)
            
        Returns:
            StressTestResult with all scenario outcomes
        """
        if scenarios is None:
            scenarios = STANDARD_SCENARIOS
        
        results = []
        for scenario in scenarios:
            result = self.calculate_scenario_pnl(scenario, delta, gamma, vega, spot)
            results.append(result)
        
        return StressTestResult.from_results(results, delta, gamma, vega, spot)
    
    def compare_with_trade(
        self,
        current_delta: float,
        current_gamma: float,
        current_vega: float,
        trade_delta: float,
        trade_gamma: float,
        trade_vega: float,
        spot: float,
        scenarios: Optional[List[Scenario]] = None
    ) -> Tuple[StressTestResult, StressTestResult]:
        """Compare stress results before and after adding a trade.
        
        Returns:
            (before_result, after_result) tuple
        """
        before = self.run_stress_test(
            current_delta, current_gamma, current_vega, spot, scenarios
        )
        
        after = self.run_stress_test(
            current_delta + trade_delta,
            current_gamma + trade_gamma,
            current_vega + trade_vega,
            spot,
            scenarios
        )
        
        return before, after


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def run_quick_stress_test(
    delta: float, 
    gamma: float, 
    vega: float, 
    spot: float
) -> StressTestResult:
    """Run stress test with default configuration."""
    engine = StressTestEngine()
    return engine.run_stress_test(delta, gamma, vega, spot)


def format_stress_result(result: ScenarioResult) -> str:
    """Format a single scenario result for display."""
    pnl_str = f"${result.estimated_pnl:+,.0f}"
    severity = result.severity
    
    if severity == "SEVERE_LOSS":
        return f"🔴 {result.scenario.name}: {pnl_str}"
    elif severity == "MODERATE_LOSS":
        return f"🟠 {result.scenario.name}: {pnl_str}"
    elif severity == "MINOR_LOSS":
        return f"🟡 {result.scenario.name}: {pnl_str}"
    else:
        return f"🟢 {result.scenario.name}: {pnl_str}"


def get_stress_summary(result: StressTestResult) -> Dict[str, str]:
    """Get summary statistics from stress test."""
    return {
        'worst_case': f"{result.worst_case_scenario.name}: ${result.worst_case_pnl:+,.0f}" if result.worst_case_scenario else "N/A",
        'best_case': f"{result.best_case_scenario.name}: ${result.best_case_pnl:+,.0f}" if result.best_case_scenario else "N/A",
        'breaches': str(len(result.breach_scenarios)),
        'has_severe': "YES" if result.worst_case_pnl < -1000 else "NO"
    }
