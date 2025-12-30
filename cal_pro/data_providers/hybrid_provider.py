"""
Hybrid Data Provider - Combines Public.com and Tradier for maximum reliability.

Features:
1. Dual-source fetching with automatic fallback
2. Cross-validation to detect stale or bad data
3. Uses Public.com for real-time quotes, Tradier for historical data
4. Flags discrepancies for user awareness
"""
import os
from datetime import date
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import DataProvider, Bar, OptionQuote, Chain
from .tradier import TradierProvider
from .public_provider import PublicProvider, is_public_configured


@dataclass
class ValidationResult:
    """Result of cross-validation between providers."""
    is_valid: bool
    spot_discrepancy_pct: float = 0.0
    quote_discrepancies: int = 0
    warnings: List[str] = field(default_factory=list)
    primary_source: str = "unknown"
    fallback_used: bool = False


@dataclass 
class HybridQuote:
    """Quote with metadata about source and validation."""
    quote: OptionQuote
    source: str
    validated: bool = False
    discrepancy_pct: float = 0.0


class HybridProvider(DataProvider):
    """
    Hybrid data provider combining Public.com and Tradier.
    
    Strategy:
    - Spot price: Use Public.com (real-time), validate against Tradier
    - Historical data: Use Tradier (more reliable historical API)
    - Option chains: Fetch from both, cross-validate, use best data
    - Fallback: If one provider fails, seamlessly use the other
    
    Environment variables:
    - PUBLIC_API_SECRET: Required for Public.com
    - TRADIER_TOKEN: Required for Tradier
    """
    
    # Thresholds for validation
    SPOT_DISCREPANCY_THRESHOLD = 0.02  # 2% spot price difference triggers warning
    QUOTE_DISCREPANCY_THRESHOLD = 0.05  # 5% quote difference triggers warning
    GREEKS_DISCREPANCY_THRESHOLD = 0.20  # 20% Greeks difference (they vary more)
    
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self._public: Optional[PublicProvider] = None
        self._tradier: Optional[TradierProvider] = None
        self._validation: Optional[ValidationResult] = None
        
        # Initialize available providers
        if is_public_configured():
            try:
                self._public = PublicProvider(ticker)
            except Exception as e:
                print(f"[HybridProvider] Public.com init failed: {e}")
        
        try:
            self._tradier = TradierProvider(ticker)
        except Exception as e:
            print(f"[HybridProvider] Tradier init failed: {e}")
        
        if not self._public and not self._tradier:
            raise RuntimeError("No data providers available. Check API credentials.")
    
    @property
    def validation_result(self) -> Optional[ValidationResult]:
        """Get the last validation result."""
        return self._validation
    
    def _fetch_parallel(self, func_name: str, *args, **kwargs) -> Tuple[any, any]:
        """Fetch from both providers in parallel."""
        results = {"public": None, "tradier": None}
        errors = {"public": None, "tradier": None}
        
        def fetch_public():
            if self._public:
                return getattr(self._public, func_name)(*args, **kwargs)
            return None
        
        def fetch_tradier():
            if self._tradier:
                return getattr(self._tradier, func_name)(*args, **kwargs)
            return None
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if self._public:
                futures[executor.submit(fetch_public)] = "public"
            if self._tradier:
                futures[executor.submit(fetch_tradier)] = "tradier"
            
            for future in as_completed(futures, timeout=30):
                provider = futures[future]
                try:
                    results[provider] = future.result()
                except Exception as e:
                    errors[provider] = str(e)
        
        return results["public"], results["tradier"]
    
    def spot(self) -> float:
        """
        Get spot price with cross-validation.
        
        Priority: Public.com (real-time) > Tradier (delayed)
        Validates both and warns on significant discrepancy.
        """
        public_spot, tradier_spot = self._fetch_parallel("spot")
        
        warnings = []
        primary_source = "unknown"
        fallback_used = False
        discrepancy = 0.0
        
        # Determine which price to use
        if public_spot is not None and tradier_spot is not None:
            # Both available - validate
            discrepancy = abs(public_spot - tradier_spot) / tradier_spot
            if discrepancy > self.SPOT_DISCREPANCY_THRESHOLD:
                warnings.append(
                    f"Spot price discrepancy: Public=${public_spot:.2f} vs Tradier=${tradier_spot:.2f} "
                    f"({discrepancy:.1%} diff)"
                )
            primary_source = "Public.com"
            result = public_spot  # Prefer real-time
            
        elif public_spot is not None:
            primary_source = "Public.com"
            result = public_spot
            warnings.append("Tradier unavailable, using Public.com only")
            
        elif tradier_spot is not None:
            primary_source = "Tradier"
            result = tradier_spot
            fallback_used = True
            warnings.append("Public.com unavailable, falling back to Tradier")
            
        else:
            raise RuntimeError(f"Could not fetch spot price for {self.ticker}")
        
        self._validation = ValidationResult(
            is_valid=discrepancy <= self.SPOT_DISCREPANCY_THRESHOLD,
            spot_discrepancy_pct=discrepancy,
            warnings=warnings,
            primary_source=primary_source,
            fallback_used=fallback_used
        )
        
        return result
    
    def history(self, days: int = 60) -> List[Bar]:
        """
        Get historical bars.
        
        Priority: Tradier (better historical data) > Public.com
        """
        # Tradier has better historical data support
        if self._tradier:
            try:
                return self._tradier.history(days)
            except Exception as e:
                print(f"[HybridProvider] Tradier history failed: {e}")
        
        # Fallback to Public if available
        if self._public:
            try:
                return self._public.history(days)
            except Exception:
                pass
        
        return []
    
    def expirations(self) -> List[date]:
        """
        Get available expirations.
        
        Merges expirations from both providers for completeness.
        """
        public_exp, tradier_exp = self._fetch_parallel("expirations")
        
        # Merge and dedupe
        all_expirations = set()
        if public_exp:
            all_expirations.update(public_exp)
        if tradier_exp:
            all_expirations.update(tradier_exp)
        
        return sorted(all_expirations)
    
    def chain(self, expiry: date) -> Chain:
        """
        Get option chain with cross-validation.
        
        Fetches from both providers, validates quotes, and merges best data.
        """
        public_chain, tradier_chain = self._fetch_parallel("chain", expiry)
        
        warnings = []
        quote_discrepancies = 0
        
        # If only one provider has data, use it
        if public_chain and not tradier_chain:
            warnings.append("Using Public.com chain only (Tradier unavailable)")
            self._update_validation(warnings=warnings, primary="Public.com", fallback=False)
            return public_chain
        
        if tradier_chain and not public_chain:
            warnings.append("Using Tradier chain only (Public.com unavailable)")
            self._update_validation(warnings=warnings, primary="Tradier", fallback=True)
            return tradier_chain
        
        if not public_chain and not tradier_chain:
            raise RuntimeError(f"No chain data available for {self.ticker} {expiry}")
        
        # Both providers have data - cross-validate and merge
        # Build lookup by strike+right for Tradier
        tradier_lookup = {
            (opt.strike, opt.right): opt 
            for opt in tradier_chain.options
        }
        
        merged_options = []
        
        for pub_opt in public_chain.options:
            key = (pub_opt.strike, pub_opt.right)
            trad_opt = tradier_lookup.get(key)
            
            if trad_opt:
                # Cross-validate
                validated_opt, discrepancy = self._validate_and_merge_quote(pub_opt, trad_opt)
                if discrepancy > self.QUOTE_DISCREPANCY_THRESHOLD:
                    quote_discrepancies += 1
                merged_options.append(validated_opt)
                # Remove from lookup so we know what's left
                del tradier_lookup[key]
            else:
                # Only in Public.com
                merged_options.append(pub_opt)
        
        # Add any remaining Tradier-only options
        for trad_opt in tradier_lookup.values():
            merged_options.append(trad_opt)
        
        if quote_discrepancies > 0:
            warnings.append(
                f"{quote_discrepancies} options had quote discrepancies >5% between providers"
            )
        
        self._update_validation(
            warnings=warnings, 
            primary="Hybrid (Public.com + Tradier)",
            fallback=False,
            quote_discrepancies=quote_discrepancies
        )
        
        return Chain(expiry=expiry, options=merged_options)
    
    def _validate_and_merge_quote(
        self, 
        public_opt: OptionQuote, 
        tradier_opt: OptionQuote
    ) -> Tuple[OptionQuote, float]:
        """
        Validate and merge quotes from both providers.
        
        Returns merged quote and discrepancy percentage.
        """
        # Calculate mid discrepancy
        if public_opt.mid > 0 and tradier_opt.mid > 0:
            discrepancy = abs(public_opt.mid - tradier_opt.mid) / tradier_opt.mid
        else:
            discrepancy = 0.0
        
        # Merge strategy: Use Public.com for price (real-time), 
        # but take better Greeks/volume from whichever has more data
        merged = OptionQuote(
            symbol=public_opt.symbol or tradier_opt.symbol,
            strike=public_opt.strike,
            right=public_opt.right,
            # Use Public.com prices (more real-time)
            mid=public_opt.mid if public_opt.mid > 0 else tradier_opt.mid,
            bid=public_opt.bid if public_opt.bid > 0 else tradier_opt.bid,
            ask=public_opt.ask if public_opt.ask > 0 else tradier_opt.ask,
            iv=public_opt.iv if public_opt.iv > 0 else tradier_opt.iv,
            # Use higher volume/OI (more complete data)
            open_interest=max(public_opt.open_interest, tradier_opt.open_interest),
            volume=max(public_opt.volume, tradier_opt.volume),
            # Average Greeks if both have them, otherwise use whichever has data
            delta=self._merge_greek(public_opt.delta, tradier_opt.delta),
            gamma=self._merge_greek(public_opt.gamma, tradier_opt.gamma),
            theta=self._merge_greek(public_opt.theta, tradier_opt.theta),
            vega=self._merge_greek(public_opt.vega, tradier_opt.vega)
        )
        
        return merged, discrepancy
    
    def _merge_greek(self, public_val: float, tradier_val: float) -> float:
        """Merge Greek values - average if both present, otherwise use available."""
        if public_val != 0 and tradier_val != 0:
            return (public_val + tradier_val) / 2
        return public_val if public_val != 0 else tradier_val
    
    def _update_validation(
        self, 
        warnings: List[str], 
        primary: str, 
        fallback: bool,
        quote_discrepancies: int = 0
    ):
        """Update validation result."""
        if self._validation:
            self._validation.warnings.extend(warnings)
            self._validation.quote_discrepancies = quote_discrepancies
        else:
            self._validation = ValidationResult(
                is_valid=True,
                warnings=warnings,
                primary_source=primary,
                fallback_used=fallback,
                quote_discrepancies=quote_discrepancies
            )


def is_hybrid_available() -> bool:
    """Check if hybrid provider can be used (at least one provider configured)."""
    has_public = is_public_configured()
    has_tradier = bool(os.getenv("TRADIER_TOKEN"))
    return has_public or has_tradier


def get_hybrid_status() -> str:
    """Get status message for hybrid provider availability."""
    has_public = is_public_configured()
    has_tradier = bool(os.getenv("TRADIER_TOKEN"))
    
    if has_public and has_tradier:
        return "✅ Hybrid mode: Public.com (real-time) + Tradier (historical) with cross-validation"
    elif has_public:
        return "⚠️ Public.com only - add TRADIER_TOKEN for cross-validation"
    elif has_tradier:
        return "⚠️ Tradier only - add PUBLIC_API_SECRET for real-time quotes"
    else:
        return "❌ No providers configured"
