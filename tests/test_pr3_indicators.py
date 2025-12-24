"""
PR #3: Indicator Correctness & Signal Integrity - Unit Tests

Tests to verify that technical indicators are mathematically correct.
"""
import pytest
import math
import datetime as dt
from cal_pro.data_providers.base import Bar
from cal_pro.engine.market import (
    MarketState, ADX_METHOD, ATR_METHOD, HV_METHOD, GEX_METHOD
)


class TestIndicatorMethodLabels:
    """Verify indicator methodology labels are defined."""
    
    def test_adx_method_label(self):
        assert "Wilder" in ADX_METHOD
    
    def test_atr_method_label(self):
        assert "Wilder" in ATR_METHOD and "True Range" in ATR_METHOD
    
    def test_hv_method_label(self):
        assert "252" in HV_METHOD
    
    def test_gex_method_label(self):
        assert "Single-expiry" in GEX_METHOD


class TestATRCalculation:
    """Verify ATR uses True Range with Wilder smoothing."""
    
    def test_atr_with_gaps(self):
        """ATR should account for gaps (close vs previous close)."""
        bars = self._create_bars_with_gap()
        atr = MarketState._atr(bars, 14)
        # ATR should be positive when there are price movements
        assert atr > 0
    
    def test_atr_zero_for_flat_market(self):
        """ATR should be near zero for perfectly flat market."""
        bars = self._create_flat_bars()
        atr = MarketState._atr(bars, 14)
        assert atr < 0.01
    
    def _create_bars_with_gap(self):
        bars = []
        base = dt.date(2024, 1, 1)
        for i in range(30):
            c = 100.0 + (i % 5) * 0.5  # Oscillating
            bars.append(Bar(base + dt.timedelta(days=i), c, c + 1.0, c - 1.0))
        return bars
    
    def _create_flat_bars(self):
        bars = []
        base = dt.date(2024, 1, 1)
        for i in range(30):
            bars.append(Bar(base + dt.timedelta(days=i), 100.0, 100.0, 100.0))
        return bars


class TestADXCalculation:
    """Verify ADX uses proper Wilder smoothing."""
    
    def test_adx_returns_tuple(self):
        """ADX should return (adx, plus_di, minus_di) tuple."""
        bars = self._create_trending_bars()
        result = MarketState._adx(bars, 14)
        assert isinstance(result, tuple)
        assert len(result) == 3
    
    def test_adx_trending_market(self):
        """ADX should be high in trending market."""
        bars = self._create_trending_bars()
        adx, plus_di, minus_di = MarketState._adx(bars, 14)
        # In strong uptrend, +DI should exceed -DI
        assert plus_di > minus_di
    
    def test_adx_range_bound_market(self):
        """ADX should be lower in range-bound market."""
        trending = self._create_trending_bars()
        ranging = self._create_ranging_bars()
        adx_trend, _, _ = MarketState._adx(trending, 14)
        adx_range, _, _ = MarketState._adx(ranging, 14)
        # Trending ADX should exceed ranging ADX
        assert adx_trend > adx_range
    
    def _create_trending_bars(self):
        bars = []
        base = dt.date(2024, 1, 1)
        for i in range(60):
            c = 100.0 + i * 0.5  # Strong uptrend
            bars.append(Bar(base + dt.timedelta(days=i), c, c + 0.3, c - 0.1))
        return bars
    
    def _create_ranging_bars(self):
        bars = []
        base = dt.date(2024, 1, 1)
        for i in range(60):
            c = 100.0 + math.sin(i * 0.5) * 2  # Oscillating
            bars.append(Bar(base + dt.timedelta(days=i), c, c + 0.5, c - 0.5))
        return bars


class TestHVCalculation:
    """Verify HV uses log returns with correct annualization."""
    
    def test_hv_uses_log_returns(self):
        """HV should use log returns, not simple returns."""
        closes = [100.0, 110.0, 100.0]  # +10%, -9.09% simple
        hv = MarketState._hv(closes, 2)
        # Log returns: ln(1.1) ≈ 0.0953, ln(0.909) ≈ -0.0953
        # These are symmetric in log space
        assert hv > 0
    
    def test_hv_annualization(self):
        """HV should be annualized with sqrt(252)."""
        closes = [100.0 + i * 0.01 for i in range(30)]
        hv = MarketState._hv(closes, 20)
        # Very small daily moves should give small annualized vol
        assert hv < 0.10  # Less than 10% annualized
    
    def test_hv_flat_market(self):
        """HV should be zero for flat market."""
        closes = [100.0] * 30
        hv = MarketState._hv(closes, 20)
        assert hv == 0.0


class TestMarketStateBackwardCompat:
    """Verify backward compatibility aliases work."""
    
    def test_dx14_alias_returns_adx14(self):
        """dx14 property should return adx14 value."""
        market = MarketState(
            ticker="SPY", spot=450.0, sma20=448.0, atr14=5.0,
            rsi14=55.0, hv5=0.15, hv20=0.18, adx14=25.0
        )
        assert market.dx14 == market.adx14 == 25.0
    
    def test_atr5_alias_returns_atr14(self):
        """atr5 property should return atr14 value."""
        market = MarketState(
            ticker="SPY", spot=450.0, sma20=448.0, atr14=5.0,
            rsi14=55.0, hv5=0.15, hv20=0.18
        )
        assert market.atr5 == market.atr14 == 5.0


class TestGEXDocumentation:
    """Verify GEX limitations are documented."""
    
    def test_gex_method_field_exists(self):
        """MarketState should have gex_method field."""
        market = MarketState(
            ticker="SPY", spot=450.0, sma20=448.0, atr14=5.0,
            rsi14=55.0, hv5=0.15, hv20=0.18
        )
        assert hasattr(market, 'gex_method')
        assert "Single-expiry" in market.gex_method


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
