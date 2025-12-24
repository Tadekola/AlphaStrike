# AlphaStrike ⚡

> **Options Analysis & Paper Trading Toolkit**

AlphaStrike is an open-source options analysis engine for studying multi-leg strategies, market regimes, and portfolio risk. It is designed for learning, paper trading, and strategy research.

---

## What AlphaStrike Is

- A **learning tool** for understanding options strategies and Greeks
- A **paper trading journal** for tracking hypothetical trades
- A **regime analysis framework** for studying market conditions
- A **risk visualization tool** for portfolio stress testing
- An **open-source project** you can inspect, modify, and learn from

## What AlphaStrike Is NOT

- ❌ **Not a trading system** — it does not execute trades
- ❌ **Not financial advice** — it is software, not a recommendation
- ❌ **Not a profit guarantee** — past patterns do not predict future results
- ❌ **Not a black box** — all logic is transparent and auditable
- ❌ **Not production-ready** — it is experimental software

## Who This Is For

- Options traders who want to **study strategy mechanics**
- Developers learning **quantitative finance concepts**
- Paper traders who want to **journal and review hypothetical trades**
- Anyone who values **transparency over convenience**

## Who This Is NOT For

- Anyone seeking **automated trading signals**
- Anyone expecting **guaranteed profits**
- Anyone unwilling to **read and understand the code**
- Anyone who would **trade real money without independent verification**

## Design Philosophy

AlphaStrike is **conservative by design**:

1. **Honesty over hype** — No performance claims. No backtest promises.
2. **Transparency over magic** — All calculations are visible and documented.
3. **Paper trading first** — Journal trades, track outcomes, validate over time.
4. **Free data only** — Works with Tradier's free sandbox API.
5. **Fail-safe defaults** — Trades are rejected unless explicitly valid.

---

## Features

*   **Institutional Strategy Suite**:
    *   **Income**: Iron Condor, Iron Butterfly, Jade Lizard.
    *   **Directional**: Vertical Spreads, Long Diagonal (PMCC), Ratio Spreads (1x2).
    *   **Volatility**: Short Strangle, Calendar Spreads, Long Butterfly.
*   **Smart Market Analysis**:
    *   **Gamma Exposure (GEX)**: Visualize dealer positioning and potential volatility magnets.
    *   **Regime Detection**: Automated classification (Trending, Range-Bound, High Vol, Gamma Squeeze).
    *   **Advanced Metrics**: IV Rank, HV vs IV, ADX Trend Strength.
*   **Modern UI**:
    *   Streamlit-based dashboard
    *   Interactive trade candidate scanning

## Installation

1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Set up environment variables in `.env` (see `.env.example` or below):
    ```env
    TRADIER_TOKEN=your_token_here
    ```

## Usage

### GUI (Streamlit)

Run the interactive dashboard:

```bash
streamlit run app_streamlit.py
```

### CLI / Scripting

You can use the engine programmatically:

```python
from cal_pro.data_providers.tradier import TradierProvider
from cal_pro.strategies.calendar import CalendarStrategy
from cal_pro.engine.pipeline import Pipeline

provider = TradierProvider("SPY")
strategies = [CalendarStrategy()]
pipeline = Pipeline(provider, strategies)

results = pipeline.run("SPY")
for trade in results:
    print(trade.description, trade.confidence_score)
```

## Architecture

*   `cal_pro/data_providers`: Data fetching adapters.
*   `cal_pro/engine`: Core logic (MarketState, Pipeline, Scoring).
*   `cal_pro/strategies`: Strategy logic modules.
*   `cal_pro/llm`: (Experimental) LLM explanation hooks.

## 🔐 Security Setup

**IMPORTANT**: Never commit your `.env` file or API tokens to version control!

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Get your Tradier API token from: https://documentation.tradier.com/brokerage-api/getting-started

3. Add your token to `.env`:
   ```
   TRADIER_TOKEN=your_actual_token_here
   ```

4. The `.env` file is already in `.gitignore` and will not be tracked by git

## ⚠️ Known Limitations

### Data Limitations (Free Tier)
- **IV Rank: NOT IMPLEMENTED** - Requires 52-week IV history not available in free data
- **No bid-ask spread analysis**: Uses midpoint pricing which may not reflect actual executable prices
- **No liquidity checks**: Does not verify option volume or open interest for execution feasibility

### Calculation Limitations
- **POP (Probability of Profit)**:
  - Only **Calendar Spread** computes real POP (marked as `VERIFIED`)
  - All other strategies show `UNVERIFIED` - POP calculation not implemented
  - Do NOT rely on unverified POP for trading decisions
- **DX vs ADX**: Trend indicator shows DX (Directional Index), not smoothed ADX
- **Close-to-Close Range**: Uses simple close-to-close movement, not true ATR (which requires H/L/C)
- **Zero interest rate**: Black-Scholes assumes r=0.0, q=0.0

### Operational Limitations
- **No commission costs**: Does not factor in trading fees
- **No position sizing**: Does not include risk management or portfolio allocation logic
- **Mock data gated**: Requires `ALLOW_MOCK_DATA=true` environment variable to enable

### Safety Notes
- Confidence scores for unverified strategies show "LOW CONFIDENCE: INSUFFICIENT DATA"
- Mock mode displays a prominent warning banner
- L-Score (qualitative analysis) is not implemented (shows 0.0)

## 🛡️ Tradability & Execution Assumptions (PR #2)

AlphaStrike enforces hard guardrails to prevent proposing untradable structures.

### Liquidity Gates (Configurable)
Every option leg must pass ALL of the following:
| Check | Default Threshold | Rejection Status |
|-------|-------------------|------------------|
| Open Interest | ≥ 250 | `REJECTED — INSUFFICIENT OPEN INTEREST` |
| Daily Volume | ≥ 50 | `REJECTED — INSUFFICIENT VOLUME` |
| Bid-Ask Spread | ≤ 15% of mid | `REJECTED — WIDE SPREAD` |
| Valid Quote | Bid > 0 AND Ask > 0 | `REJECTED — NO VALID QUOTE` |

If **any leg** fails validation, the **entire trade** is rejected.

### Conservative Pricing Model
AlphaStrike does NOT use midpoint pricing. Instead:
- **Debit trades (buying)**: Uses `ask + slippage`
- **Credit trades (selling)**: Uses `bid - slippage`

Slippage calculation:
```
slippage = (mid × 1%) + (spread × 50%)
```

This ensures displayed P/L reflects realistic worst-case execution.

### Provider Robustness
- **Retry Logic**: 3 retries with exponential backoff (1s, 2s, 4s)
- **Caching**: Option chains cached for 5 minutes to reduce API calls
- **Graceful Failure**: Individual ticker failures don't crash the scan
- **Rate Limit Handling**: Automatic backoff on 429 responses

### UI Indicators
| Status | Meaning |
|--------|---------|
| ✅ `TRADABLE` | All legs pass validation |
| ❌ `REJECTED` | One or more legs failed validation |

Rejection reasons are shown in the detailed trade view.

## 📐 Indicator Definitions (PR #3)

All technical indicators use standard, defensible mathematical implementations.

### ADX (Average Directional Index)
**Method**: Wilder-smoothed (14-period)

```
1. True Range (TR) = max(H-L, |H-Cp|, |L-Cp|)
2. +DM = H - Hp if (H-Hp) > (Lp-L) and (H-Hp) > 0, else 0
3. -DM = Lp - L if (Lp-L) > (H-Hp) and (Lp-L) > 0, else 0
4. Wilder smoothing: smoothed(t) = smoothed(t-1) × (n-1)/n + value(t)
5. +DI = 100 × smoothed(+DM) / smoothed(TR)
6. -DI = 100 × smoothed(-DM) / smoothed(TR)
7. DX = 100 × |+DI - -DI| / (+DI + -DI)
8. ADX = Wilder-smoothed DX over 14 periods
```

**Interpretation**: ADX > 25 indicates trending market, < 25 indicates range-bound.

### ATR (Average True Range)
**Method**: Wilder-smoothed True Range (14-period)

```
1. True Range (TR) = max(H-L, |H-Cp|, |L-Cp|)
2. First ATR = simple average of first 14 TRs
3. ATR(t) = ATR(t-1) × (n-1)/n + TR(t)/n
```

Uses High, Low, Close from Tradier daily bars.

### HV (Historical Volatility)
**Method**: Log returns, annualized (√252)

```
1. Log return: r(t) = ln(P(t) / P(t-1))
2. HV = σ(r) × √252
```

Log returns are preferred over simple returns because they are time-additive and symmetric.

### GEX (Gamma Exposure)
**Method**: Single-expiry, OI-based gamma approximation

```
GEX = Σ(gamma × OI × spot × 100) for calls
    - Σ(gamma × OI × spot × 100) for puts
```

**⚠️ Limitations**:
- Uses only a single expiration (~30 DTE)
- Relies on provider-supplied gamma values
- Does not aggregate across all expirations
- Thresholds for regime classification are arbitrary

**TODO**: Future PR should aggregate across multiple expirations.

### RSI (Relative Strength Index)
Standard 14-period RSI using simple averaging of gains and losses.

### SMA (Simple Moving Average)
Standard arithmetic mean over specified period (default: 20).

### Bollinger Width
```
Width = (Upper Band - Lower Band) / SMA
```
Where bands are SMA ± 2 × standard deviation.

## 🧭 Regime–Strategy Suitability (PR #4)

AlphaStrike enforces structural suitability between market regimes and strategies.
**Inappropriate strategy-regime combinations are rejected, not just warned.**

### Market Regimes

| Regime | Detection Rule | Rationale |
|--------|---------------|-----------|
| **STRONG_TREND** | ADX > 30 | Clear directional movement |
| **WEAK_TREND** | 20 < ADX ≤ 30 | Mild directional bias |
| **RANGE_BOUND** | ADX ≤ 20 | No clear direction |
| **VOL_EXPANSION** | HV5/HV20 > 1.2 | Short-term vol spiking |
| **VOL_CONTRACTION** | HV5/HV20 < 0.8 | Short-term vol compressing |
| **VOL_NEUTRAL** | 0.8 ≤ HV5/HV20 ≤ 1.2 | Stable volatility |

### Strategy Suitability Matrix

| Strategy | Allowed Trend Regimes | Allowed Vol Regimes | Key Risk |
|----------|----------------------|---------------------|----------|
| Iron Condor | RANGE, WEAK | CONTRACTION, NEUTRAL | Short gamma + short vega |
| Iron Butterfly | RANGE only | CONTRACTION, NEUTRAL | Very narrow profit zone |
| Vertical Spread | ALL | ALL | Directional risk |
| Calendar | RANGE, WEAK | EXPANSION, NEUTRAL | Long vega |
| Short Strangle | RANGE only | CONTRACTION only | **UNDEFINED RISK** |
| Jade Lizard | RANGE, WEAK | CONTRACTION, NEUTRAL | Naked put risk |
| Long Butterfly | RANGE, WEAK | ALL | Low probability |
| PMCC/Diagonal | ALL | ALL | LEAP value at risk |
| Ratio Spread | RANGE, WEAK | CONTRACTION, NEUTRAL | Naked leg exposure |

### Forbidden Combinations (Examples)

| ❌ Forbidden | Reason |
|--------------|--------|
| Iron Condor in STRONG_TREND | Wings will be breached |
| Iron Condor in VOL_EXPANSION | Short vega gets crushed |
| Short Strangle in STRONG_TREND | Undefined risk + directional move |
| Short Strangle in VOL_EXPANSION | Catastrophic for short vega |
| Calendar in STRONG_TREND | Price moves away from strike |

### Enforcement Behavior

When a strategy is unsuitable for the detected regime:
1. Trade is **rejected** (not just warned)
2. Status shows: `REJECTED — REGIME UNSUITABLE`
3. Rejection reason explains which rule was violated
4. Trade still appears in results if "Show rejected" is enabled

### UI Controls

- **Enforce regime-strategy suitability**: Toggle to enable/disable enforcement
- **Show rejected trades**: Display rejected trades with reasons

## 📊 Portfolio Greeks & Exposure (PR #5)

AlphaStrike now tracks portfolio-level Greeks and warns on dangerous exposure levels.

### Position Greeks

Each trade displays its aggregate Greeks:
| Greek | Symbol | Meaning |
|-------|--------|---------|
| **Delta** | Δ | Directional exposure (+1 ≈ 100 shares long) |
| **Gamma** | Γ | Delta sensitivity (negative = short gamma risk) |
| **Vega** | V | Volatility sensitivity (negative = hurt by vol spike) |
| **Theta** | Θ | Time decay (negative = loses value daily) |

### Exposure Thresholds

| Check | Warning | Max | Risk |
|-------|---------|-----|------|
| Net Delta | ±30 | ±50 | High directional exposure |
| Short Gamma | -2.0 | -5.0 | Vulnerable to large moves |
| Net Vega | ±$300 | ±$500 | Heavy vol sensitivity |

### Concentration Detection

AlphaStrike detects and warns on:
- **Directional stacking**: ≥3 positions with same delta sign
- **Volatility stacking**: ≥3 positions with same vega sign
- **Short gamma concentration**: ≥2 short gamma positions

### Data Source Transparency

| Source | Label | Meaning |
|--------|-------|---------|
| Provider | `BROKER` | Greeks from Tradier (preferred) |
| Calculated | `BS_CALC` | Black-Scholes fallback (clearly labeled) |

### Exposure Check Behavior

| Status | Meaning |
|--------|---------|
| `SAFE` | All exposures within limits |
| `WARNING` | Approaching or exceeding thresholds |
| `BLOCKED` | Exceeds max (if blocking enabled) |

## 🔥 Scenario Stress Testing (PR #6)

AlphaStrike tests portfolios against market shocks using Greeks-based P&L approximation.

### P&L Approximation Formula

Uses second-order Taylor expansion:

```
ΔP&L ≈ Δ × ΔS + 0.5 × Γ × (ΔS)² + V × Δσ
```

Where:
- **Δ** = Position delta
- **Γ** = Position gamma
- **V** = Position vega
- **ΔS** = Price change in dollars
- **Δσ** = IV change in percentage points

### Predefined Scenarios

| Category | Scenarios |
|----------|-----------|
| **Price Shocks** | ±1%, ±2%, ±5% |
| **Vol Shocks** | +5pts, +10pts, -5pts |
| **Combined** | Crash (-2% + IV+10), Rally (+2% + IV-5) |

### Scenario Details

| Scenario | Price | IV | Description |
|----------|-------|----|----|
| Price -5% | -5% | — | Strong bearish move |
| Price -2% | -2% | — | Moderate bearish |
| Price +5% | +5% | — | Strong bullish move |
| IV +10pts | — | +10 | Fear spike |
| Crash | -2% | +10 | Typical market crash |
| Rally | +2% | -5 | Market rally with vol crush |

### Loss Thresholds

| Threshold | Default | Meaning |
|-----------|---------|---------|
| Warning | $500 | Flag scenarios exceeding this |
| Severe | $1,000 | Flag as severe loss |

### Approximation Limitations

⚠️ **Important**: This is an approximation, not exact pricing.

- Greeks assumed constant (instantaneous move)
- **Less reliable for moves ≥5%**
- Cross-gamma effects not modeled
- Theta decay during shock not included

### UI Display

Each trade shows:
- **Worst Case**: Scenario with maximum loss
- **Best Case**: Scenario with maximum gain
- **Scenario Table**: All scenarios with P&L breakdown
- **Breach Warnings**: Scenarios exceeding loss threshold

## 📓 Paper Trading Journal (PR #7)

AlphaStrike includes a paper trading journal for tracking outcomes and validating strategies over time.

### Storage

- **Format**: SQLite database (`data/journal.db`)
- **Persistence**: Survives app restarts
- **Schema**: Indexed by status, strategy, ticker

### What's Stored

Each journal entry captures:

| Category | Fields |
|----------|--------|
| **Identity** | ID, timestamp, ticker, strategy |
| **Entry** | Entry price, legs, description |
| **Context** | Regime label, tradability status |
| **Greeks** | Delta, gamma, vega, theta at entry |
| **Stress** | Worst-case scenario and P&L |
| **Scoring** | Confidence score, POP, max profit/loss |

### Trade Lifecycle

```
OPEN → (user enters exit price) → CLOSED
```

| Status | Meaning |
|--------|---------|
| `OPEN` | Trade logged, awaiting outcome |
| `CLOSED` | User entered exit price, P&L calculated |

### P&L Calculation

```
Realized P&L = Exit Price - Entry Price
```

- **Entry Price**: Conservative fill from engine (debit = negative, credit = positive)
- **Exit Price**: User-entered closing price

### Calibration Metrics

All metrics based **ONLY** on user-logged outcomes:

| Metric | Description |
|--------|-------------|
| **Win Rate** | Winners / Closed trades |
| **Total P&L** | Sum of all realized P&L |
| **Avg P&L** | Mean realized P&L |
| **By Strategy** | Win rate and P&L per strategy |
| **Score Calibration** | Win rate by confidence score bin |

### Score Calibration Bins

| Bin | Score Range | Purpose |
|-----|-------------|---------|
| Low | 0-40 | Do low-confidence trades underperform? |
| Medium | 40-70 | Baseline performance |
| High | 70-100 | Do high-confidence trades outperform? |

### UI Workflow

1. **Save to Journal**: Button in Detailed Ticket tab
2. **View Open**: Journal tab → Open Trades
3. **Close Trade**: Enter exit price, click Close
4. **View Metrics**: Journal tab → Calibration

### Non-Negotiables

⚠️ **Truthfulness guarantees**:
- No backtest claims
- No simulated fills
- No inferred outcomes
- Only user-entered data counts as truth

## Recommended Before Live Trading

- [ ] Only use strategies with VERIFIED POP for probability-based decisions
- [ ] Paper trade extensively to validate strategies
- [ ] Implement bid-ask spread warnings
- [ ] Add commission/fee calculations
- [ ] Include delta hedging logic
- [ ] Add position Greeks monitoring
- [ ] Consult with a licensed financial advisor
