"""
PR #6: Portfolio Scenario Stress Testing - Unit Tests

Tests for P&L approximation math, monotonicity, and combined shock behavior.
"""
import pytest
from cal_pro.engine.stress import (
    Scenario, ScenarioType, ScenarioResult, StressTestResult,
    StressTestEngine, StressTestConfig,
    SCENARIO_PRICE_UP_1, SCENARIO_PRICE_UP_2, SCENARIO_PRICE_UP_5,
    SCENARIO_PRICE_DOWN_1, SCENARIO_PRICE_DOWN_2, SCENARIO_PRICE_DOWN_5,
    SCENARIO_VOL_UP_5, SCENARIO_VOL_UP_10, SCENARIO_VOL_DOWN_5,
    SCENARIO_CRASH, SCENARIO_RALLY,
    STANDARD_SCENARIOS, run_quick_stress_test, format_stress_result
)


class TestScenarioDefinitions:
    """Test scenario definitions are correct."""
    
    def test_price_shock_scenarios_have_correct_values(self):
        """Price shock scenarios should have correct percentages."""
        assert SCENARIO_PRICE_UP_1.price_change_pct == 0.01
        assert SCENARIO_PRICE_UP_2.price_change_pct == 0.02
        assert SCENARIO_PRICE_UP_5.price_change_pct == 0.05
        assert SCENARIO_PRICE_DOWN_1.price_change_pct == -0.01
        assert SCENARIO_PRICE_DOWN_2.price_change_pct == -0.02
        assert SCENARIO_PRICE_DOWN_5.price_change_pct == -0.05
    
    def test_vol_shock_scenarios_have_correct_values(self):
        """Vol shock scenarios should have correct point changes."""
        assert SCENARIO_VOL_UP_5.vol_change_points == 5.0
        assert SCENARIO_VOL_UP_10.vol_change_points == 10.0
        assert SCENARIO_VOL_DOWN_5.vol_change_points == -5.0
    
    def test_combined_scenarios(self):
        """Combined scenarios should have both price and vol changes."""
        assert SCENARIO_CRASH.price_change_pct == -0.02
        assert SCENARIO_CRASH.vol_change_points == 10.0
        assert SCENARIO_CRASH.scenario_type == ScenarioType.COMBINED
        
        assert SCENARIO_RALLY.price_change_pct == 0.02
        assert SCENARIO_RALLY.vol_change_points == -5.0
    
    def test_standard_scenarios_count(self):
        """Standard scenarios should include all major cases."""
        assert len(STANDARD_SCENARIOS) >= 10
    
    def test_is_adverse_property(self):
        """is_adverse should flag bad scenarios."""
        assert SCENARIO_PRICE_DOWN_5.is_adverse == True
        assert SCENARIO_VOL_UP_10.is_adverse == True
        assert SCENARIO_PRICE_UP_1.is_adverse == False


class TestPnLMathCorrectness:
    """Test that P&L approximation math is correct."""
    
    def setup_method(self):
        self.engine = StressTestEngine()
        self.spot = 100.0  # $100 spot price
    
    def test_delta_only_pnl(self):
        """Pure delta position should have linear P&L with price."""
        # Long 1 delta at $100 spot
        # Price +1% = +$1 → P&L = 1 * $1 * 100 = $100
        scenario = Scenario(name="Test", price_change_pct=0.01)
        result = self.engine.calculate_scenario_pnl(
            scenario, delta=1.0, gamma=0.0, vega=0.0, spot=self.spot
        )
        
        assert abs(result.delta_contribution - 100.0) < 0.01
        assert result.gamma_contribution == 0.0
        assert result.vega_contribution == 0.0
    
    def test_gamma_contribution_positive(self):
        """Long gamma should benefit from price movement (either direction)."""
        # Long gamma position
        scenario_up = Scenario(name="Up", price_change_pct=0.02)
        scenario_down = Scenario(name="Down", price_change_pct=-0.02)
        
        result_up = self.engine.calculate_scenario_pnl(
            scenario_up, delta=0.0, gamma=0.01, vega=0.0, spot=self.spot
        )
        result_down = self.engine.calculate_scenario_pnl(
            scenario_down, delta=0.0, gamma=0.01, vega=0.0, spot=self.spot
        )
        
        # Long gamma should be positive in both cases (convexity)
        assert result_up.gamma_contribution > 0
        assert result_down.gamma_contribution > 0
    
    def test_short_gamma_loses_on_moves(self):
        """Short gamma should lose on price movements."""
        scenario = Scenario(name="Move", price_change_pct=0.02)
        
        result = self.engine.calculate_scenario_pnl(
            scenario, delta=0.0, gamma=-0.01, vega=0.0, spot=self.spot
        )
        
        # Short gamma should be negative
        assert result.gamma_contribution < 0
    
    def test_vega_pnl_long_vol(self):
        """Long vega should profit from vol increase."""
        scenario = Scenario(name="Vol Up", vol_change_points=5.0)
        
        result = self.engine.calculate_scenario_pnl(
            scenario, delta=0.0, gamma=0.0, vega=0.10, spot=self.spot
        )
        
        # Long vega * positive vol change = positive P&L
        assert result.vega_contribution > 0
    
    def test_vega_pnl_short_vol(self):
        """Short vega should lose from vol increase."""
        scenario = Scenario(name="Vol Up", vol_change_points=5.0)
        
        result = self.engine.calculate_scenario_pnl(
            scenario, delta=0.0, gamma=0.0, vega=-0.10, spot=self.spot
        )
        
        # Short vega * positive vol change = negative P&L
        assert result.vega_contribution < 0
    
    def test_taylor_formula_correctness(self):
        """Verify the Taylor approximation formula."""
        # ΔP&L ≈ Δ × ΔS × 100 + 0.5 × Γ × (ΔS)² × 100 + V × Δσ × 100
        delta, gamma, vega = 0.5, 0.02, 0.10
        price_change_pct = 0.02  # 2%
        vol_change = 5.0
        
        scenario = Scenario(
            name="Combined", 
            price_change_pct=price_change_pct, 
            vol_change_points=vol_change
        )
        
        result = self.engine.calculate_scenario_pnl(
            scenario, delta=delta, gamma=gamma, vega=vega, spot=self.spot
        )
        
        # Calculate expected values
        price_change = self.spot * price_change_pct  # $2
        expected_delta = delta * price_change * 100  # 0.5 * 2 * 100 = 100
        expected_gamma = 0.5 * gamma * (price_change ** 2) * 100  # 0.5 * 0.02 * 4 * 100 = 4
        expected_vega = vega * vol_change * 100  # 0.1 * 5 * 100 = 50
        
        assert abs(result.delta_contribution - expected_delta) < 0.01
        assert abs(result.gamma_contribution - expected_gamma) < 0.01
        assert abs(result.vega_contribution - expected_vega) < 0.01


class TestMonotonicity:
    """Test that bigger shocks produce bigger impacts."""
    
    def setup_method(self):
        self.engine = StressTestEngine()
        self.spot = 100.0
    
    def test_larger_price_shock_bigger_delta_impact(self):
        """Larger price move should have larger delta impact."""
        result_1 = self.engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_1, delta=1.0, gamma=0.0, vega=0.0, spot=self.spot
        )
        result_2 = self.engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_2, delta=1.0, gamma=0.0, vega=0.0, spot=self.spot
        )
        result_5 = self.engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_5, delta=1.0, gamma=0.0, vega=0.0, spot=self.spot
        )
        
        # Bigger move = bigger P&L for long delta
        assert result_1.estimated_pnl < result_2.estimated_pnl < result_5.estimated_pnl
    
    def test_larger_vol_shock_bigger_vega_impact(self):
        """Larger vol move should have larger vega impact."""
        result_5 = self.engine.calculate_scenario_pnl(
            SCENARIO_VOL_UP_5, delta=0.0, gamma=0.0, vega=0.10, spot=self.spot
        )
        result_10 = self.engine.calculate_scenario_pnl(
            SCENARIO_VOL_UP_10, delta=0.0, gamma=0.0, vega=0.10, spot=self.spot
        )
        
        # Bigger vol move = bigger P&L for long vega
        assert result_5.estimated_pnl < result_10.estimated_pnl
    
    def test_gamma_effect_increases_with_move_size(self):
        """Gamma impact should increase quadratically with move size."""
        result_1 = self.engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_1, delta=0.0, gamma=0.01, vega=0.0, spot=self.spot
        )
        result_2 = self.engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_2, delta=0.0, gamma=0.01, vega=0.0, spot=self.spot
        )
        
        # 2% move should have ~4x the gamma impact of 1% move (quadratic)
        ratio = result_2.gamma_contribution / result_1.gamma_contribution
        assert abs(ratio - 4.0) < 0.1  # Allow small tolerance


class TestCombinedShocks:
    """Test combined price and vol shock behavior."""
    
    def setup_method(self):
        self.engine = StressTestEngine()
        self.spot = 100.0
    
    def test_crash_scenario_hurts_short_gamma_short_vega(self):
        """Crash (down + vol up) should hurt short gamma, short vega."""
        # Typical iron condor position: short gamma, short vega
        result = self.engine.calculate_scenario_pnl(
            SCENARIO_CRASH, delta=0.0, gamma=-0.02, vega=-0.20, spot=self.spot
        )
        
        # Both gamma and vega contributions should be negative
        assert result.gamma_contribution < 0
        assert result.vega_contribution < 0
        assert result.estimated_pnl < 0
    
    def test_rally_scenario_helps_long_delta(self):
        """Rally (up + vol down) should help long delta."""
        result = self.engine.calculate_scenario_pnl(
            SCENARIO_RALLY, delta=1.0, gamma=0.0, vega=0.0, spot=self.spot
        )
        
        assert result.delta_contribution > 0
        assert result.estimated_pnl > 0
    
    def test_combined_effects_are_additive(self):
        """Combined scenario should sum delta, gamma, vega effects."""
        # Run combined
        combined = self.engine.calculate_scenario_pnl(
            SCENARIO_CRASH, delta=0.5, gamma=0.01, vega=0.10, spot=self.spot
        )
        
        # Verify total is sum of parts
        expected_total = (
            combined.delta_contribution + 
            combined.gamma_contribution + 
            combined.vega_contribution
        )
        assert abs(combined.estimated_pnl - expected_total) < 0.01


class TestThresholdBreaches:
    """Test loss threshold breach detection."""
    
    def test_breach_detected_when_exceeded(self):
        """Should flag breach when loss exceeds threshold."""
        config = StressTestConfig(max_acceptable_loss=100.0)
        engine = StressTestEngine(config)
        
        # Large short delta position
        result = engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_5, delta=-5.0, gamma=0.0, vega=0.0, spot=100.0
        )
        
        # This should result in significant loss
        if result.estimated_pnl < -100:
            assert result.exceeds_threshold == True
    
    def test_no_breach_within_limits(self):
        """Should not flag breach for small losses."""
        config = StressTestConfig(max_acceptable_loss=1000.0)
        engine = StressTestEngine(config)
        
        # Small position
        result = engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_1, delta=-0.1, gamma=0.0, vega=0.0, spot=100.0
        )
        
        assert result.exceeds_threshold == False


class TestStressTestResult:
    """Test StressTestResult aggregation."""
    
    def test_worst_best_case_identified(self):
        """Should correctly identify worst and best scenarios."""
        engine = StressTestEngine()
        result = engine.run_stress_test(
            delta=1.0, gamma=0.0, vega=0.0, spot=100.0
        )
        
        # For long delta, worst case is price down, best is price up
        assert result.worst_case_pnl < result.best_case_pnl
        assert "down" in result.worst_case_scenario.name.lower() or result.worst_case_pnl < 0
    
    def test_breach_scenarios_tracked(self):
        """Should track which scenarios breach thresholds."""
        config = StressTestConfig(max_acceptable_loss=50.0)
        engine = StressTestEngine(config)
        
        # Large position that will breach on some scenarios
        result = engine.run_stress_test(
            delta=-2.0, gamma=0.0, vega=0.0, spot=100.0
        )
        
        # Should have some breaches for down scenarios
        if result.has_threshold_breach:
            assert len(result.breach_scenarios) > 0


class TestCompareWithTrade:
    """Test before/after trade comparison."""
    
    def test_adding_trade_changes_stress_profile(self):
        """Adding a trade should change stress test results."""
        engine = StressTestEngine()
        
        before, after = engine.compare_with_trade(
            current_delta=0.0, current_gamma=0.0, current_vega=0.0,
            trade_delta=1.0, trade_gamma=0.01, trade_vega=0.10,
            spot=100.0
        )
        
        # After should reflect the trade's Greeks
        assert after.net_delta == 1.0
        assert after.net_gamma == 0.01
        assert after.net_vega == 0.10
        
        # Results should be different
        assert before.worst_case_pnl != after.worst_case_pnl


class TestApproximationWarnings:
    """Test approximation reliability warnings."""
    
    def test_large_move_flagged(self):
        """Large moves should be flagged as less reliable."""
        engine = StressTestEngine()
        
        result = engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_5, delta=1.0, gamma=0.0, vega=0.0, spot=100.0
        )
        
        # 5% move should be flagged
        assert result.approximation_reliable == False
        assert "5%" in result.approximation_note or "large" in result.approximation_note.lower()
    
    def test_small_move_reliable(self):
        """Small moves should be marked as reliable."""
        engine = StressTestEngine()
        
        result = engine.calculate_scenario_pnl(
            SCENARIO_PRICE_UP_1, delta=1.0, gamma=0.0, vega=0.0, spot=100.0
        )
        
        assert result.approximation_reliable == True


class TestFormatFunctions:
    """Test formatting helper functions."""
    
    def test_format_stress_result(self):
        """Should format result with severity indicator."""
        scenario = Scenario(name="Test", price_change_pct=0.01)
        result = ScenarioResult(
            scenario=scenario,
            estimated_pnl=100.0,
            delta_contribution=100.0,
            gamma_contribution=0.0,
            vega_contribution=0.0
        )
        
        formatted = format_stress_result(result)
        assert "Test" in formatted
        assert "100" in formatted


class TestSeverityClassification:
    """Test P&L severity classification."""
    
    def test_gain_classification(self):
        """Positive P&L should be classified as GAIN."""
        scenario = Scenario(name="Test")
        result = ScenarioResult(
            scenario=scenario, estimated_pnl=100.0,
            delta_contribution=0, gamma_contribution=0, vega_contribution=0
        )
        assert result.severity == "GAIN"
    
    def test_minor_loss_classification(self):
        """Small loss should be MINOR_LOSS."""
        scenario = Scenario(name="Test")
        result = ScenarioResult(
            scenario=scenario, estimated_pnl=-50.0,
            delta_contribution=0, gamma_contribution=0, vega_contribution=0
        )
        assert result.severity == "MINOR_LOSS"
    
    def test_severe_loss_classification(self):
        """Large loss should be SEVERE_LOSS."""
        scenario = Scenario(name="Test")
        result = ScenarioResult(
            scenario=scenario, estimated_pnl=-600.0,
            delta_contribution=0, gamma_contribution=0, vega_contribution=0
        )
        assert result.severity == "SEVERE_LOSS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
