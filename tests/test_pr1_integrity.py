"""
PR #1: Turn Off Lies - Unit Tests

Tests to verify that misleading metrics have been removed and safety gates are in place.
"""
import os
import pytest
from unittest.mock import patch

# Test imports
from cal_pro.engine.base_strategy import (
    CandidateTrade, Leg, 
    POP_LABEL_VERIFIED, POP_LABEL_UNVERIFIED, POP_LABEL_DELTA_PROXY
)
from cal_pro.engine.scoring import (
    Scorer, CONFIDENCE_INSUFFICIENT_DATA, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW
)
from cal_pro.engine.market import MarketState, IV_RANK_NOT_IMPLEMENTED
from cal_pro.data_providers.mock import is_mock_allowed, ALLOW_MOCK_DATA_ENV
import datetime as dt


class TestPOPLabels:
    """Verify POP labels are correctly defined and used."""
    
    def test_pop_labels_exist(self):
        """POP label constants should exist."""
        assert POP_LABEL_VERIFIED == "VERIFIED"
        assert POP_LABEL_UNVERIFIED == "UNVERIFIED"
        assert POP_LABEL_DELTA_PROXY == "DELTA_PROXY (estimate only)"
    
    def test_candidate_trade_default_pop_label(self):
        """CandidateTrade should default to UNVERIFIED pop_label."""
        trade = CandidateTrade(
            strategy_name="Test",
            ticker="SPY",
            legs=[],
            debit=100.0,
            max_loss=100.0,
            max_profit=50.0,
            breakevens=[100.0],
            pop=None  # Unverified POP
        )
        assert trade.pop_label == POP_LABEL_UNVERIFIED


class TestScoringWithNonePOP:
    """Verify scoring handles None POP conservatively."""
    
    def setup_method(self):
        self.scorer = Scorer()
        self.market = MarketState(
            ticker="SPY",
            spot=450.0,
            sma20=448.0,
            atr14=5.0,
            rsi14=55.0,
            hv5=0.15,
            hv20=0.18
        )
    
    def test_scoring_with_none_pop_returns_conservative_baseline(self):
        """When POP is None, score should be conservative (35.0)."""
        trade = CandidateTrade(
            strategy_name="Test",
            ticker="SPY",
            legs=[],
            debit=100.0,
            max_loss=100.0,
            max_profit=50.0,
            breakevens=[100.0],
            pop=None,
            pop_label=POP_LABEL_UNVERIFIED
        )
        
        self.scorer.score(trade, self.market)
        
        assert trade.confidence_score == 35.0
        assert trade.confidence_label == CONFIDENCE_INSUFFICIENT_DATA
        assert "UNVERIFIED" in trade.metrics.get('score_basis', '')
    
    def test_scoring_with_verified_pop_uses_pop(self):
        """When POP is verified, score should use actual POP value."""
        trade = CandidateTrade(
            strategy_name="Test",
            ticker="SPY",
            legs=[],
            debit=100.0,
            max_loss=100.0,
            max_profit=50.0,
            breakevens=[100.0],
            pop=0.65,  # 65% POP
            pop_label=POP_LABEL_VERIFIED
        )
        
        self.scorer.score(trade, self.market)
        
        # Score should be 50 + (0.65 - 0.5) * 100 = 65
        assert trade.confidence_score == 65.0
        assert trade.confidence_label == CONFIDENCE_MEDIUM
        assert "VERIFIED" in trade.metrics.get('score_basis', '')
    
    def test_scoring_with_high_verified_pop(self):
        """High verified POP should result in High confidence."""
        trade = CandidateTrade(
            strategy_name="Test",
            ticker="SPY",
            legs=[],
            debit=100.0,
            max_loss=100.0,
            max_profit=50.0,
            breakevens=[100.0],
            pop=0.85,  # 85% POP
            pop_label=POP_LABEL_VERIFIED
        )
        
        self.scorer.score(trade, self.market)
        
        # Score should be 50 + (0.85 - 0.5) * 100 = 85
        assert trade.confidence_score == 85.0
        assert trade.confidence_label == CONFIDENCE_HIGH
    
    def test_l_score_is_zero_not_fake_50(self):
        """L-score should be 0 (not implemented), not fake 50."""
        trade = CandidateTrade(
            strategy_name="Test",
            ticker="SPY",
            legs=[],
            debit=100.0,
            max_loss=100.0,
            max_profit=50.0,
            breakevens=[100.0],
            pop=0.60,
            pop_label=POP_LABEL_VERIFIED
        )
        
        self.scorer.score(trade, self.market)
        
        assert trade.l_score == 0.0  # Not the fake 50.0


class TestMockDataGating:
    """Verify mock data is gated by environment variable."""
    
    def test_mock_not_allowed_by_default(self):
        """Mock data should not be allowed without env var."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove ALLOW_MOCK_DATA if it exists
            os.environ.pop(ALLOW_MOCK_DATA_ENV, None)
            assert is_mock_allowed() == False
    
    def test_mock_allowed_when_env_set_true(self):
        """Mock data should be allowed when ALLOW_MOCK_DATA=true."""
        with patch.dict(os.environ, {ALLOW_MOCK_DATA_ENV: "true"}):
            assert is_mock_allowed() == True
    
    def test_mock_allowed_case_insensitive(self):
        """ALLOW_MOCK_DATA should be case-insensitive."""
        with patch.dict(os.environ, {ALLOW_MOCK_DATA_ENV: "TRUE"}):
            assert is_mock_allowed() == True
        with patch.dict(os.environ, {ALLOW_MOCK_DATA_ENV: "True"}):
            assert is_mock_allowed() == True
    
    def test_mock_not_allowed_with_false(self):
        """Mock should not be allowed when ALLOW_MOCK_DATA=false."""
        with patch.dict(os.environ, {ALLOW_MOCK_DATA_ENV: "false"}):
            assert is_mock_allowed() == False


class TestIndicatorNaming:
    """Verify indicators are correctly named and implemented."""
    
    def test_market_state_has_true_adx(self):
        """MarketState should use true ADX (Wilder-smoothed)."""
        market = MarketState(
            ticker="SPY",
            spot=450.0,
            sma20=448.0,
            atr14=5.0,  # True ATR
            rsi14=55.0,
            hv5=0.15,
            hv20=0.18,
            adx14=25.0  # True ADX now
        )
        
        assert market.adx14 == 25.0
        # Backward compat alias should still work
        assert market.dx14 == 25.0
    
    def test_iv_rank_is_none_not_fake_50(self):
        """IV Rank should be None (not implemented), not fake 50."""
        market = MarketState(
            ticker="SPY",
            spot=450.0,
            sma20=448.0,
            atr14=5.0,
            rsi14=55.0,
            hv5=0.15,
            hv20=0.18
        )
        
        assert market.iv_rank is None
        assert market.iv_rank_label == IV_RANK_NOT_IMPLEMENTED


class TestIVRankNotImplemented:
    """Verify IV Rank is properly marked as not implemented."""
    
    def test_iv_rank_label_constant(self):
        """IV Rank label constant should be defined."""
        assert IV_RANK_NOT_IMPLEMENTED == "NOT IMPLEMENTED (FREE DATA LIMITATION)"
    
    def test_market_state_iv_rank_defaults_to_none(self):
        """MarketState.iv_rank should default to None."""
        market = MarketState(
            ticker="SPY",
            spot=450.0,
            sma20=448.0,
            atr14=5.0,
            rsi14=55.0,
            hv5=0.15,
            hv20=0.18
        )
        
        assert market.iv_rank is None
        assert "NOT IMPLEMENTED" in market.iv_rank_label


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
