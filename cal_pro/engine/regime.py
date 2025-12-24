"""
PR #4: Regime–Strategy Suitability Enforcement

This module defines market regimes and enforces strategy suitability rules.
Strategies that are structurally inappropriate for the detected regime are rejected.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Tuple


class MarketRegime(Enum):
    """Market regime classifications based on trend and volatility indicators.
    
    Each regime has explicit numeric thresholds documented below.
    """
    # Trend-based regimes
    STRONG_TREND = "STRONG_TREND"      # ADX > 30, clear directional bias
    WEAK_TREND = "WEAK_TREND"          # 20 < ADX <= 30, mild directional bias
    RANGE_BOUND = "RANGE_BOUND"        # ADX <= 20, no clear direction
    
    # Volatility-based regimes (overlays)
    VOL_EXPANSION = "VOL_EXPANSION"    # HV5 > HV20 * 1.2 (short-term vol spiking)
    VOL_CONTRACTION = "VOL_CONTRACTION"  # HV5 < HV20 * 0.8 (short-term vol compressing)
    VOL_NEUTRAL = "VOL_NEUTRAL"        # Neither expansion nor contraction
    
    # Combined regime (for display)
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeThresholds:
    """Explicit numeric thresholds for regime classification.
    
    All thresholds are documented with rationale.
    """
    # ADX thresholds for trend strength
    adx_strong_trend: float = 30.0    # ADX > 30: Strong directional movement
    adx_weak_trend: float = 20.0      # 20 < ADX <= 30: Mild trend
    # ADX <= 20: Range-bound / no trend
    
    # HV ratio thresholds for volatility regime
    hv_expansion_ratio: float = 1.2   # HV5/HV20 > 1.2: Vol expanding
    hv_contraction_ratio: float = 0.8 # HV5/HV20 < 0.8: Vol contracting
    
    # Minimum HV to consider (avoid division issues)
    hv_floor: float = 0.05  # 5% annualized minimum


@dataclass 
class RegimeClassification:
    """Complete regime classification for a market state."""
    trend_regime: MarketRegime
    vol_regime: MarketRegime
    
    # Indicator values used
    adx: float
    hv5: float
    hv20: float
    hv_ratio: float
    
    # Human-readable description
    description: str = ""
    
    @property
    def combined_label(self) -> str:
        """Combined regime label for display."""
        return f"{self.trend_regime.value} / {self.vol_regime.value}"
    
    @property
    def is_high_risk(self) -> bool:
        """True if regime is particularly dangerous for certain strategies."""
        return (self.trend_regime == MarketRegime.STRONG_TREND or 
                self.vol_regime == MarketRegime.VOL_EXPANSION)


# Strategy names (must match strategy_name in CandidateTrade)
STRATEGY_IRON_CONDOR = "Iron Condor"
STRATEGY_IRON_BUTTERFLY = "Iron Butterfly"
STRATEGY_VERTICAL = "Bull Put Vertical"
STRATEGY_VERTICAL_BEAR = "Bear Call Vertical"
STRATEGY_CALENDAR = "Calendar"
STRATEGY_SHORT_STRANGLE = "Short Strangle"
STRATEGY_JADE_LIZARD = "Jade Lizard"
STRATEGY_BUTTERFLY = "Long Call Butterfly"
STRATEGY_DIAGONAL = "PMCC / Diagonal"
STRATEGY_RATIO_CALL = "Call Ratio 1x2"
STRATEGY_RATIO_PUT = "Put Ratio 1x2"


@dataclass
class StrategySuitability:
    """Suitability rules for a strategy in different regimes."""
    strategy_name: str
    
    # Allowed trend regimes
    allowed_trend_regimes: Set[MarketRegime] = field(default_factory=set)
    
    # Allowed vol regimes
    allowed_vol_regimes: Set[MarketRegime] = field(default_factory=set)
    
    # Rejection reasons for forbidden combinations
    trend_rejection_reason: str = ""
    vol_rejection_reason: str = ""
    
    # Risk warnings (shown even if allowed)
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# STRATEGY SUITABILITY MATRIX
# =============================================================================
# This is the core declarative matrix that maps regimes to allowed strategies.
# Each entry documents WHY certain combinations are forbidden.

SUITABILITY_MATRIX: Dict[str, StrategySuitability] = {
    # -------------------------------------------------------------------------
    # IRON CONDOR: Neutral, range-bound strategy. Short gamma.
    # FORBIDDEN: Strong trends (will blow through wings)
    # FORBIDDEN: Vol expansion (short vega gets crushed)
    # -------------------------------------------------------------------------
    STRATEGY_IRON_CONDOR: StrategySuitability(
        strategy_name=STRATEGY_IRON_CONDOR,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Iron Condors are range-bound strategies. Strong trends will breach wings.",
        vol_rejection_reason="Iron Condors are short vega. Vol expansion will cause losses.",
        warnings=["Short gamma position - monitor closely near expiration"]
    ),
    
    # -------------------------------------------------------------------------
    # IRON BUTTERFLY: Aggressive neutral. Even more sensitive than IC.
    # FORBIDDEN: Any trend (very narrow profit zone)
    # FORBIDDEN: Vol expansion
    # -------------------------------------------------------------------------
    STRATEGY_IRON_BUTTERFLY: StrategySuitability(
        strategy_name=STRATEGY_IRON_BUTTERFLY,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Iron Butterflies require price to stay near center strike. Any trend is dangerous.",
        vol_rejection_reason="Iron Butterflies are short vega. Vol expansion will cause significant losses.",
        warnings=["Extremely narrow profit zone", "Max profit only at center strike"]
    ),
    
    # -------------------------------------------------------------------------
    # VERTICAL SPREADS (Bull Put / Bear Call): Directional strategies.
    # ALLOWED: Trends (that's the point)
    # ALLOWED: All vol regimes (defined risk)
    # -------------------------------------------------------------------------
    STRATEGY_VERTICAL: StrategySuitability(
        strategy_name=STRATEGY_VERTICAL,
        allowed_trend_regimes={MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND, MarketRegime.RANGE_BOUND},
        allowed_vol_regimes={MarketRegime.VOL_EXPANSION, MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="",  # Allowed in all trend regimes
        vol_rejection_reason="",    # Allowed in all vol regimes
        warnings=["Ensure spread direction aligns with trend bias"]
    ),
    
    STRATEGY_VERTICAL_BEAR: StrategySuitability(
        strategy_name=STRATEGY_VERTICAL_BEAR,
        allowed_trend_regimes={MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND, MarketRegime.RANGE_BOUND},
        allowed_vol_regimes={MarketRegime.VOL_EXPANSION, MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="",
        vol_rejection_reason="",
        warnings=["Ensure spread direction aligns with trend bias"]
    ),
    
    # -------------------------------------------------------------------------
    # CALENDAR SPREAD: Long vega, benefits from vol expansion.
    # FORBIDDEN: Strong trend (front month gets crushed directionally)
    # PREFERRED: Vol expansion (that's the thesis)
    # -------------------------------------------------------------------------
    STRATEGY_CALENDAR: StrategySuitability(
        strategy_name=STRATEGY_CALENDAR,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_EXPANSION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Calendars require price stability near strike. Strong trends move price away.",
        vol_rejection_reason="",  # Actually benefits from vol expansion
        warnings=["Best entered when expecting vol to rise"]
    ),
    
    # -------------------------------------------------------------------------
    # SHORT STRANGLE: Undefined risk. Short gamma AND short vega.
    # FORBIDDEN: Strong trend (will test one side hard)
    # FORBIDDEN: Vol expansion (short vega disaster)
    # -------------------------------------------------------------------------
    STRATEGY_SHORT_STRANGLE: StrategySuitability(
        strategy_name=STRATEGY_SHORT_STRANGLE,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION},
        trend_rejection_reason="Short Strangles have undefined risk. Strong trends will cause large losses.",
        vol_rejection_reason="Short Strangles are short vega. Vol expansion is catastrophic.",
        warnings=["UNDEFINED RISK", "Requires active management", "Not suitable for small accounts"]
    ),
    
    # -------------------------------------------------------------------------
    # JADE LIZARD: Short put + bear call spread. No upside risk if done right.
    # Similar to short strangle but with upside protection.
    # FORBIDDEN: Strong uptrend (bear call spread loses)
    # FORBIDDEN: Vol expansion (short vega)
    # -------------------------------------------------------------------------
    STRATEGY_JADE_LIZARD: StrategySuitability(
        strategy_name=STRATEGY_JADE_LIZARD,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Jade Lizard has naked put risk. Strong trends increase assignment risk.",
        vol_rejection_reason="Jade Lizard is short vega. Vol expansion hurts.",
        warnings=["Naked put risk on downside"]
    ),
    
    # -------------------------------------------------------------------------
    # LONG BUTTERFLY: Defined risk, low cost, narrow profit zone.
    # ALLOWED: Range-bound (needs price near center)
    # ALLOWED: Vol contraction (cheaper entry, less movement expected)
    # -------------------------------------------------------------------------
    STRATEGY_BUTTERFLY: StrategySuitability(
        strategy_name=STRATEGY_BUTTERFLY,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL, MarketRegime.VOL_EXPANSION},
        trend_rejection_reason="Long Butterflies need price near center strike. Strong trends move away.",
        vol_rejection_reason="",
        warnings=["Low probability of max profit", "Consider as lottery ticket"]
    ),
    
    # -------------------------------------------------------------------------
    # PMCC / DIAGONAL: Long LEAP + short near-term call. Bullish bias.
    # ALLOWED: Uptrends (that's the thesis)
    # FORBIDDEN: Strong downtrend would hurt LEAP value
    # -------------------------------------------------------------------------
    STRATEGY_DIAGONAL: StrategySuitability(
        strategy_name=STRATEGY_DIAGONAL,
        allowed_trend_regimes={MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND, MarketRegime.RANGE_BOUND},
        allowed_vol_regimes={MarketRegime.VOL_EXPANSION, MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="",
        vol_rejection_reason="",
        warnings=["Requires long-term bullish bias", "LEAP value at risk if underlying drops significantly"]
    ),
    
    # -------------------------------------------------------------------------
    # RATIO SPREADS (1x2): Buy 1, Sell 2. Exposed risk beyond breakeven.
    # FORBIDDEN: Strong trends (will blow through the naked leg)
    # FORBIDDEN: Vol expansion (short more vega than long)
    # -------------------------------------------------------------------------
    STRATEGY_RATIO_CALL: StrategySuitability(
        strategy_name=STRATEGY_RATIO_CALL,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Ratio spreads have naked leg exposure. Strong trends cause unlimited losses.",
        vol_rejection_reason="Ratio spreads are net short vega. Vol expansion hurts.",
        warnings=["EXPOSED RISK beyond upper breakeven", "Expert strategy only"]
    ),
    
    STRATEGY_RATIO_PUT: StrategySuitability(
        strategy_name=STRATEGY_RATIO_PUT,
        allowed_trend_regimes={MarketRegime.RANGE_BOUND, MarketRegime.WEAK_TREND},
        allowed_vol_regimes={MarketRegime.VOL_CONTRACTION, MarketRegime.VOL_NEUTRAL},
        trend_rejection_reason="Ratio spreads have naked leg exposure. Strong trends cause unlimited losses.",
        vol_rejection_reason="Ratio spreads are net short vega. Vol expansion hurts.",
        warnings=["EXPOSED RISK beyond lower breakeven", "Expert strategy only"]
    ),
}


@dataclass
class SuitabilityResult:
    """Result of checking strategy suitability for a regime."""
    strategy_name: str
    is_suitable: bool
    regime: RegimeClassification
    
    # If rejected
    rejection_reason: str = ""
    trend_violation: bool = False
    vol_violation: bool = False
    
    # Warnings (even if suitable)
    warnings: List[str] = field(default_factory=list)


class RegimeDetector:
    """Detects market regime from indicators."""
    
    def __init__(self, thresholds: Optional[RegimeThresholds] = None):
        self.thresholds = thresholds or RegimeThresholds()
    
    def detect(self, adx: float, hv5: float, hv20: float) -> RegimeClassification:
        """Detect market regime from indicator values.
        
        Args:
            adx: ADX value (14-period, Wilder-smoothed)
            hv5: 5-day historical volatility (annualized)
            hv20: 20-day historical volatility (annualized)
            
        Returns:
            RegimeClassification with trend and vol regime
        """
        # Trend regime classification
        if adx > self.thresholds.adx_strong_trend:
            trend_regime = MarketRegime.STRONG_TREND
        elif adx > self.thresholds.adx_weak_trend:
            trend_regime = MarketRegime.WEAK_TREND
        else:
            trend_regime = MarketRegime.RANGE_BOUND
        
        # Vol regime classification
        # Ensure we don't divide by zero
        hv20_safe = max(hv20, self.thresholds.hv_floor)
        hv_ratio = hv5 / hv20_safe
        
        if hv_ratio > self.thresholds.hv_expansion_ratio:
            vol_regime = MarketRegime.VOL_EXPANSION
        elif hv_ratio < self.thresholds.hv_contraction_ratio:
            vol_regime = MarketRegime.VOL_CONTRACTION
        else:
            vol_regime = MarketRegime.VOL_NEUTRAL
        
        # Build description
        trend_desc = {
            MarketRegime.STRONG_TREND: f"Strong trend (ADX={adx:.1f} > {self.thresholds.adx_strong_trend})",
            MarketRegime.WEAK_TREND: f"Weak trend (ADX={adx:.1f})",
            MarketRegime.RANGE_BOUND: f"Range-bound (ADX={adx:.1f} ≤ {self.thresholds.adx_weak_trend})",
        }
        
        vol_desc = {
            MarketRegime.VOL_EXPANSION: f"Vol expanding (HV5/HV20={hv_ratio:.2f} > {self.thresholds.hv_expansion_ratio})",
            MarketRegime.VOL_CONTRACTION: f"Vol contracting (HV5/HV20={hv_ratio:.2f} < {self.thresholds.hv_contraction_ratio})",
            MarketRegime.VOL_NEUTRAL: f"Vol neutral (HV5/HV20={hv_ratio:.2f})",
        }
        
        description = f"{trend_desc.get(trend_regime, '')}; {vol_desc.get(vol_regime, '')}"
        
        return RegimeClassification(
            trend_regime=trend_regime,
            vol_regime=vol_regime,
            adx=adx,
            hv5=hv5,
            hv20=hv20,
            hv_ratio=hv_ratio,
            description=description
        )


class SuitabilityEnforcer:
    """Enforces strategy suitability based on market regime."""
    
    def __init__(self, matrix: Optional[Dict[str, StrategySuitability]] = None):
        self.matrix = matrix or SUITABILITY_MATRIX
    
    def check_suitability(
        self, 
        strategy_name: str, 
        regime: RegimeClassification
    ) -> SuitabilityResult:
        """Check if a strategy is suitable for the given regime.
        
        Args:
            strategy_name: Name of the strategy (must match CandidateTrade.strategy_name)
            regime: Detected market regime
            
        Returns:
            SuitabilityResult with pass/fail and reasons
        """
        # Get suitability rules for this strategy
        rules = self.matrix.get(strategy_name)
        
        if rules is None:
            # Unknown strategy - allow with warning
            return SuitabilityResult(
                strategy_name=strategy_name,
                is_suitable=True,
                regime=regime,
                warnings=[f"No suitability rules defined for '{strategy_name}'"]
            )
        
        # Check trend regime
        trend_ok = regime.trend_regime in rules.allowed_trend_regimes
        
        # Check vol regime
        vol_ok = regime.vol_regime in rules.allowed_vol_regimes
        
        # Build rejection reason if needed
        rejection_reasons = []
        if not trend_ok:
            rejection_reasons.append(rules.trend_rejection_reason)
        if not vol_ok:
            rejection_reasons.append(rules.vol_rejection_reason)
        
        is_suitable = trend_ok and vol_ok
        
        return SuitabilityResult(
            strategy_name=strategy_name,
            is_suitable=is_suitable,
            regime=regime,
            rejection_reason=" | ".join(rejection_reasons) if rejection_reasons else "",
            trend_violation=not trend_ok,
            vol_violation=not vol_ok,
            warnings=rules.warnings if is_suitable else []
        )
    
    def get_allowed_strategies(self, regime: RegimeClassification) -> List[str]:
        """Get list of strategies allowed in the given regime."""
        allowed = []
        for strategy_name, rules in self.matrix.items():
            if (regime.trend_regime in rules.allowed_trend_regimes and
                regime.vol_regime in rules.allowed_vol_regimes):
                allowed.append(strategy_name)
        return allowed
    
    def get_forbidden_strategies(self, regime: RegimeClassification) -> List[Tuple[str, str]]:
        """Get list of forbidden strategies with reasons.
        
        Returns:
            List of (strategy_name, rejection_reason) tuples
        """
        forbidden = []
        for strategy_name in self.matrix:
            result = self.check_suitability(strategy_name, regime)
            if not result.is_suitable:
                forbidden.append((strategy_name, result.rejection_reason))
        return forbidden


# Convenience function for detecting regime from MarketState
def detect_regime_from_market(market: "MarketState") -> RegimeClassification:
    """Detect regime from a MarketState object."""
    detector = RegimeDetector()
    return detector.detect(market.adx14, market.hv5, market.hv20)
