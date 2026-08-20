"""
NSE Stock Screener — Interactive Analysis Engine
------------------------------------------------
A Streamlit + yfinance based screener for NSE (.NS) stocks.
Combines 3 customizable scoring pillars:
1. Fundamental (CANSLIM-7)
2. Technical (10-Point Technical System)
3. Relative Strength (Broad Market + Sector Peer RS)

Run with: streamlit run app.py
"""

import numpy as np

# --- Compatibility patch for pandas_ta on newer numpy ---
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import time
import pandas as pd
import streamlit as st
import yfinance as yf
import pandas_ta as ta

# ----------------------------------------------------------------------------------
# Page config & dark theme styling
# ----------------------------------------------------------------------------------
st.set_page_config(page_title="NSE Stock Screener", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; }
    section[data-testid="stSidebar"] { background-color: #131722; }
    h1, h2, h3 { color: #e8eaed; }
    .metric-label { color: #9aa0a6; }
    div[data-testid="stMetricValue"] { color: #22c55e; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 NSE Stock Screener — Interactive Engine")
st.caption("Customizable Fundamental (CANSLIM-7) + Technical (10-Point) + Relative Strength Scoring System.")

# ----------------------------------------------------------------------------------
# Constants & Default Parameter Maps
# ----------------------------------------------------------------------------------
DEFAULT_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "TRENT.NS", "HAL.NS", "TATAMOTORS.NS", "BAJFINANCE.NS", "LT.NS",
    "SBIN.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS",
]
BENCHMARK = "^NSEI"

DEFAULT_FUND_PARAMS = {
    "C": "C: Current EPS Growth > 15%",
    "A": "A: Annual Revenue Growth > 10%",
    "N": "N: Near 52-Week High (within 25%)",
    "S": "S: Supply/Demand (Tight Base Consolidation)",
    "L": "L: Leader Relative Strength (Daily RSI > 55)",
    "I": "I: Institutional Ownership > 30%",
    "M": "M: Market Direction (Nifty > 200 DMA)",
}

DEFAULT_TECH_PARAMS = {
    "T1": "T1: Close > 200 DMA and near 50 DMA (within 5%)",
    "T2": "T2: Tight consolidation near 50/20 DMA",
    "T3": "T3: Early Stage 2 Proximity (Close <= 1.25 * 200 DMA)",
    "T4": "T4: 200 DMA & 50 DMA Sloping Up (5 bars)",
    "T5": "T5: Monthly RSI > 50 & Rising",
    "T6": "T6: Weekly RSI > 50 & Rising",
    "T7": "T7: Daily RSI > 50 & Rising",
    "T8": "T8: Monthly MACD Line Rising",
    "T9": "T9: Weekly MACD Positive Crossover & Rising",
    "T10": "T10: Daily MACD Line Rising",
}

DEFAULT_RS_PARAMS = {
    "RS1": "RS1: Broad Market RS vs Nifty 50 (^NSEI)",
    "RS2": "RS2: Sector Peer Relative Strength",
}

# Session State Initialization for Parameter Toggles
for p_key in DEFAULT_FUND_PARAMS:
    if f"fund_{p_key}" not in st.session_state:
        st.session_state[f"fund_{p_key}"] = True

for p_key in DEFAULT_TECH_PARAMS:
    if f"tech_{p_key}" not in st.session_state:
        st.session_state[f"tech_{p_key}"] = True

for p_key in DEFAULT_RS_PARAMS:
    if f"rs_{p_key}" not in st.session_state:
        st.session_state[f"rs_{p_key}"] = True


# ----------------------------------------------------------------------------------
# Customization Modals (Dialogs)
# ----------------------------------------------------------------------------------
@st.dialog("⚙️ Customize Fundamental Parameters")
def customize_fundamental_modal():
    st.write("Select which CANSLIM-7 criteria to include in the Fundamental Score calculation:")
    for k, label in DEFAULT_FUND_PARAMS.items():
        st.session_state[f"fund_{k}"] = st.checkbox(label, value=st.session_state[f"fund_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_fund"):
        for k in DEFAULT_FUND_PARAMS:
            st.session_state[f"fund_{k}"] = True
        st.rerun()
    if col2.button("Apply & Close", key="apply_fund"):
        st.rerun()


@st.dialog("⚙️ Customize Technical Parameters")
def customize_technical_modal():
    st.write("Select which rules to include in the 10-Point Technical Score calculation:")
    for k, label in DEFAULT_TECH_PARAMS.items():
        st.session_state[f"tech_{k}"] = st.checkbox(label, value=st.session_state[f"tech_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_tech"):
        for k in DEFAULT_TECH_PARAMS:
            st.session_state[f"tech_{k}"] = True
        st.rerun()
    if col2.button("Apply & Close", key="apply_tech"):
        st.rerun()


@st.dialog("⚙️ Customize Relative Strength Parameters")
def customize_rs_modal():
    st.write("Select which relative strength benchmarks to include:")
    for k, label in DEFAULT_RS_PARAMS.items():
        st.session_state[f"rs_{k}"] = st.checkbox(label, value=st.session_state[f"rs_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_rs"):
        for k in DEFAULT_RS_PARAMS:
            st.session_state[f"rs_{k}"] = True
        st.rerun()
    if col2.button("Apply & Close", key="apply_rs"):
        st.rerun()


# ----------------------------------------------------------------------------------
# Data Fetching & Resampling (Cached with 1-Hour Time-to-Live)
# ----------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_daily(ticker: str, period: str = "2y", retries: int = 2):
    for attempt in range(retries):
        try:
            df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
            if df is None or df.empty or len(df) < 30:
                time.sleep(0.3)
                continue
            required_cols = ["Open", "High", "Low", "Close", "Volume"]
            if not all(col in df.columns for col in required_cols):
                continue
            df.index = pd.to_datetime(df.index)
            df = df[required_cols].copy().replace([np.inf, -np.inf], np.nan).dropna()
            if len(df) >= 30:
                return df
        except Exception:
            time.sleep(0.3)
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_info(ticker: str) -> dict:
    default_info = {
        "earningsGrowth": None, "revenueGrowth": None, "fiftyTwoWeekHigh": None,
        "currentPrice": None, "regularMarketPrice": None, "heldPercentInstitutions": None,
        "sector": "Unknown",
    }
    try:
        raw_info = yf.Ticker(ticker).info
        if isinstance(raw_info, dict):
            default_info.update(raw_info)
    except Exception:
        pass
    return default_info


def resample_ohlc(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    if daily is None or daily.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    try:
        return daily.resample(rule).agg(agg).dropna()
    except ValueError:
        fallback_rule = "M" if rule == "ME" else "W"
        try:
            return daily.resample(fallback_rule).agg(agg).dropna()
        except Exception:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    except Exception:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


def slope_up(series: pd.Series, lookback: int = 5) -> bool:
    s = series.dropna()
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])


def is_rising(series: pd.Series, lookback: int = 2) -> bool:
    s = series.dropna()
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])


# ----------------------------------------------------------------------------------
# Calculation Engines
# ----------------------------------------------------------------------------------
def compute_fundamental_score(info: dict, daily: pd.DataFrame, bench_daily: pd.DataFrame):
    raw_results = {}
    
    eps_growth = info.get("earningsGrowth")
    rev_growth = info.get("revenueGrowth")
    fifty2_high = info.get("fiftyTwoWeekHigh")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    inst_hold = info.get("heldPercentInstitutions")

    # C
    raw_results["C"] = bool(eps_growth is not None and eps_growth > 0.15)
    # A
    raw_results["A"] = bool(rev_growth is not None and rev_growth > 0.10)
    # N
    raw_results["N"] = bool(fifty2_high and current_price and current_price >= 0.75 * fifty2_high)
    # S
    if daily is not None and len(daily) >= 50:
        close = daily["Close"]
        sma50 = close.rolling(50).mean().iloc[-1]
        vol_std = close.tail(10).std() / close.tail(10).mean() * 100
        near_50 = abs(close.iloc[-1] - sma50) / sma50 * 100 if pd.notna(sma50) else 99
        raw_results["S"] = bool(near_50 <= 5 and vol_std <= 6)
    else:
        raw_results["S"] = False
    # L
    if daily is not None and len(daily) >= 14:
        rsi = ta.rsi(daily["Close"], length=14)
        raw_results["L"] = bool(rsi is not None and not rsi.empty and rsi.iloc[-1] > 55)
    else:
        raw_results["L"] = False
    # I
    raw_results["I"] = bool(inst_hold is not None and inst_hold > 0.30)
    # M
    if bench_daily is not None and len(bench_daily) >= 200:
        bench_close = bench_daily["Close"]
        bench_sma200 = bench_close.rolling(200).mean().iloc[-1]
        raw_results["M"] = bool(bench_close.iloc[-1] > bench_sma200)
    else:
        raw_results["M"] = False

    active_passed = 0
    active_total = 0
    passed_labels = []

    for k in DEFAULT_FUND_PARAMS:
        if st.session_state.get(f"fund_{k}", True):
            active_total += 1
            if raw_results.get(k, False):
                active_passed += 1
                passed_labels.append(k)

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    status_str = f"{active_passed}/{active_total} active ({', '.join(passed_labels) if passed_labels else 'None'})"
    
    return round(norm_score, 2), status_str


def compute_technical_score(daily: pd.DataFrame):
    if daily is None or len(daily) < 30:
        return 0.0, "0/0 active"

    close = daily["Close"]
    d = daily.copy()
    d["SMA20"] = close.rolling(20).mean()
    d["SMA50"] = close.rolling(50).mean()
    d["SMA200"] = close.rolling(200).mean()
    d["RSI14"] = ta.rsi(close, length=14)

    last_close = close.iloc[-1]
    sma20 = d["SMA20"].iloc[-1]
    sma50 = d["SMA50"].iloc[-1]
    sma200 = d["SMA200"].iloc[-1]
    rsi_daily = d["RSI14"].iloc[-1] if not d["RSI14"].empty else np.nan

    weekly = resample_ohlc(daily, "W")
    monthly = resample_ohlc(daily, "ME")

    rsi_weekly = ta.rsi(weekly["Close"], length=14) if not weekly.empty else None
    rsi_monthly = ta.rsi(monthly["Close"], length=14) if not monthly.empty else None

    macd_w = ta.macd(weekly["Close"]) if not weekly.empty and len(weekly) > 3 else None
    macd_m = ta.macd(monthly["Close"]) if not monthly.empty and len(monthly) > 3 else None
    macd_d = ta.macd(close) if len(close) > 3 else None

    raw = {}
    
    # T1: Close > 200 DMA & near 50 DMA
    near_50_pct = abs(last_close - sma50) / sma50 * 100 if pd.notna(sma50) else 99
    raw["T1"] = bool(pd.notna(sma200) and last_close > sma200 and near_50_pct <= 5)

    # T2: Tight consolidation near 50 or 20 DMA
    vol_pct = close.tail(10).std() / close.tail(10).mean() * 100
    near_20_pct = abs(last_close - sma20) / sma20 * 100 if pd.notna(sma20) else 99
    raw["T2"] = bool((near_50_pct <= 5 or near_20_pct <= 5) and vol_pct <= 6)

    # T3: Early Stage 2 Proximity
    raw["T3"] = bool(pd.notna(sma200) and last_close <= 1.25 * sma200 and last_close > sma200)

    # T4: Slopes of 50 and 200 DMA
    raw["T4"] = bool(slope_up(d["SMA50"], 5) and slope_up(d["SMA200"], 5))

    # T5: Monthly RSI > 50 & rising
    raw["T5"] = bool(rsi_monthly is not None and not rsi_monthly.empty and rsi_monthly.iloc[-1] > 50 and is_rising(rsi_monthly, 2))

    # T6: Weekly RSI > 50 & rising
    raw["T6"] = bool(rsi_weekly is not None and not rsi_weekly.empty and rsi_weekly.iloc[-1] > 50 and is_rising(rsi_weekly, 2))

    # T7: Daily RSI > 50 & rising
    raw["T7"] = bool(pd.notna(rsi_daily) and rsi_daily > 50 and is_rising(d["RSI14"], 2))

    # T8: Monthly MACD rising
    raw["T8"] = bool(macd_m is not None and not macd_m.empty and is_rising(macd_m.iloc[:, 0], 2))

    # T9: Weekly MACD positive cross & rising
    if macd_w is not None and not macd_w.empty:
        raw["T9"] = bool(macd_w.iloc[-1, 0] > macd_w.iloc[-1, 2] and macd_w.iloc[-1, 0] > 0 and is_rising(macd_w.iloc[:, 0], 2))
    else:
        raw["T9"] = False

    # T10: Daily MACD line rising
    raw["T10"] = bool(macd_d is not None and not macd_d.empty and is_rising(macd_d.iloc[:, 0], 2))

    active_passed = 0
    active_total = 0

    for k in DEFAULT_TECH_PARAMS:
        if st.session_state.get(f"tech_{k}", True):
            active_total += 1
            if raw.get(k, False):
                active_passed += 1

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    status_str = f"{active_passed}/{active_total} active"

    return round(norm_score, 2), status_str


def compute_relative_strength_score(daily: pd.DataFrame, bench_daily: pd.DataFrame, sector_avg_ret: float, lookback: int = 63):
    if daily is None or bench_daily is None or len(daily) < 10 or len(bench_daily) < 10:
        return 0.0, "0/0 active"

    n = min(lookback, len(daily) - 1, len(bench_daily) - 1)
    stock_ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-n] - 1) * 100
    bench_ret = (bench_daily["Close"].iloc[-1] / bench_daily["Close"].iloc[-n] - 1) * 100

    outperform_bench = stock_ret - bench_ret
    outperform_sector = stock_ret - sector_avg_ret if pd.notna(sector_avg_ret) else outperform_bench

    score_rs1 = float(np.clip(2.5 + (outperform_bench / 10 * 2.5), 0, 5))
    score_rs2 = float(np.clip(2.5 + (outperform_sector / 10 * 2.5), 0, 5))

    pts_earned = 0.0
    pts_max = 0.0

    if st.session_state.get("rs_RS1", True):
        pts_earned += score_rs1
        pts_max += 5.0

    if st.session_state.get("rs_RS2", True):
        pts_earned += score_rs2
        pts_max += 5.0

    norm_score = (pts_earned / pts_max * 10) if pts_max > 0 else 0.0
    status_str = f"Broad RS: {outperform_bench:+.1f}% | Sector RS: {outperform_sector:+.1f}%"

    return round(norm_score, 2), status_str


# ----------------------------------------------------------------------------------
# Sidebar UI Controls
# ----------------------------------------------------------------------------------
st.sidebar.header("⚙️ Screener Controls")

st.sidebar.subheader("1. Universe Selection")
with st.sidebar.expander("📤 Upload CSV Universe (e.g. Nifty 500)", expanded=False):
    uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], label_visibility="collapsed")

csv_tickers = []
if uploaded_csv is not None:
    try:
        csv_df = pd.read_csv(uploaded_csv)
        symbol_col = next((c for c in csv_df.columns if c.strip().lower() == "symbol"), None)
        if symbol_col:
            csv_tickers = [
                f"{str(s).strip().upper()}.NS" if not str(s).strip().upper().endswith(".NS") else str(s).strip().upper()
                for s in csv_df[symbol_col].dropna().tolist() if str(s).strip()
            ]
            st.sidebar.success(f"Loaded {len(csv_tickers)} tickers.")
    except Exception as e:
        st.sidebar.error(f"Error reading CSV: {e}")

full_options = list(dict.fromkeys(DEFAULT_UNIVERSE + csv_tickers))
selected_universe = st.sidebar.multiselect("Active Tickers", options=full_options, default=(csv_tickers if csv_tickers else DEFAULT_UNIVERSE))
custom_raw = st.sidebar.text_input("Add Custom Tickers (comma-separated)", value="")
custom_tickers = [t.strip().upper() if t.strip().upper().endswith(".NS") else f"{t.strip().upper()}.NS" for t in custom_raw.split(",") if t.strip()]
universe = list(dict.fromkeys(selected_universe + custom_tickers))

st.sidebar.divider()

st.sidebar.subheader("2. Pillar Weights (Auto-Sum to 10)")
w_fund = st.sidebar.slider("Fundamental Weight", 0, 10, 3, key="w_fund")
w_tech = st.sidebar.slider("Technical Weight", 0, 10, 5, key="w_tech")
w_rs_calc = 10 - w_fund - w_tech

if w_rs_calc < 0:
    st.sidebar.error("Fundamental + Technical weight exceeds 10. Adjust sliders.")
    w_rs = 0
else:
    w_rs = w_rs_calc
    st.sidebar.metric("Relative Strength Weight", w_rs)

st.sidebar.divider()

st.sidebar.subheader("3. Pillar Customization Modals")
if st.sidebar.button("⚙️ Customize Fundamental (CANSLIM)", use_container_width=True):
    customize_fundamental_modal()

if st.sidebar.button("⚙️ Customize Technical (10-Point)", use_container_width=True):
    customize_technical_modal()

if st.sidebar.button("⚙️ Customize Relative Strength", use_container_width=True):
    customize_rs_modal()

st.sidebar.divider()
run_scan = st.sidebar.button("🔍 Run / Refresh Screening Scan", use_container_width=True)


# ----------------------------------------------------------------------------------
# Main Screening Execution & Rendering
# ----------------------------------------------------------------------------------
if run_scan:
    if not universe:
        st.warning("Please select at least one ticker in the sidebar.")
    else:
        st.cache_data.clear()  # Purge stale cache on button click to match fresh live data
        with st.spinner("Fetching benchmark and stock data..."):
            bench_daily = fetch_daily(BENCHMARK)
            
            stock_data = {}
            sector_returns = {}
            
            progress = st.progress(0, text="Fetching price histories...")
            for i, tkr in enumerate(universe):
                progress.progress((i + 1) / len(universe), text=f"Fetching {tkr}...")
                daily = fetch_daily(tkr)
                info = fetch_info(tkr)
                if daily is not None:
                    stock_data[tkr] = {"daily": daily, "info": info}
                    if len(daily) >= 63:
                        ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-63] - 1) * 100
                        sec = info.get("sector", "Unknown")
                        sector_returns.setdefault(sec, []).append(ret)
            progress.empty()

            sector_avg = {sec: np.mean(rets) for sec, rets in sector_returns.items() if rets}

            results = []
            skipped = []

            for tkr in universe:
                if tkr not in stock_data:
                    skipped.append(tkr)
                    continue
                
                daily = stock_data[tkr]["daily"]
                info = stock_data[tkr]["info"]
                sec = info.get("sector", "Unknown")
                sec_ret = sector_avg.get(sec, np.nan)

                fund_score, fund_status = compute_fundamental_score(info, daily, bench_daily)
                tech_score, tech_status = compute_technical_score(daily)
                rs_score, rs_status = compute_relative_strength_score(daily, bench_daily, sec_ret)

                total_score = (fund_score * w_fund + tech_score * w_tech + rs_score * w_rs) / 10

                results.append({
                    "Ticker": tkr,
                    "Total Score": round(total_score, 2),
                    "Fundamental Score": fund_score,
                    "Technical Score": tech_score,
                    "Relative Strength Score": rs_score,
                    "Tech Passed": tech_status,
                    "CANSLIM Hits": fund_status,
                    "RS Details": rs_status,
                    "Sector": sec,
                })

            st.session_state["results_df"] = pd.DataFrame(results)
            st.session_state["skipped_tickers"] = skipped

if "results_df" in st.session_state:
    df = st.session_state["results_df"]
    skipped = st.session_state.get("skipped_tickers", [])

    if not df.empty:
        df = df.sort_values("Total Score", ascending=False).reset_index(drop=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Tickers Screened", len(df))
        col2.metric("Top Score", f"{df['Total Score'].max():.2f}")
        col3.metric("Avg Total Score", f"{df['Total Score'].mean():.2f}")

        st.subheader("📋 Screening Results")
        display_cols = [
            "Ticker", "Total Score", "Fundamental Score", "Technical Score", "Relative Strength Score",
            "Tech Passed", "CANSLIM Hits", "RS Details", "Sector"
        ]
        
        styled = (
            df[display_cols]
            .style.background_gradient(subset=["Total Score"], cmap="Greens")
            .format({
                "Total Score": "{:.2f}",
                "Fundamental Score": "{:.2f}",
                "Technical Score": "{:.2f}",
                "Relative Strength Score": "{:.2f}",
            })
        )
        st.dataframe(styled, use_container_width=True, height=min(600, 60 + 35 * len(df)))

        st.download_button(
            "⬇️ Download Results CSV",
            data=df[display_cols].to_csv(index=False).encode("utf-8"),
            file_name="nse_screener_results.csv",
            mime="text/csv",
        )

    if skipped:
        st.warning(f"⚠️ {len(skipped)} ticker(s) skipped due to missing/insufficient data: {', '.join(skipped)}")
else:
    st.info("Configure universe and weights in the sidebar, then click **Run / Refresh Screening Scan**.")

# ----------------------------------------------------------------------------------
# Footer & Disclaimer
# ----------------------------------------------------------------------------------
st.divider()
st.caption(
    "**Disclaimer:** This application is strictly for educational and informational purposes "
    "and does not constitute investment or financial advice. Quantitative models, technical indicators, "
    "and CANSLIM scoring filters are algorithmic abstractions based on historical data and do not guarantee "
    "future returns or market success. Market parameters, pricing feeds, and fundamentals provided via third-party APIs "
    "(such as Yahoo Finance) may contain delays, inaccuracies, or incomplete historical data. Always perform "
    "independent, rigorous research and consult a SEBI-registered financial advisor before making any trading "
    "or investment decisions."
)
st.markdown(
    "<div style='text-align: center; color: #9aa0a6; padding-top: 10px; font-size: 0.85rem;'>"
    "💬 For any feedback or queries, contact the creator at <b>vkiyer@hotmail.com</b>"
    "</div>",
    unsafe_allow_html=True,
)