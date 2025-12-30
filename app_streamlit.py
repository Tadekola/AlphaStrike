from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

# Engine Imports
from cal_pro.data_providers.tradier import TradierProvider
from cal_pro.data_providers.mock import MockProvider, is_mock_allowed
from cal_pro.data_providers.public_provider import PublicProvider, is_public_configured
from cal_pro.data_providers.hybrid_provider import HybridProvider, is_hybrid_available, get_hybrid_status
from cal_pro.engine.pipeline import Pipeline, REGIME_REJECTED
from cal_pro.engine.universes import get_universe, UNIVERSES
from cal_pro.engine.tradability import TradabilityConfig
from cal_pro.engine.regime import RegimeClassification, MarketRegime
from cal_pro.engine.portfolio import (
    PortfolioManager, PortfolioGreeks, PositionGreeks, 
    ExposureThresholds, ExposureCheck, ExposureStatus, format_greeks_summary
)
from cal_pro.engine.stress import (
    StressTestEngine, StressTestResult, ScenarioResult, 
    STANDARD_SCENARIOS, format_stress_result, get_stress_summary
)
from cal_pro.engine.journal import (
    TradeJournal, JournalDB, JournalEntry, CalibrationEngine, 
    TradeStatus, CalibrationMetrics
)

# Strategies
from cal_pro.strategies.calendar import CalendarStrategy
from cal_pro.strategies.vertical import VerticalStrategy
from cal_pro.strategies.iron_condor import IronCondorStrategy
from cal_pro.strategies.iron_fly import IronButterflyStrategy
from cal_pro.strategies.short_strangle import ShortStrangleStrategy
from cal_pro.strategies.diagonal import DiagonalStrategy
from cal_pro.strategies.ratio import RatioStrategy
from cal_pro.strategies.jade_lizard import JadeLizardStrategy
from cal_pro.strategies.butterfly import ButterflyStrategy

load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(
    page_title="AlphaStrike", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Professional Look
st.markdown("""
<style>
    .stApp {
        background-color: #0E1117;
    }
    .metric-card {
        background-color: #262730;
        border: 1px solid #464B5C;
        padding: 15px;
        border-radius: 5px;
        color: white;
    }
    .strategy-tag {
        background-color: #29B5E8;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
</style>
""", unsafe_allow_html=True)

st.title("AlphaStrike")
st.markdown("### Options Analysis & Paper Trading Toolkit")

# Persistent disclaimer banner
st.warning(
    "**RESEARCH TOOL ONLY** - This is not financial advice. All outputs are for educational purposes "
    "and require independent verification before any trading decisions. Past patterns do not predict future results. "
    "See README for full limitations."
)

# Track if mock mode is active for banner display
_mock_mode_active = False

# --- Configuration Sidebar ---
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Provider Selection with Safety Gates
    provider_options = []
    if is_hybrid_available():
        provider_options.append("Hybrid (Recommended)")
    if is_public_configured():
        provider_options.append("Public.com Only")
    provider_options.append("Tradier Only")
    if is_mock_allowed():
        provider_options.append("Mock")
    provider_name = st.selectbox("Data Provider", provider_options)
    
    # Show hybrid status
    st.caption(get_hybrid_status())
    
    if not is_mock_allowed():
        st.caption("ℹ️ Mock data disabled. Set ALLOW_MOCK_DATA=true to enable.")
    
    # Universe Selection
    st.subheader("🔍 Universe")
    scan_mode = st.radio("Mode", ["Single Ticker", "Universe Scan"])
    
    if scan_mode == "Single Ticker":
        tickers = [st.text_input("Ticker Symbol", value="SPY").upper()]
    else:
        universe_name = st.selectbox("Select Universe", list(UNIVERSES.keys()))
        tickers = get_universe(universe_name)
        st.caption(f"Scanning {len(tickers)} tickers: {', '.join(tickers[:5])}...")
    
    # Strategy Selection
    st.subheader("♟️ Strategies")
    
    selected_strategies = []
    
    with st.expander("Income (Neutral)", expanded=True):
        if st.checkbox("Iron Condor", value=True):
            selected_strategies.append(IronCondorStrategy())
        if st.checkbox("Iron Butterfly", value=True):
            selected_strategies.append(IronButterflyStrategy())
        if st.checkbox("Jade Lizard", value=False, help="Short Put + Bear Call Spread (No Upside Risk)"):
            selected_strategies.append(JadeLizardStrategy())
            
    with st.expander("Directional", expanded=True):
        if st.checkbox("Vertical Spread", value=True):
            selected_strategies.append(VerticalStrategy())
        if st.checkbox("Long Diagonal (PMCC)", value=False):
            selected_strategies.append(DiagonalStrategy())
        if st.checkbox("Ratio Spread (1x2)", value=False, help="Expert: Buy 1 / Sell 2. Exposed Risk."):
            selected_strategies.append(RatioStrategy())
            
    with st.expander("Volatility / Speculation", expanded=True):
        if st.checkbox("Calendar Spread", value=True):
            selected_strategies.append(CalendarStrategy())
        if st.checkbox("Short Strangle (High Risk)", value=False):
            selected_strategies.append(ShortStrangleStrategy())
        if st.checkbox("Long Butterfly", value=False):
            selected_strategies.append(ButterflyStrategy())

    st.subheader("🎚️ Filters")
    min_pop = st.slider("Min POP", 0.0, 1.0, 0.40, 0.05)
    show_rejected = st.checkbox("Show rejected trades", value=False)
    enforce_regime = st.checkbox("Enforce regime-strategy suitability", value=True, 
                                  help="Reject strategies that are structurally inappropriate for detected regime")
    
    # Tradability settings
    with st.expander("⚙️ Tradability Settings", expanded=False):
        min_oi = st.number_input("Min Open Interest", value=250, min_value=0, step=50)
        min_vol = st.number_input("Min Daily Volume", value=50, min_value=0, step=10)
        max_spread = st.slider("Max Bid-Ask Spread %", 0.05, 0.50, 0.15, 0.01, format="%.0f%%")
        
    tradability_config = TradabilityConfig(
        min_open_interest=min_oi,
        min_volume=min_vol,
        max_spread_pct=max_spread
    )

# --- Main Logic ---

# Show mock mode warning banner if active
if provider_name == "Mock":
    st.error("⚠️ **MOCK DATA MODE — NOT FOR TRADING** ⚠️\n\nThis mode uses synthetic data for testing only. Do not make trading decisions based on mock data.")

if st.button("🚀 Run Analysis", use_container_width=True):
    if not tickers or not tickers[0]:
        st.error("Please define a ticker or universe.")
        st.stop()
        
    if not selected_strategies:
        st.error("Select at least one strategy.")
        st.stop()

    results_cache = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # --- Pipeline Loop ---
    for i, ticker in enumerate(tickers):
        status_text.text(f"Analyzing {ticker} ({i+1}/{len(tickers)})...")
        progress_bar.progress((i + 1) / len(tickers))
        
        # 1. Provider Setup
        try:
            if provider_name == "Hybrid (Recommended)":
                provider = HybridProvider(ticker)
            elif provider_name == "Public.com Only":
                provider = PublicProvider(ticker)
            elif provider_name == "Tradier Only":
                provider = TradierProvider(ticker)
            else:
                provider = MockProvider(ticker)
            
            # 2. Pipeline Run with tradability and regime validation
            pipeline = Pipeline(provider, selected_strategies, tradability_config, 
                               enforce_regime_suitability=enforce_regime)
            candidates, market, regime = pipeline.run(ticker)
            
            if market is None:
                continue
            
            # 3. Filter & Store
            for c in candidates:
                # Filter by POP if verified
                pop_ok = c.pop is None or c.pop >= min_pop
                # Filter by tradability unless show_rejected is enabled
                tradable_ok = c.is_tradable or show_rejected
                
                if pop_ok and tradable_ok:
                    # Enrich with market context for display
                    c.metrics['regime'] = regime.combined_label if regime else "Unknown"
                    c.metrics['regime_description'] = regime.description if regime else ""
                    c.metrics['gex'] = market.gex
                    c.metrics['adx'] = market.adx14
                    c.metrics['hv20'] = market.hv20
                    c.metrics['hv5'] = market.hv5
                    results_cache.append(c)
                    
        except Exception as e:
            # st.error(f"Error on {ticker}: {e}") # Optional: Hide individual errors
            continue

    progress_bar.empty()
    status_text.empty()
    
    # Data freshness indicator with cache warning
    analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.warning(
        f"**Data Freshness**: Analysis at {analysis_time}. "
        f"Option quotes may be **5-15 minutes delayed** due to provider caching. "
        f"Greeks and prices can change rapidly. Always verify current quotes before trading."
    )

    # --- Display Results ---
    if not results_cache:
        st.warning("No candidates found. Try adjusting filters or strategies.")
    else:
        # Sort: tradable first, then by confidence
        results_cache.sort(key=lambda x: (x.is_tradable, x.confidence_score), reverse=True)
        
        # Count tradable vs rejected
        tradable_count = sum(1 for r in results_cache if r.is_tradable)
        rejected_count = len(results_cache) - tradable_count
        
        if rejected_count > 0:
            st.success(f"✅ Found {tradable_count} tradable opportunities and {rejected_count} rejected across {len(tickers)} tickers.")
        else:
            st.success(f"✅ Found {tradable_count} tradable opportunities across {len(tickers)} tickers.")
        
        # Tabs for Views
        tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📝 Detailed Ticket", "📓 Journal"])
        
        with tab1:
            # Prepare DataFrame
            data = []
            for r in results_cache:
                data.append({
                    "Tradable": "✅" if r.is_tradable else "❌",
                    "Ticker": r.ticker,
                    "Strategy": r.strategy_name,
                    "Structure": r.description,
                    "Regime": r.metrics.get('regime', 'N/A'),
                    "Confidence": r.confidence_score,
                    "Label": r.confidence_label,
                    "POP": f"{r.pop:.0%}" if r.pop is not None else "UNVERIFIED",
                    "Max Profit": r.max_profit,
                    "Max Loss": r.max_loss,
                    "Debit/Credit": r.debit,
                    "Slippage": f"${r.slippage_cost:.2f}" if r.is_tradable else "N/A"
                })
            df = pd.DataFrame(data)
            
            # Highlighting functions
            def highlight_conf(val):
                if val == "High": return 'color: green; font-weight: bold'
                if val == "Medium": return 'color: orange; font-weight: bold'
                return 'color: red'
            
            def highlight_tradable(val):
                if val == "✅": return 'color: green; font-weight: bold'
                return 'color: red; font-weight: bold'
            
            # Use map instead of applymap for pandas compatibility
            st.dataframe(
                df.style.map(highlight_conf, subset=['Label'])
                        .map(highlight_tradable, subset=['Tradable'])
                        .format({"Max Profit": "${:.2f}", "Max Loss": "${:.2f}", "Debit/Credit": "${:.2f}"}),
                use_container_width=True,
                height=500
            )
            
        with tab2:
            st.markdown("### Top Recommendations Details")
            
            # Show top 10 detailed cards
            for i, trade in enumerate(results_cache[:10]):
                # Title with tradability status
                status_icon = "✅" if trade.is_tradable else "❌"
                title = f"{status_icon} {trade.ticker} - {trade.strategy_name}: {trade.description}"
                
                with st.expander(title, expanded=(i==0)):
                    
                    # Trade-level disclaimer
                    st.caption(
                        "This analysis is for educational purposes only. Verify all data independently. "
                        "Options involve risk of loss. Past performance does not predict future results."
                    )
                    
                    # Tradability banner
                    if trade.is_tradable:
                        st.success(f"**{trade.tradability_status}** — Estimated slippage: ${trade.slippage_cost:.2f}")
                    else:
                        st.error(f"**{trade.tradability_status}**")
                        if trade.rejection_reasons:
                            with st.container():
                                st.markdown("**Rejection Reasons:**")
                                for reason in trade.rejection_reasons:
                                    st.markdown(f"- {reason}")
                    
                    st.divider()
                    
                    # Layout: Metrics
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Confidence", f"{trade.confidence_score}/100", delta=trade.confidence_label)
                    c2.metric("Max Profit", f"${trade.max_profit:.2f}*")
                    max_loss_display = str(trade.max_loss) if trade.max_loss != float('inf') else "UNLIMITED"
                    c3.metric("Max Loss", max_loss_display)
                    pop_display = f"{trade.pop:.0%}" if trade.pop is not None else "N/A"
                    c4.metric("POP", pop_display, delta=trade.pop_label if trade.pop is None else None)
                    
                    # Position sizing warning
                    if trade.max_loss == float('inf'):
                        st.error(
                            "**UNLIMITED RISK**: This strategy has undefined maximum loss. "
                            "Not suitable for most accounts. Requires margin and active management."
                        )
                    elif trade.max_loss > 500:
                        st.warning(
                            f"**Position Sizing**: Max loss ${trade.max_loss:.0f} per contract. "
                            f"Ensure this fits within your risk tolerance and account size. "
                            f"Never risk more than you can afford to lose."
                        )
                    
                    # Commission disclaimer
                    st.caption(
                        "*P&L figures exclude commissions, fees, and assignment costs. "
                        "Actual results will differ. Typical options commissions: $0.50-$0.65 per contract."
                    )
                    
                    # Regime warnings (PR #4)
                    regime_warnings = trade.metrics.get('regime_warnings', [])
                    if regime_warnings:
                        for warning in regime_warnings:
                            st.warning(f"⚠️ {warning}")
                    
                    # Expert Analysis
                    st.markdown("#### 🧠 Expert Analysis")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Market Regime", trade.metrics.get('regime', 'N/A'))
                    gex_val = trade.metrics.get('gex', 0)
                    m2.metric("Net GEX ($)", f"${gex_val:,.0f}", delta="Bullish" if gex_val > 0 else "Bearish/Vol")
                    m3.metric("Trend (ADX)", f"{trade.metrics.get('adx', 0):.1f}")
                    m4.metric("Vol (HV20)", f"{trade.metrics.get('hv20', 0):.1%}")
                    
                    # Show HV ratio for regime context
                    hv5 = trade.metrics.get('hv5', 0)
                    hv20 = trade.metrics.get('hv20', 0)
                    if hv20 > 0:
                        hv_ratio = hv5 / hv20
                        st.caption(f"HV5/HV20 ratio: {hv_ratio:.2f} — {trade.metrics.get('regime_description', '')}")
                    
                    st.divider()
                    
                    # Trade Greeks (PR #5)
                    if trade.greeks:
                        st.markdown("#### 📊 Position Greeks")
                        
                        # Check for missing/zero Greeks
                        greeks_delta = trade.greeks.get('delta', 0)
                        greeks_gamma = trade.greeks.get('gamma', 0)
                        greeks_vega = trade.greeks.get('vega', 0)
                        greeks_theta = trade.greeks.get('theta', 0)
                        
                        all_zero = all(v == 0 for v in [greeks_delta, greeks_gamma, greeks_vega, greeks_theta])
                        if all_zero:
                            st.error("**Greeks Unavailable** - Broker did not provide Greeks data. Stress test results will be unreliable.")
                        
                        g1, g2, g3, g4 = st.columns(4)
                        g1.metric("Delta (Δ)", f"{greeks_delta:+.2f}", 
                                 help="Directional exposure. +1 delta ≈ 100 shares long")
                        g2.metric("Gamma (Γ)", f"{greeks_gamma:+.4f}",
                                 help="Delta sensitivity. Negative = short gamma risk")
                        g3.metric("Vega (V)", f"{greeks_vega:+.2f}",
                                 help="Vol sensitivity. Negative = hurt by vol increase")
                        g4.metric("Theta (Θ)", f"{greeks_theta:+.2f}",
                                 help="Time decay. Negative = lose value daily")
                        
                        source = trade.greeks.get('source', 'UNKNOWN')
                        st.caption(f"Greeks source: {source}")
                        
                        # Stress Test (PR #6)
                        st.markdown("#### 🔥 Scenario Stress Test")
                        st.caption("⚠️ Approximation: Uses second-order Taylor expansion. Less reliable for moves >5%.")
                        
                        # Get spot price from metrics
                        spot_price = trade.metrics.get('spot', 100.0)  # Default if not available
                        
                        # Run stress test for this trade
                        stress_engine = StressTestEngine()
                        stress_result = stress_engine.run_stress_test(
                            delta=trade.greeks.get('delta', 0),
                            gamma=trade.greeks.get('gamma', 0),
                            vega=trade.greeks.get('vega', 0),
                            spot=spot_price
                        )
                        
                        # Display worst/best case summary
                        wc1, wc2 = st.columns(2)
                        if stress_result.worst_case_scenario:
                            wc1.metric(
                                "Worst Case", 
                                f"${stress_result.worst_case_pnl:+,.0f}",
                                delta=stress_result.worst_case_scenario.name,
                                delta_color="inverse"
                            )
                        if stress_result.best_case_scenario:
                            wc2.metric(
                                "Best Case", 
                                f"${stress_result.best_case_pnl:+,.0f}",
                                delta=stress_result.best_case_scenario.name
                            )
                        
                        # Show scenario table
                        stress_data = []
                        for sr in stress_result.scenario_results:
                            stress_data.append({
                                "Scenario": sr.scenario.name,
                                "Est. P&L": f"${sr.estimated_pnl:+,.0f}",
                                "Δ P&L": f"${sr.delta_contribution:+,.0f}",
                                "Γ P&L": f"${sr.gamma_contribution:+,.0f}",
                                "V P&L": f"${sr.vega_contribution:+,.0f}",
                                "Status": "⚠️" if sr.exceeds_threshold else ("🔴" if sr.severity == "SEVERE_LOSS" else "✅")
                            })
                        
                        stress_df = pd.DataFrame(stress_data)
                        st.dataframe(stress_df, hide_index=True, use_container_width=True)
                        
                        if stress_result.has_threshold_breach:
                            st.error(f"⚠️ {len(stress_result.breach_scenarios)} scenario(s) exceed loss threshold")
                        
                        # Gap/Overnight risk warning
                        st.warning(
                            "**Overnight Risk**: These scenarios do not model gap risk. Markets can open "
                            "significantly higher or lower than previous close. Options positions held overnight "
                            "are exposed to gap moves that may exceed modeled worst-case scenarios."
                        )
                    
                    st.divider()
                    
                    # Legs
                    st.markdown("**Legs**")
                    legs_df = pd.DataFrame([l.__dict__ for l in trade.legs])
                    st.dataframe(legs_df, hide_index=True)
                    
                    # Analysis Summary (conditioned on actual confidence)
                    if trade.confidence_score >= 70 and trade.pop is not None:
                        st.info(
                            f"**Analysis**: {trade.strategy_name} on {trade.ticker} shows favorable metrics. "
                            f"Break-even range: {trade.breakevens}. "
                            f"**Verify independently before trading.**"
                        )
                    elif trade.confidence_score >= 50:
                        st.warning(
                            f"**Moderate Confidence**: {trade.strategy_name} on {trade.ticker}. "
                            f"Some metrics are favorable but POP may be unverified. "
                            f"Break-even range: {trade.breakevens}. **Requires additional analysis.**"
                        )
                    else:
                        st.error(
                            f"**Low Confidence**: Insufficient verified data for {trade.strategy_name} on {trade.ticker}. "
                            f"Do NOT rely on this analysis for trading decisions."
                        )
                    
                    # Save to Journal button (PR #7)
                    if trade.is_tradable:
                        if st.button(f"📓 Save to Journal", key=f"save_{i}"):
                            journal = TradeJournal()
                            stress_summary = {
                                'worst_case_scenario': stress_result.worst_case_scenario.name if stress_result.worst_case_scenario else '',
                                'worst_case_pnl': stress_result.worst_case_pnl
                            } if 'stress_result' in dir() else {}
                            entry_id = journal.save_trade(
                                trade, 
                                regime_label=trade.metrics.get('regime', ''),
                                stress_summary=stress_summary
                            )
                            st.success(f"✅ Trade saved to journal with ID: {entry_id}")
        
        # Journal Tab (PR #7)
        with tab3:
            st.markdown("### 📓 Paper Trading Journal")
            st.caption("Track paper trades and validate strategy performance over time. All metrics based on user-logged outcomes only.")
            
            # Initialize journal
            journal = TradeJournal()
            calibration = CalibrationEngine(journal)
            
            # Journal stats
            j1, j2, j3 = st.columns(3)
            open_count = journal.db.count(status=TradeStatus.OPEN.value)
            closed_count = journal.db.count(status=TradeStatus.CLOSED.value)
            j1.metric("Open Trades", open_count)
            j2.metric("Closed Trades", closed_count)
            j3.metric("Total", open_count + closed_count)
            
            # Sub-tabs for journal views
            jtab1, jtab2, jtab3 = st.tabs(["📂 Open Trades", "✅ Closed Trades", "📊 Calibration"])
            
            with jtab1:
                st.markdown("#### Open Paper Trades")
                open_trades = journal.get_open_trades()
                
                if not open_trades:
                    st.info("No open trades in journal. Save trades from the Detailed Ticket tab.")
                else:
                    for entry in open_trades:
                        with st.expander(f"{entry.ticker} - {entry.strategy_name} ({entry.id})", expanded=False):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Entry Price", f"${entry.entry_price:,.2f}")
                            c2.metric("Confidence", f"{entry.confidence_score}/100")
                            c3.metric("Regime", entry.regime_label or "N/A")
                            
                            st.caption(f"Opened: {entry.entry_timestamp[:10]}")
                            st.caption(f"Description: {entry.description}")
                            
                            # Greeks at entry
                            st.markdown("**Greeks at Entry:**")
                            st.text(f"Δ={entry.entry_delta:+.2f} | Γ={entry.entry_gamma:+.4f} | V={entry.entry_vega:+.2f} | Θ={entry.entry_theta:+.2f}")
                            
                            # Stress at entry
                            if entry.worst_case_scenario:
                                st.markdown(f"**Worst Stress:** {entry.worst_case_scenario}: ${entry.worst_case_pnl:+,.0f}")
                            
                            # Close trade form
                            st.markdown("---")
                            st.markdown("**Close Trade:**")
                            exit_price = st.number_input(
                                "Exit Price (credit=positive, debit=negative)", 
                                value=0.0, 
                                key=f"exit_{entry.id}"
                            )
                            close_notes = st.text_input("Closing notes", key=f"notes_{entry.id}")
                            
                            if st.button(f"Close Trade", key=f"close_{entry.id}"):
                                closed = journal.close_trade(entry.id, exit_price, close_notes)
                                if closed:
                                    st.success(f"✅ Trade closed. Realized P&L: ${closed.realized_pnl:+,.2f}")
                                    st.rerun()
            
            with jtab2:
                st.markdown("#### Closed Paper Trades")
                closed_trades = journal.get_closed_trades()
                
                if not closed_trades:
                    st.info("No closed trades yet. Close open trades to see performance.")
                else:
                    # Summary table
                    closed_data = []
                    for entry in closed_trades:
                        closed_data.append({
                            "ID": entry.id,
                            "Ticker": entry.ticker,
                            "Strategy": entry.strategy_name,
                            "Entry": f"${entry.entry_price:,.2f}",
                            "Exit": f"${entry.exit_price:,.2f}" if entry.exit_price else "N/A",
                            "P&L": f"${entry.realized_pnl:+,.2f}" if entry.realized_pnl else "N/A",
                            "Result": "✅ Win" if (entry.realized_pnl and entry.realized_pnl > 0) else "❌ Loss",
                            "Regime": entry.regime_label or "N/A"
                        })
                    
                    closed_df = pd.DataFrame(closed_data)
                    st.dataframe(closed_df, hide_index=True, use_container_width=True)
            
            with jtab3:
                st.markdown("#### Calibration Metrics")
                st.caption("⚠️ All metrics based ONLY on user-logged outcomes. No simulated or inferred data.")
                
                metrics = calibration.compute_metrics()
                
                if metrics.closed_trades == 0:
                    st.info("Close some trades to see calibration metrics.")
                else:
                    # Summary metrics
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Win Rate", f"{metrics.win_rate:.1%}")
                    m2.metric("Total P&L", f"${metrics.total_pnl:+,.2f}")
                    m3.metric("Avg P&L", f"${metrics.average_pnl:+,.2f}")
                    m4.metric("Closed", metrics.closed_trades)
                    
                    st.divider()
                    
                    # By strategy
                    st.markdown("##### Performance by Strategy")
                    if metrics.by_strategy:
                        strat_data = []
                        for strat, data in metrics.by_strategy.items():
                            strat_data.append({
                                "Strategy": strat,
                                "Trades": data['count'],
                                "Win Rate": f"{data['win_rate']:.1%}",
                                "Total P&L": f"${data['total_pnl']:+,.2f}",
                                "Avg P&L": f"${data['average_pnl']:+,.2f}"
                            })
                        st.dataframe(pd.DataFrame(strat_data), hide_index=True, use_container_width=True)
                    
                    st.divider()
                    
                    # Score calibration
                    st.markdown("##### Score vs Outcome Calibration")
                    st.caption("Does higher confidence correlate with better outcomes?")
                    if metrics.score_vs_outcome:
                        score_data = []
                        for bin_name, data in metrics.score_vs_outcome.items():
                            score_data.append({
                                "Score Bin": bin_name,
                                "Trades": data['count'],
                                "Win Rate": f"{data['win_rate']:.1%}",
                                "Avg P&L": f"${data['avg_pnl']:+,.2f}"
                            })
                        st.dataframe(pd.DataFrame(score_data), hide_index=True, use_container_width=True)
