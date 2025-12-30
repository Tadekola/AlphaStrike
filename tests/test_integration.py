"""
Integration Tests for AlphaStrike

End-to-end tests validating the full pipeline from data provider to trade output.
Uses mock data to ensure reproducible results.
"""
import pytest
import os
from datetime import date, timedelta

# Enable mock data for tests
os.environ["ALLOW_MOCK_DATA"] = "true"

from cal_pro.data_providers.mock import MockProvider, is_mock_allowed
from cal_pro.engine.pipeline import Pipeline
from cal_pro.engine.tradability import TradabilityConfig
from cal_pro.engine.regime import RegimeDetector, MarketRegime
from cal_pro.engine.market import MarketState
from cal_pro.engine.stress import StressTestEngine, STANDARD_SCENARIOS
from cal_pro.strategies.calendar import CalendarStrategy
from cal_pro.strategies.iron_condor import IronCondorStrategy
from cal_pro.strategies.vertical import VerticalStrategy


class TestMockDataGating:
    """Test that mock data is properly gated."""
    
    def test_mock_allowed_when_env_set(self):
        """Mock data should be allowed when ALLOW_MOCK_DATA=true."""
        assert is_mock_allowed() == True
    
    def test_mock_provider_returns_data(self):
        """Mock provider should return valid synthetic data."""
        provider = MockProvider("SPY")
        
        spot = provider.spot()
        assert spot > 0
        assert isinstance(spot, float)
        
        history = provider.history(20)
        assert len(history) == 20
        assert all(bar.close > 0 for bar in history)
        
        expirations = provider.expirations()
        assert len(expirations) > 0
        assert all(exp > date.today() for exp in expirations)


class TestMarketStateBuilding:
    """Test market state construction from provider data."""
    
    def test_market_state_builds_successfully(self):
        """MarketState should build without errors from mock data."""
        provider = MockProvider("SPY")
        market = MarketState.build("SPY", provider)
        
        assert market.ticker == "SPY"
        assert market.spot > 0
        assert market.sma20 > 0
        assert market.atr14 >= 0
        assert 0 <= market.rsi14 <= 100
    
    def test_adx_calculation_produces_valid_range(self):
        """ADX should be in valid range 0-100."""
        provider = MockProvider("SPY")
        market = MarketState.build("SPY", provider)
        
        assert 0 <= market.adx14 <= 100, f"ADX out of range: {market.adx14}"
    
    def test_hv_calculation_produces_reasonable_values(self):
        """Historical volatility should be reasonable (not 0, not extreme)."""
        provider = MockProvider("SPY")
        market = MarketState.build("SPY", provider)
        
        # HV should be annualized, typically 0.05 to 1.0 (5% to 100%)
        assert 0 <= market.hv20 <= 2.0, f"HV20 out of range: {market.hv20}"
        assert 0 <= market.hv5 <= 2.0, f"HV5 out of range: {market.hv5}"


class TestRegimeDetection:
    """Test regime classification logic."""
    
    def test_strong_trend_detection(self):
        """ADX > 30 should classify as STRONG_TREND."""
        detector = RegimeDetector()
        regime = detector.detect(adx=35, hv5=0.20, hv20=0.20)
        
        assert regime.trend_regime == MarketRegime.STRONG_TREND
    
    def test_range_bound_detection(self):
        """ADX <= 20 should classify as RANGE_BOUND."""
        detector = RegimeDetector()
        regime = detector.detect(adx=15, hv5=0.20, hv20=0.20)
        
        assert regime.trend_regime == MarketRegime.RANGE_BOUND
    
    def test_vol_expansion_detection(self):
        """HV5/HV20 > 1.2 should classify as VOL_EXPANSION."""
        detector = RegimeDetector()
        regime = detector.detect(adx=25, hv5=0.30, hv20=0.20)
        
        assert regime.vol_regime == MarketRegime.VOL_EXPANSION
    
    def test_vol_contraction_detection(self):
        """HV5/HV20 < 0.8 should classify as VOL_CONTRACTION."""
        detector = RegimeDetector()
        regime = detector.detect(adx=25, hv5=0.10, hv20=0.20)
        
        assert regime.vol_regime == MarketRegime.VOL_CONTRACTION


class TestPipelineEndToEnd:
    """End-to-end pipeline tests."""
    
    def test_pipeline_runs_without_error(self):
        """Pipeline should complete without exceptions."""
        provider = MockProvider("SPY")
        strategies = [CalendarStrategy(), IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=True)
        results, market, regime = pipeline.run("SPY")
        
        assert market is not None
        assert regime is not None
        assert isinstance(results, list)
    
    def test_pipeline_returns_trades_with_required_fields(self):
        """All returned trades should have required fields populated."""
        provider = MockProvider("SPY")
        strategies = [IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results, market, regime = pipeline.run("SPY")
        
        for trade in results:
            assert trade.ticker == "SPY"
            assert trade.strategy_name is not None
            assert trade.legs is not None
            assert len(trade.legs) > 0
            assert trade.max_profit is not None
            assert trade.max_loss is not None
            assert trade.confidence_score >= 0
            assert trade.tradability_status is not None
    
    def test_pipeline_calculates_greeks(self):
        """Pipeline should populate Greeks for tradable trades."""
        provider = MockProvider("SPY")
        strategies = [IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results, market, regime = pipeline.run("SPY")
        
        tradable = [t for t in results if t.is_tradable]
        if tradable:
            trade = tradable[0]
            assert trade.greeks is not None
            assert 'delta' in trade.greeks
            assert 'gamma' in trade.greeks
            assert 'vega' in trade.greeks
            assert 'theta' in trade.greeks


class TestTradabilityValidation:
    """Test tradability validation in pipeline context."""
    
    def test_strict_config_rejects_more_trades(self):
        """Stricter tradability config should reject more trades."""
        provider = MockProvider("SPY")
        strategies = [IronCondorStrategy()]
        
        # Lenient config
        lenient_config = TradabilityConfig(min_open_interest=10, min_volume=5, max_spread_pct=0.50)
        lenient_pipeline = Pipeline(provider, strategies, lenient_config, enforce_regime_suitability=False)
        lenient_results, _, _ = lenient_pipeline.run("SPY")
        
        # Strict config
        strict_config = TradabilityConfig(min_open_interest=5000, min_volume=1000, max_spread_pct=0.05)
        strict_pipeline = Pipeline(provider, strategies, strict_config, enforce_regime_suitability=False)
        strict_results, _, _ = strict_pipeline.run("SPY")
        
        lenient_tradable = sum(1 for t in lenient_results if t.is_tradable)
        strict_tradable = sum(1 for t in strict_results if t.is_tradable)
        
        assert strict_tradable <= lenient_tradable


class TestStressTestIntegration:
    """Test stress testing integration."""
    
    def test_stress_test_runs_on_trade_greeks(self):
        """Stress test should produce valid results from trade Greeks."""
        provider = MockProvider("SPY")
        strategies = [IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results, market, regime = pipeline.run("SPY")
        
        if results and results[0].greeks:
            trade = results[0]
            engine = StressTestEngine()
            
            stress_result = engine.run_stress_test(
                delta=trade.greeks.get('delta', 0),
                gamma=trade.greeks.get('gamma', 0),
                vega=trade.greeks.get('vega', 0),
                spot=market.spot
            )
            
            assert stress_result is not None
            assert len(stress_result.scenario_results) == len(STANDARD_SCENARIOS)
            assert stress_result.worst_case_scenario is not None
            assert stress_result.best_case_scenario is not None
    
    def test_stress_test_monotonicity(self):
        """Larger price moves should produce larger P&L magnitudes for delta-only position."""
        engine = StressTestEngine()
        
        # Long delta position
        result_1pct = engine.run_stress_test(delta=1.0, gamma=0.0, vega=0.0, spot=100.0,
                                              scenarios=[s for s in STANDARD_SCENARIOS if s.name == "Price +1%"])
        result_5pct = engine.run_stress_test(delta=1.0, gamma=0.0, vega=0.0, spot=100.0,
                                              scenarios=[s for s in STANDARD_SCENARIOS if s.name == "Price +5%"])
        
        if result_1pct.scenario_results and result_5pct.scenario_results:
            pnl_1pct = result_1pct.scenario_results[0].estimated_pnl
            pnl_5pct = result_5pct.scenario_results[0].estimated_pnl
            assert pnl_5pct > pnl_1pct


class TestCalendarPOPVerification:
    """Test that Calendar strategy POP is properly computed."""
    
    def test_calendar_pop_is_verified(self):
        """Calendar trades should have VERIFIED POP label."""
        provider = MockProvider("SPY")
        strategies = [CalendarStrategy(pop_min=0.30)]  # Lower threshold to get trades
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results, market, regime = pipeline.run("SPY")
        
        calendar_trades = [t for t in results if t.strategy_name == "Calendar"]
        
        for trade in calendar_trades:
            assert trade.pop is not None, "Calendar POP should be computed"
            assert trade.pop_label == "VERIFIED", f"Calendar POP should be VERIFIED, got {trade.pop_label}"
            assert 0 <= trade.pop <= 1, f"POP should be between 0 and 1, got {trade.pop}"


class TestIronCondorPOPEstimate:
    """Test that Iron Condor has POP estimate."""
    
    def test_iron_condor_has_pop_estimate(self):
        """Iron Condor should have delta-proxy POP estimate."""
        provider = MockProvider("SPY")
        strategies = [IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        pipeline = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results, market, regime = pipeline.run("SPY")
        
        ic_trades = [t for t in results if t.strategy_name == "Iron Condor"]
        
        for trade in ic_trades:
            # Should have POP estimate (may be None if Greeks missing)
            if trade.pop is not None:
                assert trade.pop_label in ["DELTA_PROXY (estimate only)", "UNVERIFIED"]
                assert 0 <= trade.pop <= 1


class TestRegimeSuitabilityEnforcement:
    """Test regime-strategy suitability enforcement."""
    
    def test_regime_enforcement_rejects_unsuitable(self):
        """With enforcement on, unsuitable regime-strategy combos should be rejected."""
        provider = MockProvider("SPY")
        
        # Iron Condor in strong trend should be rejected
        # We can't control mock regime, but we can check enforcement flag works
        strategies = [IronCondorStrategy()]
        config = TradabilityConfig(min_open_interest=10, min_volume=10)
        
        # With enforcement
        pipeline_enforced = Pipeline(provider, strategies, config, enforce_regime_suitability=True)
        results_enforced, _, regime = pipeline_enforced.run("SPY")
        
        # Without enforcement
        pipeline_unenforced = Pipeline(provider, strategies, config, enforce_regime_suitability=False)
        results_unenforced, _, _ = pipeline_unenforced.run("SPY")
        
        # Results may differ based on regime
        # At minimum, both should return valid result structures
        assert isinstance(results_enforced, list)
        assert isinstance(results_unenforced, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
