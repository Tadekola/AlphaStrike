# Gate Changes - Less Restrictive Filtering

## Summary of Changes

The app now shows **all calendar spreads that meet the minimum POP threshold**, with a clear indicator showing which ones pass all quality gates.

## What Changed

### 1. **More Lenient Default Gate Values** (`config.yaml`)

**Before** → **After**:
- `pop_min`: 0.55 → **0.45** (lower probability threshold)
- `term_min_pts`: 0.5 → **0.0** (allow any term structure, even flat)
- `rsi_min/max`: 40-60 → **30-70** (wider RSI range)
- `hv5_leq_hv20`: true → **false** (don't require falling volatility)
- `dma_band_atr`: 1.25 → **2.0** (wider price deviation band)
- `adx_max`: 20 → **30** (allow higher ADX/trend strength)

### 2. **New Gate Indicator Column**

The results table now includes a **`gates_pass`** column:
- **✓** = All gates passed (term structure, RSI, HV, price band)
- **✗** = One or more gates failed

### 3. **Smarter Sorting**

Results are sorted by:
1. **Gate status first** (✓ candidates appear at top)
2. **POP** (probability of profit)
3. **Best P/L** (maximum profit potential)

This means you see the highest-quality trades first, but can still review lower-quality opportunities.

## Why These Changes?

### Old Behavior (Too Restrictive):
- Many valid calendar spreads were **completely hidden** from view
- No way to see why candidates were rejected
- Hard-coded gates were too conservative for some strategies
- Users couldn't make informed decisions about risk/reward tradeoffs

### New Behavior (More Transparent):
- ✅ **See all candidates** that meet minimum POP
- ✅ **Clear visibility** into which gates passed/failed
- ✅ **More flexibility** to choose your own risk tolerance
- ✅ **Better defaults** that work for more market conditions

## Example Use Cases

### Conservative Trader
- Filter the table to only show **✓** candidates
- Use higher POP threshold (0.60+)
- Manually verify RSI and term structure

### Aggressive Trader
- Review **✗** candidates for high P/L potential
- Accept lower POP (0.45-0.50)
- Trade in trending markets (ignore RSI band gate)

### Research/Backtesting
- Export all candidates to CSV
- Analyze which gates correlate with actual profitability
- Refine your own custom gate thresholds

## How to Use

1. **Run the search** with default settings
2. **Review the table**:
   - Green ✓ = highest quality (recommended)
   - Red ✗ = review carefully, may have risk factors
3. **Check diagnostics** to see specific gate values
4. **Adjust sliders** if needed to refine search

## Reverting to Old Behavior

If you prefer the stricter filtering, edit `config.yaml`:

```yaml
defaults:
  pop_min: 0.55
  term_min_pts: 0.5
  rsi_min: 40
  rsi_max: 60
  hv5_leq_hv20: true
  dma_band_atr: 1.25
```

Then the app will only show candidates that pass all gates.
