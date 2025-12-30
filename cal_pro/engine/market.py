from dataclasses import dataclass
from typing import Optional, List
import statistics as stats
import datetime as dt
import math
from ..data_providers.base import DataProvider, Bar

# IV Rank labels for transparency
IV_RANK_NOT_IMPLEMENTED = "NOT IMPLEMENTED (FREE DATA LIMITATION)"
IV_RANK_HV_PROXY = "HV PROXY (estimate only - not true IV rank)"

# Indicator methodology labels
ADX_METHOD = "Wilder-smoothed (14-period)"
ATR_METHOD = "Wilder-smoothed True Range (14-period)"
HV_METHOD = "Log returns, annualized (√252)"
GEX_METHOD = "Single-expiry, OI-based gamma approximation"

@dataclass
class MarketState:
    """Market state with technical indicators.
    
    All indicators are computed using standard, defensible methodologies.
    See individual method docstrings for mathematical definitions.
    """
    ticker: str
    spot: float
    sma20: float
    
    # Volatility indicators
    atr14: float  # True ATR using Wilder smoothing on True Range
    hv5: float    # 5-day historical volatility (log returns, annualized)
    hv20: float   # 20-day historical volatility (log returns, annualized)
    
    # Momentum/Trend indicators
    rsi14: float  # Relative Strength Index
    adx14: float = 0.0  # True ADX (Wilder-smoothed DX)
    plus_di14: float = 0.0  # +DI component
    minus_di14: float = 0.0  # -DI component
    
    # Market structure
    gex: float = 0.0  # Gamma Exposure (single-expiry approximation)
    gex_method: str = GEX_METHOD
    bollinger_width: float = 0.0
    
    # IV Rank proxy using historical volatility
    iv_rank: Optional[float] = None  # HV-based proxy when available
    iv_rank_label: str = IV_RANK_NOT_IMPLEMENTED
    hv_ratio: Optional[float] = None  # HV5/HV20 ratio for vol regime
    
    # Classification
    regime: str = "Neutral"
    
    # Deprecated aliases for backward compatibility
    @property
    def dx14(self) -> float:
        """DEPRECATED: Use adx14. Returns true ADX now."""
        return self.adx14
    
    @property
    def atr5(self) -> float:
        """DEPRECATED: Use atr14. Returns true ATR now."""
        return self.atr14
    
    @classmethod
    def build(cls, ticker: str, provider: DataProvider) -> "MarketState":
        spot = provider.spot()
        hist = provider.history(60)
        closes = [b.close for b in hist]
        
        # Calculate GEX using nearest expiry > 14 days
        # LIMITATION: Single-expiry approximation only. See GEX_METHOD.
        # TODO (future PR): Aggregate across multiple expirations for more accurate GEX
        gex = 0.0
        try:
            today = dt.date.today()
            exps = provider.expirations()
            # Pick an expiration ~30 days out for representative gamma
            target_date = today + dt.timedelta(days=30)
            if exps:
                chosen_exp = min(exps, key=lambda d: abs((d - target_date).days))
                chain = provider.chain(chosen_exp)
                gex = cls._calculate_gex(chain, spot)
        except Exception:
            pass  # GEX failure shouldn't crash the pipeline

        # Calculate true ADX with Wilder smoothing
        adx, plus_di, minus_di = cls._adx(hist, 14)
        
        # Calculate true ATR with Wilder smoothing
        atr = cls._atr(hist, 14)
        
        # Historical volatility using log returns
        hv5 = cls._hv(closes, 5)
        hv20 = cls._hv(closes, 20)
        
        rsi = cls._rsi(closes, 14)
        
        # Regime Classification using corrected ADX
        regime_parts = []
        if adx > 25:
            regime_parts.append("Trending")
        else:
            regime_parts.append("Range")
            
        if hv20 > 0.25:  # >25% annualized vol
            regime_parts.append("High Vol")
        else:
            regime_parts.append("Low Vol")
        
        # GEX regime classification
        # NOTE: These thresholds are arbitrary and should be calibrated
        if gex < -1_000_000:
            regime_parts.append("Neg Gamma")
        elif gex > 1_000_000:
            regime_parts.append("Pos Gamma")
            
        # Calculate IV Rank proxy using HV percentile
        # This uses HV20 compared to a longer lookback as a proxy
        iv_rank_proxy, iv_rank_label = cls._iv_rank_proxy(closes)
        hv_ratio = hv5 / hv20 if hv20 > 0 else 1.0
        
        return cls(
            ticker=ticker,
            spot=spot,
            sma20=cls._sma(closes, 20),
            atr14=atr,
            rsi14=rsi,
            hv5=hv5,
            hv20=hv20,
            adx14=adx,
            plus_di14=plus_di,
            minus_di14=minus_di,
            gex=gex,
            bollinger_width=cls._bollinger_width(closes, 20),
            regime=" / ".join(regime_parts),
            iv_rank=iv_rank_proxy,
            iv_rank_label=iv_rank_label,
            hv_ratio=hv_ratio
        )

    @staticmethod
    def _calculate_gex(chain, spot) -> float:
        """Calculate Gamma Exposure (GEX) for a single expiration.
        
        Formula: GEX = Σ(gamma × OI × spot × 100) for calls
                      - Σ(gamma × OI × spot × 100) for puts
        
        LIMITATIONS:
        - Uses only a single expiration (~30 DTE)
        - Relies on provider-supplied gamma values
        - Does not aggregate across all expirations
        - Thresholds for regime classification are arbitrary
        
        TODO: Future PR should aggregate across multiple expirations
        for more accurate market-wide GEX estimation.
        """
        total_gex = 0.0
        for o in chain.options:
            g = o.gamma
            oi = o.open_interest
            if o.right == 'call':
                total_gex += g * oi
            else:
                total_gex -= g * oi
        return total_gex * spot * 100

    @staticmethod
    def _adx(bars: List[Bar], n: int = 14) -> tuple:
        """Calculate true ADX (Average Directional Index) using Wilder smoothing.
        
        Mathematical Definition (Welles Wilder, 1978):
        1. True Range (TR) = max(H-L, |H-Cp|, |L-Cp|)
        2. +DM = H - Hp if (H-Hp) > (Lp-L) and (H-Hp) > 0, else 0
        3. -DM = Lp - L if (Lp-L) > (H-Hp) and (Lp-L) > 0, else 0
        4. Smoothed TR, +DM, -DM using Wilder smoothing: 
           smoothed(t) = smoothed(t-1) - smoothed(t-1)/n + value(t)
        5. +DI = 100 × smoothed(+DM) / smoothed(TR)
        6. -DI = 100 × smoothed(-DM) / smoothed(TR)
        7. DX = 100 × |+DI - -DI| / (+DI + -DI)
        8. ADX = Wilder-smoothed DX over n periods
        
        Returns:
            (adx, plus_di, minus_di) tuple
        """
        if len(bars) < n * 2:
            return (0.0, 0.0, 0.0)
        
        # Step 1-3: Calculate TR, +DM, -DM for each bar
        tr_list = []
        dm_plus_list = []
        dm_minus_list = []
        
        for i in range(1, len(bars)):
            h = bars[i].high
            l = bars[i].low
            c_prev = bars[i-1].close
            h_prev = bars[i-1].high
            l_prev = bars[i-1].low
            
            # True Range
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr_list.append(tr)
            
            # Directional Movement
            up_move = h - h_prev
            down_move = l_prev - l
            
            if up_move > down_move and up_move > 0:
                dm_plus_list.append(up_move)
            else:
                dm_plus_list.append(0.0)
                
            if down_move > up_move and down_move > 0:
                dm_minus_list.append(down_move)
            else:
                dm_minus_list.append(0.0)
        
        if len(tr_list) < n:
            return (0.0, 0.0, 0.0)
        
        # Step 4: Wilder smoothing function
        def wilder_smooth(data: List[float], period: int) -> List[float]:
            """Wilder's smoothing: smoothed(t) = smoothed(t-1) × (n-1)/n + value(t)/n
            
            Standard Wilder EMA formula used in ADX, ATR calculations.
            First value is SMA of first n periods, then Wilder smoothing applied.
            """
            if len(data) < period:
                return []
            
            # First smoothed value is simple AVERAGE (SMA) of first n values
            first_avg = sum(data[:period]) / period
            smoothed = [first_avg]
            
            # Subsequent values use Wilder smoothing: 
            # smoothed(t) = smoothed(t-1) * (n-1)/n + value(t)/n
            # This is equivalent to: smoothed(t) = smoothed(t-1) + (value(t) - smoothed(t-1))/n
            for i in range(period, len(data)):
                new_val = smoothed[-1] + (data[i] - smoothed[-1]) / period
                smoothed.append(new_val)
            
            return smoothed
        
        # Apply Wilder smoothing to TR, +DM, -DM
        smoothed_tr = wilder_smooth(tr_list, n)
        smoothed_dm_plus = wilder_smooth(dm_plus_list, n)
        smoothed_dm_minus = wilder_smooth(dm_minus_list, n)
        
        if not smoothed_tr or smoothed_tr[-1] == 0:
            return (0.0, 0.0, 0.0)
        
        # Step 5-6: Calculate +DI and -DI
        plus_di = 100 * smoothed_dm_plus[-1] / smoothed_tr[-1]
        minus_di = 100 * smoothed_dm_minus[-1] / smoothed_tr[-1]
        
        # Step 7: Calculate DX series
        dx_list = []
        for i in range(len(smoothed_tr)):
            if smoothed_tr[i] == 0:
                dx_list.append(0.0)
                continue
            pdi = 100 * smoothed_dm_plus[i] / smoothed_tr[i]
            mdi = 100 * smoothed_dm_minus[i] / smoothed_tr[i]
            if pdi + mdi == 0:
                dx_list.append(0.0)
            else:
                dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi))
        
        # Step 8: Wilder-smooth DX to get ADX
        if len(dx_list) < n:
            return (0.0, plus_di, minus_di)
        
        smoothed_dx = wilder_smooth(dx_list, n)
        if not smoothed_dx:
            return (0.0, plus_di, minus_di)
        
        # Final ADX: wilder_smooth now properly returns averages (not sums)
        # so no additional division is needed.
        adx = smoothed_dx[-1]
        
        return (adx, plus_di, minus_di)

    @staticmethod
    def _bollinger_width(closes, n=20, k=2) -> float:
        if len(closes) < n: return 0.0
        sma = sum(closes[-n:]) / n
        stdev = stats.pstdev(closes[-n:])
        upper = sma + k * stdev
        lower = sma - k * stdev
        return (upper - lower) / sma

    @staticmethod
    def _sma(x, n):
        n = min(n, len(x))
        return sum(x[-n:]) / n if n else float("nan")

    @staticmethod
    def _atr(bars: List[Bar], n: int = 14) -> float:
        """Calculate true Average True Range (ATR) using Wilder smoothing.
        
        Mathematical Definition (Welles Wilder, 1978):
        1. True Range (TR) = max(H-L, |H-Cp|, |L-Cp|)
           where H=High, L=Low, Cp=Previous Close
        2. ATR = Wilder-smoothed TR over n periods
           ATR(t) = ATR(t-1) × (n-1)/n + TR(t)/n
        
        This is the standard ATR used in professional trading systems.
        """
        if len(bars) < n + 1:
            return 0.0
        
        # Calculate True Range for each bar
        tr_list = []
        for i in range(1, len(bars)):
            h = bars[i].high
            l = bars[i].low
            c_prev = bars[i-1].close
            
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr_list.append(tr)
        
        if len(tr_list) < n:
            return 0.0
        
        # First ATR is simple average of first n True Ranges
        atr = sum(tr_list[:n]) / n
        
        # Apply Wilder smoothing for remaining values
        for i in range(n, len(tr_list)):
            atr = (atr * (n - 1) + tr_list[i]) / n
        
        return atr

    @staticmethod
    def _rsi(x, n=14):
        if len(x) < 2:
            return 50.0
        ch = [x[i] - x[i - 1] for i in range(1, len(x))]
        gains = [c for c in ch if c > 0]
        losses = [-c for c in ch if c < 0]
        n_real = min(n, len(ch))
        avgG = (sum(gains[-n_real:]) / n_real) if n_real else 0.0
        avgL = (sum(losses[-n_real:]) / n_real) if n_real else 1e-9
        rs = avgG / avgL if avgL > 0 else 999.0
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _hv(x: List[float], n: int) -> float:
        """Calculate Historical Volatility using log returns.
        
        Mathematical Definition:
        1. Log return: r(t) = ln(P(t) / P(t-1))
        2. HV = σ(r) × √252
        
        Where:
        - σ(r) = population standard deviation of log returns
        - √252 = annualization factor (trading days per year)
        
        Log returns are preferred over simple returns because:
        - They are time-additive (can sum across periods)
        - They are symmetric (±10% gives same magnitude)
        - They approximate normal distribution better
        """
        if len(x) < 2:
            return 0.0
        
        # Calculate log returns
        log_returns = []
        for i in range(1, len(x)):
            if x[i-1] <= 0 or x[i] <= 0:
                continue  # Skip invalid prices
            log_returns.append(math.log(x[i] / x[i-1]))
        
        n_real = min(n, len(log_returns))
        if n_real <= 1:
            return 0.0
        
        # Population standard deviation of log returns, annualized
        return stats.pstdev(log_returns[-n_real:]) * math.sqrt(252)
    
    @staticmethod
    def _iv_rank_proxy(closes: List[float], lookback: int = 60) -> tuple:
        """Calculate IV Rank proxy using historical volatility percentile.
        
        Since we don't have 52-week IV history from free data sources,
        we use HV20 percentile over the available lookback as a proxy.
        
        This is NOT true IV Rank, but provides a rough estimate of whether
        current volatility is high or low relative to recent history.
        
        Args:
            closes: List of closing prices (most recent last)
            lookback: Number of periods for percentile calculation
            
        Returns:
            Tuple of (iv_rank_proxy, label)
        """
        if len(closes) < 25:  # Need at least 25 days for meaningful HV20 history
            return (None, IV_RANK_NOT_IMPLEMENTED)
        
        # Calculate rolling HV20 values
        hv_values = []
        for i in range(20, min(len(closes), lookback)):
            window = closes[i-20:i]
            if len(window) >= 2:
                log_returns = []
                for j in range(1, len(window)):
                    if window[j-1] > 0 and window[j] > 0:
                        log_returns.append(math.log(window[j] / window[j-1]))
                if len(log_returns) >= 2:
                    hv = stats.pstdev(log_returns) * math.sqrt(252)
                    hv_values.append(hv)
        
        if len(hv_values) < 5:
            return (None, IV_RANK_NOT_IMPLEMENTED)
        
        # Current HV20 is last value
        current_hv = hv_values[-1]
        
        # Calculate percentile rank
        below_count = sum(1 for hv in hv_values[:-1] if hv < current_hv)
        percentile = below_count / (len(hv_values) - 1)
        
        return (round(percentile, 2), IV_RANK_HV_PROXY)
