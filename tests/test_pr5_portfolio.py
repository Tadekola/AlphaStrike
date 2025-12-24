"""
PR #5: Portfolio Greeks & Exposure Guardrails - Unit Tests

Tests for aggregate Greeks calculation, exposure thresholds, and concentration detection.
"""
import pytest
from cal_pro.engine.portfolio import (
    LegGreeks, PositionGreeks, PortfolioGreeks,
    PortfolioManager, ExposureThresholds, ExposureCheck, ExposureStatus,
    ConcentrationAnalysis, GreeksSource,
    format_greeks_summary, format_exposure_change
)


class TestLegGreeks:
    """Test LegGreeks dataclass operations."""
    
    def test_scale_greeks(self):
        """Scaling should multiply all Greeks."""
        leg = LegGreeks(delta=0.5, gamma=0.02, vega=0.10, theta=-0.05)
        scaled = leg.scale(2.0)
        
        assert scaled.delta == 1.0
        assert scaled.gamma == 0.04
        assert scaled.vega == 0.20
        assert scaled.theta == -0.10
    
    def test_add_greeks(self):
        """Adding two LegGreeks should sum all values."""
        leg1 = LegGreeks(delta=0.5, gamma=0.02, vega=0.10, theta=-0.05)
        leg2 = LegGreeks(delta=-0.3, gamma=0.01, vega=-0.05, theta=-0.03)
        result = leg1 + leg2
        
        assert abs(result.delta - 0.2) < 0.001
        assert abs(result.gamma - 0.03) < 0.001
        assert abs(result.vega - 0.05) < 0.001
        assert abs(result.theta - (-0.08)) < 0.001


class TestPositionGreeks:
    """Test position-level Greeks."""
    
    def test_position_greeks_add(self):
        """Adding two PositionGreeks should sum values."""
        pos1 = PositionGreeks(net_delta=0.5, net_gamma=0.02, net_vega=10.0, net_theta=-5.0)
        pos2 = PositionGreeks(net_delta=-0.3, net_gamma=-0.01, net_vega=-5.0, net_theta=-3.0)
        result = pos1 + pos2
        
        assert abs(result.net_delta - 0.2) < 0.001
        assert abs(result.net_gamma - 0.01) < 0.001
        assert abs(result.net_vega - 5.0) < 0.001


class TestPortfolioGreeks:
    """Test portfolio-level Greeks aggregation."""
    
    def test_from_positions_empty(self):
        """Empty positions should return zero Greeks."""
        portfolio = PortfolioGreeks.from_positions([])
        
        assert portfolio.net_delta == 0.0
        assert portfolio.net_gamma == 0.0
        assert portfolio.net_vega == 0.0
        assert portfolio.num_positions == 0
    
    def test_from_positions_aggregates(self):
        """Portfolio should aggregate all positions."""
        positions = [
            PositionGreeks(net_delta=0.5, net_gamma=0.02, net_vega=10.0, net_theta=-5.0),
            PositionGreeks(net_delta=-0.3, net_gamma=-0.01, net_vega=-5.0, net_theta=-3.0),
            PositionGreeks(net_delta=0.2, net_gamma=0.01, net_vega=3.0, net_theta=-2.0),
        ]
        portfolio = PortfolioGreeks.from_positions(positions)
        
        assert abs(portfolio.net_delta - 0.4) < 0.001
        assert abs(portfolio.net_gamma - 0.02) < 0.001
        assert abs(portfolio.net_vega - 8.0) < 0.001
        assert portfolio.num_positions == 3
    
    def test_dollar_exposure_with_spot(self):
        """Dollar exposure should be calculated when spot is provided."""
        positions = [PositionGreeks(net_delta=1.0, net_gamma=0.01, net_vega=10.0)]
        portfolio = PortfolioGreeks.from_positions(positions, spot=100.0)
        
        # Delta dollars = delta * spot * 100
        assert portfolio.delta_dollars == 10000.0


class TestExposureThresholds:
    """Test exposure threshold configuration."""
    
    def test_default_thresholds(self):
        """Default thresholds should be conservative."""
        thresholds = ExposureThresholds()
        
        assert thresholds.max_net_delta == 50.0
        assert thresholds.warn_net_delta == 30.0
        assert thresholds.max_short_gamma == 5.0
        assert thresholds.block_on_exceed == False
    
    def test_custom_thresholds(self):
        """Custom thresholds should be respected."""
        thresholds = ExposureThresholds(
            max_net_delta=100.0,
            warn_net_delta=50.0,
            block_on_exceed=True
        )
        
        assert thresholds.max_net_delta == 100.0
        assert thresholds.block_on_exceed == True


class TestPortfolioManagerExposure:
    """Test exposure checking logic."""
    
    def setup_method(self):
        self.manager = PortfolioManager()
    
    def test_safe_exposure(self):
        """Small positions should be safe."""
        self.manager.add_position(PositionGreeks(net_delta=5.0, net_gamma=0.5, net_vega=50.0))
        check = self.manager.check_exposure()
        
        assert check.status == ExposureStatus.SAFE
        assert len(check.warnings) == 0
    
    def test_delta_warning(self):
        """Delta exceeding warn threshold should generate warning."""
        self.manager.add_position(PositionGreeks(net_delta=35.0))
        check = self.manager.check_exposure()
        
        assert check.delta_status == ExposureStatus.WARNING
        assert any("delta" in w.lower() for w in check.warnings)
    
    def test_delta_exceed_max(self):
        """Delta exceeding max should generate warning (not block by default)."""
        self.manager.add_position(PositionGreeks(net_delta=60.0))
        check = self.manager.check_exposure()
        
        assert check.delta_status == ExposureStatus.WARNING
        assert any("delta" in w.lower() for w in check.warnings)
    
    def test_delta_exceed_with_blocking(self):
        """Delta exceeding max with blocking enabled should block."""
        thresholds = ExposureThresholds(block_on_exceed=True)
        manager = PortfolioManager(thresholds)
        manager.add_position(PositionGreeks(net_delta=60.0))
        check = manager.check_exposure()
        
        assert check.delta_status == ExposureStatus.BLOCKED
        assert check.is_blocked == True
        assert len(check.blocks) > 0
    
    def test_short_gamma_warning(self):
        """Short gamma exceeding threshold should warn."""
        self.manager.add_position(PositionGreeks(net_gamma=-3.0))
        check = self.manager.check_exposure()
        
        assert check.gamma_status == ExposureStatus.WARNING
        assert any("gamma" in w.lower() for w in check.warnings)
    
    def test_vega_warning(self):
        """High vega exposure should warn."""
        self.manager.add_position(PositionGreeks(net_vega=350.0))
        check = self.manager.check_exposure()
        
        assert check.vega_status == ExposureStatus.WARNING


class TestExposureWithTrade:
    """Test before/after exposure checking."""
    
    def setup_method(self):
        self.manager = PortfolioManager()
        # Start with existing position
        self.manager.add_position(PositionGreeks(net_delta=20.0, net_gamma=1.0, net_vega=100.0))
    
    def test_check_with_trade(self):
        """Should return before and after Greeks."""
        new_trade = PositionGreeks(net_delta=15.0, net_gamma=0.5, net_vega=50.0)
        check, before, after = self.manager.check_exposure_with_trade(new_trade)
        
        assert before.net_delta == 20.0
        assert after.net_delta == 35.0  # 20 + 15
        assert after.net_gamma == 1.5   # 1 + 0.5
    
    def test_trade_triggers_warning(self):
        """Trade that pushes exposure over threshold should warn."""
        # Add trade that pushes delta over warning threshold
        new_trade = PositionGreeks(net_delta=15.0)  # Total: 35 > 30 warn threshold
        check, before, after = self.manager.check_exposure_with_trade(new_trade)
        
        assert check.has_warnings == True


class TestConcentrationDetection:
    """Test concentration risk detection."""
    
    def setup_method(self):
        self.manager = PortfolioManager()
    
    def test_directional_stacking_detection(self):
        """Should detect multiple positions with same delta sign."""
        # Add 3 long delta positions
        for _ in range(3):
            self.manager.add_position(PositionGreeks(net_delta=5.0))
        
        analysis = self.manager.analyze_concentration()
        
        assert analysis.long_delta_count == 3
        assert analysis.directional_bias == "LONG_BIASED"
        assert any("directional" in w.lower() for w in analysis.warnings)
    
    def test_short_vega_stacking_detection(self):
        """Should detect multiple short vega positions."""
        for _ in range(3):
            self.manager.add_position(PositionGreeks(net_vega=-10.0))
        
        analysis = self.manager.analyze_concentration()
        
        assert analysis.short_vega_count == 3
        assert analysis.vol_bias == "SHORT_VOL"
        assert any("vol" in w.lower() for w in analysis.warnings)
    
    def test_short_gamma_concentration(self):
        """Should warn on short gamma concentration."""
        for _ in range(2):
            self.manager.add_position(PositionGreeks(net_gamma=-0.5))
        
        analysis = self.manager.analyze_concentration()
        
        assert analysis.short_gamma_count == 2
        assert any("gamma" in w.lower() for w in analysis.warnings)
    
    def test_balanced_portfolio(self):
        """Balanced portfolio should have neutral bias."""
        self.manager.add_position(PositionGreeks(net_delta=5.0, net_vega=10.0))
        self.manager.add_position(PositionGreeks(net_delta=-5.0, net_vega=-10.0))
        
        analysis = self.manager.analyze_concentration()
        
        assert analysis.directional_bias == "NEUTRAL"
        assert analysis.vol_bias == "NEUTRAL"
        assert len(analysis.warnings) == 0


class TestFormatFunctions:
    """Test formatting helper functions."""
    
    def test_format_greeks_summary(self):
        """Should format Greeks in readable string."""
        greeks = PortfolioGreeks(net_delta=0.5, net_gamma=0.02, net_vega=10.0, net_theta=-5.0)
        summary = format_greeks_summary(greeks)
        
        assert "Δ=" in summary
        assert "Γ=" in summary
        assert "V=" in summary
        assert "Θ=" in summary
    
    def test_format_exposure_change(self):
        """Should format before/after change."""
        before = PortfolioGreeks(net_delta=10.0, net_gamma=0.5)
        after = PortfolioGreeks(net_delta=20.0, net_gamma=1.0)
        
        change = format_exposure_change(before, after)
        
        assert "→" in change['delta']
        assert "10" in change['delta'] and "20" in change['delta']


class TestGreeksSource:
    """Test Greeks source tracking."""
    
    def test_broker_source(self):
        """Broker source should be tracked."""
        leg = LegGreeks(delta=0.5, source=GreeksSource.BROKER)
        assert leg.source == GreeksSource.BROKER
    
    def test_bs_fallback_source(self):
        """Black-Scholes fallback should be clearly labeled."""
        leg = LegGreeks(delta=0.5, source=GreeksSource.BLACK_SCHOLES)
        assert leg.source == GreeksSource.BLACK_SCHOLES
        assert leg.source.value == "BS_CALC"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
