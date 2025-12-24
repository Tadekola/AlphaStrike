import datetime as dt
from typing import List, Tuple, Optional
from ..data_providers.base import Chain, OptionQuote

def pick_exp(
    front_min: int,
    front_max: int,
    back_min: int,
    back_max: int,
    expirations: List[dt.date],
    *,
    relax: bool,
) -> Tuple[dt.date, dt.date]:
    today = dt.date.today()
    dtes = [(e, (e - today).days) for e in expirations if e > today]
    if not dtes:
        raise RuntimeError("No future expirations returned by provider.")

    # Primary window
    fronts = [e for e, d in dtes if front_min <= d <= front_max]
    backs = [e for e, d in dtes if back_min <= d <= back_max]
    if fronts and backs:
        return min(fronts), max(backs)  # nearest front, farthest back

    if not relax:
        raise RuntimeError("No expirations within requested windows.")

    # Relaxed fallback
    front = next((e for e, d in dtes if d >= front_min), dtes[0][0])
    min_back_dte = max(back_min, (front - today).days + 35)
    back = next((e for e, d in dtes if d >= min_back_dte), dtes[-1][0])

    if back <= front:
        back = dtes[-1][0]
        if back <= front:
            raise RuntimeError("Could not find a valid back expiry after the chosen front.")

    return front, back

def mid_iv(chain: Chain, right: str, K: float) -> Tuple[Optional[float], Optional[float]]:
    """Return (mid, iv) for a specific right/strike (None, None if not found)."""
    cands = [o for o in chain.options if o.right == right and abs(o.strike - K) < 1e-6]
    if not cands:
        return (None, None)
    x = cands[0]
    return (float(x.mid), float(x.iv))

def nearest_common_strike(ch_front: Chain, ch_back: Chain, target_K: float, right: str) -> Optional[float]:
    """Pick the nearest strike that exists in BOTH front/back chains for the given right."""
    f = {float(o.strike) for o in ch_front.options if o.right == right}
    b = {float(o.strike) for o in ch_back.options if o.right == right}
    commons = sorted(f & b)
    if not commons:
        return None
    return min(commons, key=lambda k: abs(k - target_K))

def round_strike(k: float, step: float) -> float:
    return step * round(k / step)


def get_quote(chain: Chain, right: str, strike: float) -> Optional[OptionQuote]:
    """Get full OptionQuote for a specific right/strike.
    
    Returns None if not found.
    """
    for o in chain.options:
        if o.right == right and abs(o.strike - strike) < 1e-6:
            return o
    return None


def get_quote_with_tradability(
    chain: Chain, 
    right: str, 
    strike: float,
    validator: "TradabilityValidator",
    action: str
) -> Tuple[Optional[OptionQuote], Optional["LegValidation"]]:
    """Get quote and validate tradability in one call.
    
    Returns (quote, validation) or (None, None) if quote not found.
    """
    from .tradability import TradabilityValidator, LegValidation
    
    quote = get_quote(chain, right, strike)
    if quote is None:
        return None, None
    
    validation = validator.validate_leg(quote, action)
    return quote, validation
