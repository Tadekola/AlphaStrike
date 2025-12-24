import math

def _N(x):  # standard normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _n(x):  # standard normal PDF
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def bs_price(S, K, sigma, T, right='call', r=0.0, q=0.0):
    """
    Black–Scholes price. sigma in decimals, T in years.
    """
    if T <= 0 or sigma <= 0:
        if right == 'call':
            return max(S - K, 0.0)
        else:
            return max(K - S, 0.0)

    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if right == 'call':
        return S * math.exp(-q * T) * _N(d1) - K * math.exp(-r * T) * _N(d2)
    else:
        return K * math.exp(-r * T) * _N(-d2) - S * math.exp(-q * T) * _N(-d1)

def bs_vega(S, K, sigma, T, r=0.0, q=0.0):
    """
    Black–Scholes vega with respect to volatility in DECIMALS.
    Returns $ price change per 1.00 (100 vol points) change in sigma.
    For $/1 vol point, multiply by 0.01. Then multiply by 100 for contract multiplier.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return S * math.exp(-q * T) * _n(d1) * math.sqrt(T)
