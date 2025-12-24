"""
PR #2: Trade Realism & Data Robustness - Unit Tests

Tests to verify tradability validation, conservative pricing, and provider robustness.
"""
import pytest
from unittest.mock import patch, MagicMock
import time

from cal_pro.data_providers.base import OptionQuote
from cal_pro.engine.tradability import (
    TradabilityValidator,
    TradabilityConfig,
    TradabilityStatus,
    LegValidation,
    TradeValidation,
    get_conservative_price,
    validate_option_for_trade
)


class TestOptionQuoteProperties:
    """Test OptionQuote spread calculation properties."""
    
    def test_spread_calculation(self):
        """Spread should be ask - bid."""
        quote = OptionQuote(
            symbol="SPY240119C00450000",
            strike=450.0,
            right="call",
            mid=2.50,
            iv=0.20,
            bid=2.40,
            ask=2.60,
            open_interest=1000,
            volume=500
        )
        assert abs(quote.spread - 0.20) < 0.001  # Floating point tolerance
        assert abs(quote.spread_pct - 0.08) < 0.01  # 8% spread
    
    def test_spread_with_zero_bid(self):
        """Spread should be inf when bid is zero."""
        quote = OptionQuote(
            symbol="SPY240119C00450000",
            strike=450.0,
            right="call",
            mid=2.50,
            iv=0.20,
            bid=0.0,
            ask=2.60,
            open_interest=100,
            volume=50
        )
        assert quote.spread == float('inf')
        assert quote.is_quoted == False
    
    def test_is_quoted_with_valid_bid_ask(self):
        """is_quoted should be True when both bid and ask > 0."""
        quote = OptionQuote(
            symbol="SPY240119C00450000",
            strike=450.0,
            right="call",
            mid=2.50,
            iv=0.20,
            bid=2.40,
            ask=2.60,
            open_interest=1000,
            volume=500
        )
        assert quote.is_quoted == True


class TestTradabilityValidatorRejections:
    """Test that validator correctly rejects untradable options."""
    
    def setup_method(self):
        self.config = TradabilityConfig(
            min_open_interest=250,
            min_volume=50,
            max_spread_pct=0.15,
            reject_spread_pct=0.25
        )
        self.validator = TradabilityValidator(self.config)
    
    def test_reject_zero_bid(self):
        """Should reject option with zero bid."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=0.0,
            ask=1.0,
            open_interest=1000,
            volume=500
        )
        
        result = self.validator.validate_leg(quote, "sell")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_ZERO_BID
        assert "Zero bid" in result.rejection_reason
    
    def test_reject_zero_ask(self):
        """Should reject option with zero ask."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=1.0,
            ask=0.0,
            open_interest=1000,
            volume=500
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_ZERO_ASK
    
    def test_reject_low_open_interest(self):
        """Should reject option with OI below threshold."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=0.95,
            ask=1.05,
            open_interest=100,  # Below 250 threshold
            volume=500
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_LOW_OI
        assert "OI=100" in result.rejection_reason
    
    def test_reject_low_volume(self):
        """Should reject option with volume below threshold."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=0.95,
            ask=1.05,
            open_interest=500,
            volume=20  # Below 50 threshold
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_LOW_VOLUME
        assert "Volume=20" in result.rejection_reason
    
    def test_reject_wide_spread(self):
        """Should reject option with spread exceeding threshold."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=0.80,
            ask=1.20,  # 40% spread
            open_interest=500,
            volume=100
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_WIDE_SPREAD
    
    def test_accept_tradable_option(self):
        """Should accept option meeting all criteria."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=1.0,
            iv=0.20,
            bid=0.95,
            ask=1.05,  # 10% spread - OK
            open_interest=500,  # Above 250
            volume=100  # Above 50
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        assert result.is_valid == True
        assert result.status == TradabilityStatus.TRADABLE
        assert result.entry_price > 0


class TestConservativePricing:
    """Test conservative pricing model."""
    
    def setup_method(self):
        self.config = TradabilityConfig(
            base_slippage_pct=0.01,
            spread_slippage_multiplier=0.5
        )
        self.validator = TradabilityValidator(self.config)
    
    def test_buy_uses_ask_plus_slippage(self):
        """Buying should use ask + slippage (worst case for buyer)."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=2.00,
            iv=0.20,
            bid=1.90,
            ask=2.10,
            open_interest=500,
            volume=100
        )
        
        result = self.validator.validate_leg(quote, "buy")
        
        # Entry price should be > ask
        assert result.entry_price > quote.ask
        assert result.slippage > 0
    
    def test_sell_uses_bid_minus_slippage(self):
        """Selling should use bid - slippage (worst case for seller)."""
        quote = OptionQuote(
            symbol="TEST",
            strike=100.0,
            right="call",
            mid=2.00,
            iv=0.20,
            bid=1.90,
            ask=2.10,
            open_interest=500,
            volume=100
        )
        
        result = self.validator.validate_leg(quote, "sell")
        
        # Entry price should be < bid
        assert result.entry_price < quote.bid
        assert result.slippage > 0
    
    def test_wider_spread_means_more_slippage(self):
        """Wider spreads should result in more slippage."""
        # Use a config with higher spread tolerance so both pass
        config = TradabilityConfig(
            base_slippage_pct=0.01,
            spread_slippage_multiplier=0.5,
            max_spread_pct=0.25  # Allow up to 25% spread
        )
        validator = TradabilityValidator(config)
        
        narrow_spread = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.95, ask=2.05, open_interest=500, volume=100  # 5% spread
        )
        
        wide_spread = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.80, ask=2.20, open_interest=500, volume=100  # 20% spread
        )
        
        narrow_result = validator.validate_leg(narrow_spread, "buy")
        wide_result = validator.validate_leg(wide_spread, "buy")
        
        # Both should be valid
        assert narrow_result.is_valid == True
        assert wide_result.is_valid == True
        # Wide spread should have more slippage
        assert wide_result.slippage > narrow_result.slippage


class TestTradeValidation:
    """Test full trade validation with multiple legs."""
    
    def setup_method(self):
        self.config = TradabilityConfig(
            min_open_interest=100,
            min_volume=25,
            max_spread_pct=0.20
        )
        self.validator = TradabilityValidator(self.config)
    
    def test_trade_rejected_if_any_leg_fails(self):
        """Entire trade should be rejected if any leg fails validation."""
        good_quote = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.90, ask=2.10, open_interest=500, volume=100
        )
        
        bad_quote = OptionQuote(
            symbol="TEST", strike=105.0, right="call", mid=1.00, iv=0.20,
            bid=0.0, ask=1.00, open_interest=500, volume=100  # Zero bid
        )
        
        legs = [
            (good_quote, "buy", 1),
            (bad_quote, "sell", 1)
        ]
        
        result = self.validator.validate_trade(legs)
        
        assert result.is_tradable == False
        assert len(result.rejection_reasons) > 0
    
    def test_trade_accepted_if_all_legs_pass(self):
        """Trade should be accepted if all legs pass validation."""
        # Use narrower spreads that pass the 20% threshold
        quote1 = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.85, ask=2.15, open_interest=500, volume=100  # 15% spread
        )
        
        quote2 = OptionQuote(
            symbol="TEST", strike=105.0, right="call", mid=1.00, iv=0.20,
            bid=0.92, ask=1.08, open_interest=500, volume=100  # 16% spread
        )
        
        legs = [
            (quote1, "buy", 1),
            (quote2, "sell", 1)
        ]
        
        result = self.validator.validate_trade(legs)
        
        assert result.is_tradable == True
        assert result.status == TradabilityStatus.TRADABLE
        assert len(result.rejection_reasons) == 0


class TestProviderCaching:
    """Test provider caching functionality."""
    
    def test_cache_clear_function_exists(self):
        """clear_cache function should exist."""
        from cal_pro.data_providers.tradier import clear_cache
        # Should not raise
        clear_cache()


class TestConfigurableThresholds:
    """Test that thresholds are configurable."""
    
    def test_custom_oi_threshold(self):
        """Should use custom OI threshold."""
        config = TradabilityConfig(min_open_interest=1000)
        validator = TradabilityValidator(config)
        
        quote = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.90, ask=2.10, open_interest=500, volume=100
        )
        
        result = validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_LOW_OI
    
    def test_custom_volume_threshold(self):
        """Should use custom volume threshold."""
        config = TradabilityConfig(min_volume=200)
        validator = TradabilityValidator(config)
        
        quote = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.90, ask=2.10, open_interest=500, volume=100
        )
        
        result = validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_LOW_VOLUME
    
    def test_custom_spread_threshold(self):
        """Should use custom spread threshold."""
        config = TradabilityConfig(max_spread_pct=0.05)  # 5%
        validator = TradabilityValidator(config)
        
        quote = OptionQuote(
            symbol="TEST", strike=100.0, right="call", mid=2.00, iv=0.20,
            bid=1.90, ask=2.10, open_interest=500, volume=100  # 10% spread
        )
        
        result = validator.validate_leg(quote, "buy")
        
        assert result.is_valid == False
        assert result.status == TradabilityStatus.REJECTED_WIDE_SPREAD


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
