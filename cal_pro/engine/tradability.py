"""
Tradability validation module for PR #2: Trade Realism & Data Robustness.

This module enforces hard guardrails so AlphaStrike cannot propose untradable
or unrealistic option structures.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

from ..data_providers.base import OptionQuote


class TradabilityStatus(Enum):
    """Trade tradability status."""
    TRADABLE = "TRADABLE"
    REJECTED_NO_QUOTE = "REJECTED — NO VALID QUOTE"
    REJECTED_LOW_OI = "REJECTED — INSUFFICIENT OPEN INTEREST"
    REJECTED_LOW_VOLUME = "REJECTED — INSUFFICIENT VOLUME"
    REJECTED_WIDE_SPREAD = "REJECTED — WIDE SPREAD"
    REJECTED_ZERO_BID = "REJECTED — ZERO BID"
    REJECTED_ZERO_ASK = "REJECTED — ZERO ASK"


@dataclass
class TradabilityConfig:
    """Configuration for tradability validation.
    
    All thresholds are conservative defaults that can be adjusted.
    """
    # Minimum open interest per leg
    min_open_interest: int = 250
    
    # Minimum daily volume per leg
    min_volume: int = 50
    
    # Maximum bid-ask spread as percentage of midpoint
    max_spread_pct: float = 0.15  # 15%
    
    # Slippage configuration
    base_slippage_pct: float = 0.01  # 1% base slippage
    spread_slippage_multiplier: float = 0.5  # Additional slippage = 50% of spread
    
    # If spread exceeds this, reject even with slippage model
    reject_spread_pct: float = 0.25  # 25% - too wide to price reliably


@dataclass
class LegValidation:
    """Validation result for a single option leg."""
    quote: OptionQuote
    is_valid: bool
    status: TradabilityStatus
    rejection_reason: str = ""
    
    # Pricing info
    entry_price: float = 0.0  # Conservative price (ask for buy, bid for sell)
    slippage: float = 0.0


@dataclass
class TradeValidation:
    """Validation result for entire trade structure."""
    is_tradable: bool
    status: TradabilityStatus
    rejection_reasons: List[str] = field(default_factory=list)
    leg_validations: List[LegValidation] = field(default_factory=list)
    
    # Conservative pricing
    total_debit: float = 0.0  # Positive = pay, Negative = receive credit
    total_slippage: float = 0.0


class TradabilityValidator:
    """Validates option legs and trades for real-world tradability."""
    
    def __init__(self, config: Optional[TradabilityConfig] = None):
        self.config = config or TradabilityConfig()
    
    def validate_leg(self, quote: OptionQuote, action: str) -> LegValidation:
        """Validate a single option leg for tradability.
        
        Args:
            quote: The option quote to validate
            action: 'buy' or 'sell'
            
        Returns:
            LegValidation with status and conservative pricing
        """
        # Check for valid quote (bid and ask > 0)
        if not quote.is_quoted:
            if quote.bid == 0 and quote.ask == 0:
                return LegValidation(
                    quote=quote,
                    is_valid=False,
                    status=TradabilityStatus.REJECTED_NO_QUOTE,
                    rejection_reason=f"No valid quote for {quote.right} @ {quote.strike}"
                )
            elif quote.bid == 0:
                return LegValidation(
                    quote=quote,
                    is_valid=False,
                    status=TradabilityStatus.REJECTED_ZERO_BID,
                    rejection_reason=f"Zero bid for {quote.right} @ {quote.strike}"
                )
            else:
                return LegValidation(
                    quote=quote,
                    is_valid=False,
                    status=TradabilityStatus.REJECTED_ZERO_ASK,
                    rejection_reason=f"Zero ask for {quote.right} @ {quote.strike}"
                )
        
        # Check open interest
        if quote.open_interest < self.config.min_open_interest:
            return LegValidation(
                quote=quote,
                is_valid=False,
                status=TradabilityStatus.REJECTED_LOW_OI,
                rejection_reason=f"OI={quote.open_interest} < {self.config.min_open_interest} for {quote.right} @ {quote.strike}"
            )
        
        # Check volume
        if quote.volume < self.config.min_volume:
            return LegValidation(
                quote=quote,
                is_valid=False,
                status=TradabilityStatus.REJECTED_LOW_VOLUME,
                rejection_reason=f"Volume={quote.volume} < {self.config.min_volume} for {quote.right} @ {quote.strike}"
            )
        
        # Check spread percentage
        spread_pct = quote.spread_pct
        if spread_pct > self.config.reject_spread_pct:
            return LegValidation(
                quote=quote,
                is_valid=False,
                status=TradabilityStatus.REJECTED_WIDE_SPREAD,
                rejection_reason=f"Spread={spread_pct:.1%} > {self.config.reject_spread_pct:.0%} for {quote.right} @ {quote.strike}"
            )
        
        if spread_pct > self.config.max_spread_pct:
            return LegValidation(
                quote=quote,
                is_valid=False,
                status=TradabilityStatus.REJECTED_WIDE_SPREAD,
                rejection_reason=f"Spread={spread_pct:.1%} > {self.config.max_spread_pct:.0%} for {quote.right} @ {quote.strike}"
            )
        
        # Calculate conservative pricing with slippage
        entry_price, slippage = self._calculate_conservative_price(quote, action)
        
        return LegValidation(
            quote=quote,
            is_valid=True,
            status=TradabilityStatus.TRADABLE,
            entry_price=entry_price,
            slippage=slippage
        )
    
    def _calculate_conservative_price(self, quote: OptionQuote, action: str) -> Tuple[float, float]:
        """Calculate conservative entry price with slippage.
        
        For BUY: use ask + slippage (worst case for buyer)
        For SELL: use bid - slippage (worst case for seller)
        
        Slippage increases with wider spreads.
        """
        spread = quote.spread
        mid = quote.mid
        
        # Base slippage + spread-dependent component
        base_slip = mid * self.config.base_slippage_pct
        spread_slip = spread * self.config.spread_slippage_multiplier
        total_slippage = base_slip + spread_slip
        
        if action == 'buy':
            # Buyer pays ask + slippage
            entry_price = quote.ask + total_slippage
        else:
            # Seller receives bid - slippage
            entry_price = max(0.01, quote.bid - total_slippage)  # Floor at $0.01
        
        return entry_price, total_slippage
    
    def validate_trade(self, legs: List[Tuple[OptionQuote, str, int]]) -> TradeValidation:
        """Validate entire trade structure.
        
        Args:
            legs: List of (quote, action, quantity) tuples
            
        Returns:
            TradeValidation with overall status and conservative pricing
        """
        leg_validations = []
        rejection_reasons = []
        total_debit = 0.0
        total_slippage = 0.0
        all_valid = True
        worst_status = TradabilityStatus.TRADABLE
        
        for quote, action, qty in legs:
            validation = self.validate_leg(quote, action)
            leg_validations.append(validation)
            
            if not validation.is_valid:
                all_valid = False
                rejection_reasons.append(validation.rejection_reason)
                worst_status = validation.status
            else:
                # Calculate cost/credit for this leg
                if action == 'buy':
                    # Buying costs money (debit)
                    total_debit += validation.entry_price * qty * 100  # Per contract
                else:
                    # Selling receives money (credit)
                    total_debit -= validation.entry_price * qty * 100
                
                total_slippage += validation.slippage * qty * 100
        
        return TradeValidation(
            is_tradable=all_valid,
            status=worst_status if not all_valid else TradabilityStatus.TRADABLE,
            rejection_reasons=rejection_reasons,
            leg_validations=leg_validations,
            total_debit=round(total_debit, 2),
            total_slippage=round(total_slippage, 2)
        )


def get_conservative_price(quote: OptionQuote, action: str, config: Optional[TradabilityConfig] = None) -> Tuple[float, float]:
    """Convenience function to get conservative price for a single quote.
    
    Returns:
        (entry_price, slippage)
    """
    validator = TradabilityValidator(config)
    return validator._calculate_conservative_price(quote, action)


def validate_option_for_trade(quote: OptionQuote, action: str, config: Optional[TradabilityConfig] = None) -> LegValidation:
    """Convenience function to validate a single option.
    
    Returns:
        LegValidation with tradability status
    """
    validator = TradabilityValidator(config)
    return validator.validate_leg(quote, action)
