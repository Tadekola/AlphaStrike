"""
PR #4: Regime–Strategy Suitability Enforcement - Unit Tests

Tests to verify regime detection and strategy suitability enforcement.
"""
import pytest
from cal_pro.engine.regime import (
    MarketRegime, RegimeThresholds, RegimeClassification,
    RegimeDetector, SuitabilityEnforcer, StrategySuitability,
    SUITABILITY_MATRIX,
    STRATEGY_IRON_CONDOR, STRATEGY_IRON_BUTTERFLY,
    STRATEGY_VERTICAL, STRATEGY_CALENDAR, STRATEGY_SHORT_STRANGLE
)


class TestRegimeDetection:
    """Test regime detection based on indicator values."""
    
    def setup_method(self):
        self.detector = RegimeDetector()
    
    def test_strong_trend_detection(self):
        """ADX > 30 should detect STRONG_TREND."""
        regime = self.detector.detect(adx=35.0, hv5=0.20, hv20=0.20)
        assert regime.trend_regime == MarketRegime.STRONG_TREND
    
    def test_weak_trend_detection(self):
        """20 < ADX <= 30 should detect WEAK_TREND."""
        regime = self.detector.detect(adx=25.0, hv5=0.20, hv20=0.20)
        assert regime.trend_regime == MarketRegime.WEAK_TREND
    
    def test_range_bound_detection(self):
        """ADX <= 20 should detect RANGE_BOUND."""
        regime = self.detector.detect(adx=15.0, hv5=0.20, hv20=0.20)
        assert regime.trend_regime == MarketRegime.RANGE_BOUND
    
    def test_vol_expansion_detection(self):
        """HV5/HV20 > 1.2 should detect VOL_EXPANSION."""
        regime = self.detector.detect(adx=20.0, hv5=0.30, hv20=0.20)
        assert regime.vol_regime == MarketRegime.VOL_EXPANSION
    
    def test_vol_contraction_detection(self):
        """HV5/HV20 < 0.8 should detect VOL_CONTRACTION."""
        regime = self.detector.detect(adx=20.0, hv5=0.10, hv20=0.20)
        assert regime.vol_regime == MarketRegime.VOL_CONTRACTION
    
    def test_vol_neutral_detection(self):
        """0.8 <= HV5/HV20 <= 1.2 should detect VOL_NEUTRAL."""
        regime = self.detector.detect(adx=20.0, hv5=0.20, hv20=0.20)
        assert regime.vol_regime == MarketRegime.VOL_NEUTRAL
    
    def test_combined_label(self):
        """Combined label should include both trend and vol regime."""
        regime = self.detector.detect(adx=35.0, hv5=0.30, hv20=0.20)
        assert "STRONG_TREND" in regime.combined_label
        assert "VOL_EXPANSION" in regime.combined_label
    
    def test_is_high_risk(self):
        """High risk should be True for strong trend or vol expansion."""
        strong_trend = self.detector.detect(adx=35.0, hv5=0.20, hv20=0.20)
        assert strong_trend.is_high_risk == True
        
        vol_expansion = self.detector.detect(adx=15.0, hv5=0.30, hv20=0.20)
        assert vol_expansion.is_high_risk == True
        
        safe = self.detector.detect(adx=15.0, hv5=0.20, hv20=0.20)
        assert safe.is_high_risk == False


class TestSuitabilityMatrix:
    """Test the suitability matrix has correct entries."""
    
    def test_iron_condor_forbidden_in_strong_trend(self):
        """Iron Condor should be forbidden in strong trend."""
        rules = SUITABILITY_MATRIX[STRATEGY_IRON_CONDOR]
        assert MarketRegime.STRONG_TREND not in rules.allowed_trend_regimes
    
    def test_iron_condor_forbidden_in_vol_expansion(self):
        """Iron Condor should be forbidden in vol expansion."""
        rules = SUITABILITY_MATRIX[STRATEGY_IRON_CONDOR]
        assert MarketRegime.VOL_EXPANSION not in rules.allowed_vol_regimes
    
    def test_iron_condor_allowed_in_range_bound(self):
        """Iron Condor should be allowed in range-bound markets."""
        rules = SUITABILITY_MATRIX[STRATEGY_IRON_CONDOR]
        assert MarketRegime.RANGE_BOUND in rules.allowed_trend_regimes
    
    def test_vertical_allowed_in_all_trend_regimes(self):
        """Vertical spreads should be allowed in all trend regimes."""
        rules = SUITABILITY_MATRIX[STRATEGY_VERTICAL]
        assert MarketRegime.STRONG_TREND in rules.allowed_trend_regimes
        assert MarketRegime.WEAK_TREND in rules.allowed_trend_regimes
        assert MarketRegime.RANGE_BOUND in rules.allowed_trend_regimes
    
    def test_short_strangle_most_restrictive(self):
        """Short Strangle should be most restrictive (range + vol contraction only)."""
        rules = SUITABILITY_MATRIX[STRATEGY_SHORT_STRANGLE]
        assert rules.allowed_trend_regimes == {MarketRegime.RANGE_BOUND}
        assert rules.allowed_vol_regimes == {MarketRegime.VOL_CONTRACTION}


class TestSuitabilityEnforcer:
    """Test suitability enforcement logic."""
    
    def setup_method(self):
        self.enforcer = SuitabilityEnforcer()
        self.detector = RegimeDetector()
    
    def test_iron_condor_rejected_in_strong_trend(self):
        """Iron Condor should be rejected in strong trend."""
        regime = self.detector.detect(adx=35.0, hv5=0.15, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_IRON_CONDOR, regime)
        
        assert result.is_suitable == False
        assert result.trend_violation == True
        assert "range-bound" in result.rejection_reason.lower() or "trend" in result.rejection_reason.lower()
    
    def test_iron_condor_rejected_in_vol_expansion(self):
        """Iron Condor should be rejected in vol expansion."""
        regime = self.detector.detect(adx=15.0, hv5=0.30, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_IRON_CONDOR, regime)
        
        assert result.is_suitable == False
        assert result.vol_violation == True
        assert "vega" in result.rejection_reason.lower() or "vol" in result.rejection_reason.lower()
    
    def test_iron_condor_allowed_in_ideal_conditions(self):
        """Iron Condor should be allowed in range-bound + vol contraction."""
        regime = self.detector.detect(adx=15.0, hv5=0.10, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_IRON_CONDOR, regime)
        
        assert result.is_suitable == True
        assert result.rejection_reason == ""
    
    def test_calendar_rejected_in_strong_trend(self):
        """Calendar should be rejected in strong trend."""
        regime = self.detector.detect(adx=35.0, hv5=0.20, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_CALENDAR, regime)
        
        assert result.is_suitable == False
        assert result.trend_violation == True
    
    def test_calendar_allowed_in_vol_expansion(self):
        """Calendar should be allowed in vol expansion (it's long vega)."""
        regime = self.detector.detect(adx=15.0, hv5=0.30, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_CALENDAR, regime)
        
        # Calendar is allowed in range-bound + vol expansion
        assert result.is_suitable == True
    
    def test_short_strangle_rejected_in_most_conditions(self):
        """Short Strangle should only be allowed in range-bound + vol contraction."""
        # Test various "bad" conditions
        regimes_to_reject = [
            (35.0, 0.15, 0.20),  # Strong trend
            (25.0, 0.15, 0.20),  # Weak trend
            (15.0, 0.30, 0.20),  # Vol expansion
            (15.0, 0.20, 0.20),  # Vol neutral
        ]
        
        for adx, hv5, hv20 in regimes_to_reject:
            regime = self.detector.detect(adx=adx, hv5=hv5, hv20=hv20)
            result = self.enforcer.check_suitability(STRATEGY_SHORT_STRANGLE, regime)
            assert result.is_suitable == False, f"Should reject at ADX={adx}, HV5={hv5}, HV20={hv20}"
    
    def test_short_strangle_allowed_only_in_ideal(self):
        """Short Strangle should only be allowed in range-bound + vol contraction."""
        regime = self.detector.detect(adx=15.0, hv5=0.10, hv20=0.20)
        result = self.enforcer.check_suitability(STRATEGY_SHORT_STRANGLE, regime)
        
        assert result.is_suitable == True
    
    def test_unknown_strategy_allowed_with_warning(self):
        """Unknown strategy should be allowed but with warning."""
        regime = self.detector.detect(adx=25.0, hv5=0.20, hv20=0.20)
        result = self.enforcer.check_suitability("Unknown Strategy XYZ", regime)
        
        assert result.is_suitable == True
        assert len(result.warnings) > 0
        assert "no suitability rules" in result.warnings[0].lower()


class TestGetAllowedForbiddenStrategies:
    """Test getting lists of allowed/forbidden strategies."""
    
    def setup_method(self):
        self.enforcer = SuitabilityEnforcer()
        self.detector = RegimeDetector()
    
    def test_get_allowed_strategies_range_contraction(self):
        """In range-bound + vol contraction, most strategies should be allowed."""
        regime = self.detector.detect(adx=15.0, hv5=0.10, hv20=0.20)
        allowed = self.enforcer.get_allowed_strategies(regime)
        
        assert STRATEGY_IRON_CONDOR in allowed
        assert STRATEGY_SHORT_STRANGLE in allowed
    
    def test_get_forbidden_strategies_strong_trend(self):
        """In strong trend, neutral strategies should be forbidden."""
        regime = self.detector.detect(adx=35.0, hv5=0.20, hv20=0.20)
        forbidden = self.enforcer.get_forbidden_strategies(regime)
        
        forbidden_names = [name for name, reason in forbidden]
        assert STRATEGY_IRON_CONDOR in forbidden_names
        assert STRATEGY_IRON_BUTTERFLY in forbidden_names


class TestRegimeThresholds:
    """Test customizable thresholds."""
    
    def test_custom_adx_threshold(self):
        """Custom ADX threshold should be respected."""
        custom = RegimeThresholds(adx_strong_trend=40.0)
        detector = RegimeDetector(thresholds=custom)
        
        # ADX=35 should now be weak trend, not strong
        regime = detector.detect(adx=35.0, hv5=0.20, hv20=0.20)
        assert regime.trend_regime == MarketRegime.WEAK_TREND
    
    def test_custom_hv_ratio_threshold(self):
        """Custom HV ratio threshold should be respected."""
        custom = RegimeThresholds(hv_expansion_ratio=1.5)
        detector = RegimeDetector(thresholds=custom)
        
        # HV ratio 1.3 should now be neutral, not expansion
        regime = detector.detect(adx=20.0, hv5=0.26, hv20=0.20)  # ratio = 1.3
        assert regime.vol_regime == MarketRegime.VOL_NEUTRAL


class TestRegimeClassificationProperties:
    """Test RegimeClassification dataclass properties."""
    
    def test_hv_ratio_stored(self):
        """HV ratio should be stored in classification."""
        detector = RegimeDetector()
        regime = detector.detect(adx=20.0, hv5=0.30, hv20=0.20)
        
        assert abs(regime.hv_ratio - 1.5) < 0.01
    
    def test_description_includes_values(self):
        """Description should include indicator values."""
        detector = RegimeDetector()
        regime = detector.detect(adx=35.0, hv5=0.30, hv20=0.20)
        
        assert "35" in regime.description or "ADX" in regime.description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
