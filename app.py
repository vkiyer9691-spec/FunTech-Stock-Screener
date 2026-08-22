"""
NSE Stock Screener — Interactive Analysis Engine (Auth Gated, Admin Enabled & Supabase Persisted)
----------------------------------------------------------------------------------
Includes Enforced Main-Screen Supabase Authentication, Settings Persistence (Save/Load),
Admin Email Privilege Checking, Mobile-First Responsive CSS, Multi-Broker Auto-Parser, 
API Data-Drop Protection, Parallel Execution Engine, Chartink Integrator, and 1-Click TradingView Exporter.

Run with: streamlit run app.py
"""

import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

# --- Compatibility patch for pandas_ta on newer numpy ---
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import pandas as pd
import streamlit as st
import yfinance as yf
import pandas_ta as ta

# Optional Supabase Import with Graceful Fallback
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ----------------------------------------------------------------------------------
# Page Config & Mobile-First CSS Scaffolding
# ----------------------------------------------------------------------------------
st.set_page_config(
    page_title="NSE Stock Screener & Portfolio Evaluator", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .stButton > button, .stSelectbox, .stTextInput, .stMultiSelect {
        min-height: 44px !important;
    }
    div[data-testid="stMetricValue"] { 
        font-weight: 600; 
        font-size: clamp(1.2rem, 4vw, 1.8rem) !important;
    }
    button[data-testid="stBaseButton-popover"] {
        padding-top: 0.4rem;
        padding-bottom: 0.4rem;
        font-weight: 600;
        width: 100% !important;
        min-height: 44px !important;
    }
    @media only screen and (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] { flex-direction: column !important; gap: 1rem !important; }
        div[data-testid="column"] { width: 100% !important; min-width: 100% !important; white-space: normal !important; word-break: break-word !important; }
        .stButton > button { width: 100% !important; margin-bottom: 0.5rem; }
        div[data-baseweb="tab-list"] { gap: 2px !important; width: 100% !important; }
        button[data-baseweb="tab"] { padding: 8px 10px !important; font-size: 12px !important; flex-grow: 1 !important; text-align: center !important; }
        div[data-testid="stTable"], div[data-testid="stDataFrame"] { overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------------
# Constants, Defaults & Admin Access Control
# ----------------------------------------------------------------------------------
ADMIN_EMAILS = ["vkiyer@hotmail.com"][cite: 3]
BENCHMARK = "^NSEI"[cite: 3]

DEFAULT_FUND_PARAMS = {
    "C": "C: Current EPS Growth > 15%",
    "A": "A: Annual Revenue Growth > 10%",
    "N": "N: Near 52-Week High (within 25%)",
    "S": "S: Supply/Demand (Tight Base Consolidation)",
    "L": "L: Leader Relative Strength (Daily RSI > 55)",
    "I": "I: Institutional Ownership > 30%",
    "M": "M: Market Direction (Nifty > 200 DMA)",
}[cite: 3]

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
}[cite: 3]

DEFAULT_RS_PARAMS = {
    "RS1": "RS1: Broad Market RS vs Nifty 50 (^NSEI)",
    "RS2": "RS2: Sector Peer Relative Strength",
}[cite: 3]

SECTOR_MAP = {
    "Financial Services": "Fin Services", "Consumer Cyclical": "Cons Cyclical",
    "Consumer Defensive": "Cons Defensive", "Healthcare": "Healthcare",
    "Technology": "Tech", "Industrials": "Industrials", "Basic Materials": "Materials",
    "Energy": "Energy", "Utilities": "Utilities", "Real Estate": "Real Estate",
    "Communication Services": "Comm Services", "Unknown": "Unknown"
}[cite: 3]

BROKER_SYMBOL_HEADERS = [
    "instrument", "trading symbol", "tradingsymbol", "symbol", 
    "ticker", "company name", "stock name", "stock", "scrip name", "display name"
][cite: 3]

def is_admin(user) -> bool:
    if not user:
        return False
    email = user.get("email") if isinstance(user, dict) else getattr(user, "email", "")
    return email.lower() in [e.lower() for e in ADMIN_EMAILS][cite: 3]

# ----------------------------------------------------------------------------------
# Safe Supabase Helper & Persistence Engine
# ----------------------------------------------------------------------------------
def get_supabase_client():
    if not SUPABASE_AVAILABLE:
        return None
    url = str(st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url") or os.environ.get("SUPABASE_URL") or "").strip()[cite: 3]
    key = str(st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase", {}).get("key") or os.environ.get("SUPABASE_KEY") or "").strip()[cite: 3]
    if url and key and url != "None" and key != "None":
        try:
            return create_client(url, key)[cite: 3]
        except Exception:
            return None
    return None


def init_session_defaults():
    if "w_fund" not in st.session_state:
        st.session_state["w_fund"] = 4[cite: 3]
    if "w_tech" not in st.session_state:
        st.session_state["w_tech"] = 4[cite: 3]

    for k in DEFAULT_FUND_PARAMS:
        if f"fund_{k}" not in st.session_state:
            st.session_state[f"fund_{k}"] = True[cite: 3]

    for k in DEFAULT_TECH_PARAMS:
        if f"tech_{k}" not in st.session_state:
            st.session_state[f"tech_{k}"] = True[cite: 3]

    for k in DEFAULT_RS_PARAMS:
        if f"rs_{k}" not in st.session_state:
            st.session_state[f"rs_{k}"] = True[cite: 3]


def load_user_settings_from_db(user_id: str):
    supabase = get_supabase_client()[cite: 3]
    if not supabase or not user_id:
        return
    
    try:
        session = st.session_state.get("supabase_session")[cite: 3]
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)[cite: 3]

        response = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()[cite: 3]
        if response.data and len(response.data) > 0:
            data = response.data[0][cite: 3]
            st.session_state["w_fund"] = int(data.get("w_fund", 4))[cite: 3]
            st.session_state["w_tech"] = int(data.get("w_tech", 4))[cite: 3]
            
            fund_rules = data.get("fund_rules") or {}[cite: 3]
            for k in DEFAULT_FUND_PARAMS:
                st.session_state[f"fund_{k}"] = bool(fund_rules.get(k, True))[cite: 3]
                
            tech_rules = data.get("tech_rules") or {}[cite: 3]
            for k in DEFAULT_TECH_PARAMS:
                st.session_state[f"tech_{k}"] = bool(tech_rules.get(k, True))[cite: 3]

            rs_rules = data.get("rs_rules") or {}[cite: 3]
            for k in DEFAULT_RS_PARAMS:
                st.session_state[f"rs_{k}"] = bool(rs_rules.get(k, True))[cite: 3]
    except Exception as e:
        st.warning(f"Could not load saved settings: {e}")[cite: 3]


def save_user_settings_to_db():
    supabase = get_supabase_client()[cite: 3]
    user = st.session_state.get("user")[cite: 3]
    session = st.session_state.get("supabase_session")[cite: 3]
    
    if not supabase or not user:
        return

    if session and hasattr(session, "access_token"):
        supabase.postgrest.auth(session.access_token)[cite: 3]

    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)[cite: 3]
    if not user_id:
        return

    fund_dict = {k: st.session_state.get(f"fund_{k}", True) for k in DEFAULT_FUND_PARAMS}[cite: 3]
    tech_dict = {k: st.session_state.get(f"tech_{k}", True) for k in DEFAULT_TECH_PARAMS}[cite: 3]
    rs_dict = {k: st.session_state.get(f"rs_{k}", True) for k in DEFAULT_RS_PARAMS}[cite: 3]

    payload = {
        "user_id": user_id,
        "w_fund": st.session_state.get("w_fund", 4),
        "w_tech": st.session_state.get("w_tech", 4),
        "fund_rules": fund_dict,
        "tech_rules": tech_dict,
        "rs_rules": rs_dict,
        "updated_at": "now()"
    }[cite: 3]

    try:
        supabase.table("user_settings").upsert(payload).execute()[cite: 3]
    except Exception as e:
        st.error(f"Failed to save settings: {e}")[cite: 3]


def init_auth_session():
    if "user" not in st.session_state:
        st.session_state["user"] = None[cite: 3]
    if "supabase_session" not in st.session_state:
        st.session_state["supabase_session"] = None[cite: 3]
    init_session_defaults()


def render_login_screen():
    init_auth_session()
    supabase = get_supabase_client()[cite: 3]

    st.title("🔐 NSE Stock Screener")[cite: 3]
    st.caption("Please log in to access the Quantitative Analysis Engine.")[cite: 3]
    st.divider()[cite: 3]

    if not SUPABASE_AVAILABLE or supabase is None:
        st.warning("⚠️ **Supabase configuration not detected.**")[cite: 3]
        st.info("Configure `SUPABASE_URL` and `SUPABASE_KEY` in `.streamlit/secrets.toml` to enable auth & persistence.")[cite: 3]
        
        if st.button("Bypass Login (Developer / Local Mode)", use_container_width=True):[cite: 3]
            st.session_state["user"] = {"id": "local-dev-id", "email": "vkiyer@hotmail.com"}[cite: 3]
            st.session_state["supabase_session"] = None[cite: 3]
            st.rerun()[cite: 3]
        return False

    col1, col2 = st.columns([1, 1])[cite: 3]

    with col1:
        st.subheader("Account Access")[cite: 3]
        auth_mode = st.radio("Choose Mode", ["Login", "Sign Up"], key="auth_mode")[cite: 3]
        email = st.text_input("Email", key="auth_email")[cite: 3]
        password = st.text_input("Password", type="password", key="auth_pass")[cite: 3]

        if auth_mode == "Login":
            if st.button("Log In", use_container_width=True, type="primary"):[cite: 3]
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})[cite: 3]
                    st.session_state["user"] = res.user[cite: 3]
                    st.session_state["supabase_session"] = res.session[cite: 3]
                    
                    user_id = getattr(res.user, "id", None)[cite: 3]
                    if user_id:
                        load_user_settings_from_db(user_id)[cite: 3]
                    st.success("Login successful!")[cite: 3]
                    st.rerun()[cite: 3]
                except Exception as e:
                    st.error(f"Login failed: {e}")[cite: 3]
        else:
            if st.button("Create Account", use_container_width=True, type="primary"):[cite: 3]
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})[cite: 3]
                    if res.user and res.session:
                        st.session_state["user"] = res.user[cite: 3]
                        st.session_state["supabase_session"] = res.session[cite: 3]
                    st.success("Account created! Check your email or log in.")[cite: 3]
                except Exception as e:
                    st.error(f"Sign up failed: {e}")[cite: 3]

    with col2:
        st.markdown(
            """
            ### 🏛️ What's Inside:
            * **CANSLIM-7 Fundamental Engine:** Quantitative growth scoring.
            * **10-Point Technical System:** Multi-timeframe trend & momentum.
            * **Relative Strength Matrix:** Sector & Nifty 50 outperformance filters.
            * **Multi-Broker Portfolio Evaluator:** Auto-parse holdings.
            * **Chartink Strategy Integrator:** Seamless custom scanner sync.
            * **1-Click TradingView Exporter:** Instant watchlist sync.
            """
        )[cite: 3]

    return False

# Enforce Authentication Gate
if "user" not in st.session_state or st.session_state["user"] is None:
    render_login_screen()[cite: 3]
    st.stop()[cite: 3]

# Ensure user defaults exist in state
init_session_defaults()

# ----------------------------------------------------------------------------------
# Main App Header & User Info
# ----------------------------------------------------------------------------------
current_user = st.session_state["user"][cite: 3]
user_email = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", "User")[cite: 3]
user_is_admin = is_admin(current_user)[cite: 3]

st.sidebar.markdown(f"👤 **User:** `{user_email}`")[cite: 3]
if user_is_admin:
    st.sidebar.markdown("⭐ **Role:** `Administrator`")[cite: 3]

if st.sidebar.button("🚪 Log Out", use_container_width=True):[cite: 3]
    supabase = get_supabase_client()[cite: 3]
    if supabase:
        try:
            supabase.auth.sign_out()[cite: 3]
        except Exception:
            pass
    st.session_state.clear()[cite: 3]
    st.rerun()[cite: 3]

st.sidebar.divider()[cite: 3]

st.title("📊 NSE Stock Screener & Portfolio Evaluator")[cite: 3]
st.caption("Quantitative Multi-Pillar Engine for Stock Market Traders and Investors.")[cite: 3]

# ----------------------------------------------------------------------------------
# Helper Functions & Data Fetchers
# ----------------------------------------------------------------------------------
def abbreviate_sector(sector_raw: str) -> str:
    if not sector_raw or sector_raw == "Unknown":
        return "Unknown"
    return SECTOR_MAP.get(sector_raw.strip(), sector_raw.strip())[cite: 3]


def parse_broker_symbols(df: pd.DataFrame) -> list:
    matched_col = None
    cleaned_cols = {str(c).strip().lower(): c for c in df.columns}[cite: 3]
    
    for key in BROKER_SYMBOL_HEADERS:
        if key in cleaned_cols:
            matched_col = cleaned_cols[key][cite: 3]
            break
            
    if not matched_col:
        return []

    raw_symbols = df[matched_col].dropna().astype(str).tolist()[cite: 3]
    formatted_symbols = []
    
    for sym in raw_symbols:
        clean = sym.strip().upper()[cite: 3]
        clean = clean.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-BE", "").strip()[cite: 3]
        if clean and not clean.startswith("^"):
            formatted_symbols.append(f"{clean}.NS" if not clean.endswith(".NS") else clean)[cite: 3]
            
    return list(dict.fromkeys(formatted_symbols))[cite: 3]


def parse_chartink_input(text: str) -> list:
    """Extracts ticker symbols from raw Chartink copy-pastes or custom text."""
    if not text:
        return []
    tokens = re.findall(r'[A-Za-z0-9\-]+', text.upper())
    formatted = []
    skip_keywords = {"SYMBOL", "NAME", "SR", "NO", "PRICE", "CHANGE", "VOLUME", "PERC", "CHG", "NSE"}
    for t in tokens:
        clean = t.replace(".NS", "").strip()
        if clean and clean not in skip_keywords and not clean.isdigit():
            formatted.append(f"{clean}.NS")
    return list(dict.fromkeys(formatted))


@st.cache_data(ttl=86400, show_spinner=False)
def load_default_nifty500():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"[cite: 3]
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}[cite: 3]
        df = pd.read_csv(url, storage_options=headers)[cite: 3]
        symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)[cite: 3]
        if symbol_col:
            return [f"{str(s).strip().upper()}.NS" for s in df[symbol_col].dropna().tolist() if str(s).strip()][cite: 3]
    except Exception:
        pass
    return [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "AUBANK.NS", "TRENT.NS", "HAL.NS", "TATAMOTORS.NS", "BAJFINANCE.NS",
        "LT.NS", "SBIN.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS"
    ][cite: 3]

DEFAULT_UNIVERSE = load_default_nifty500()[cite: 3]

# ----------------------------------------------------------------------------------
# Dialog Modals with Database Sync
# ----------------------------------------------------------------------------------
@st.dialog("⚙️ Customize Fundamental Parameters")
def customize_fundamental_modal():
    st.write("Select CANSLIM-7 criteria to include:")[cite: 3]
    for k, label in DEFAULT_FUND_PARAMS.items():
        st.session_state[f"fund_{k}"] = st.checkbox(label, value=st.session_state.get(f"fund_{k}", True))[cite: 3]
    
    col1, col2 = st.columns([1, 1])[cite: 3]
    if col1.button("Restore Defaults", key="reset_fund"):
        for k in DEFAULT_FUND_PARAMS:
            st.session_state[f"fund_{k}"] = True[cite: 3]
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]
    if col2.button("Apply & Save", key="apply_fund"):
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]


@st.dialog("⚙️ Customize Technical Parameters")
def customize_technical_modal():
    st.write("Select rules to include in Technical Score:")[cite: 3]
    for k, label in DEFAULT_TECH_PARAMS.items():
        st.session_state[f"tech_{k}"] = st.checkbox(label, value=st.session_state.get(f"tech_{k}", True))[cite: 3]
    
    col1, col2 = st.columns([1, 1])[cite: 3]
    if col1.button("Restore Defaults", key="reset_tech"):
        for k in DEFAULT_TECH_PARAMS:
            st.session_state[f"tech_{k}"] = True[cite: 3]
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]
    if col2.button("Apply & Save", key="apply_tech"):
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]


@st.dialog("⚙️ Customize Relative Strength Parameters")
def customize_rs_modal():
    st.write("Select relative strength benchmarks to include:")[cite: 3]
    for k, label in DEFAULT_RS_PARAMS.items():
        st.session_state[f"rs_{k}"] = st.checkbox(label, value=st.session_state.get(f"rs_{k}", True))[cite: 3]
    
    col1, col2 = st.columns([1, 1])[cite: 3]
    if col1.button("Restore Defaults", key="reset_rs"):
        for k in DEFAULT_RS_PARAMS:
            st.session_state[f"rs_{k}"] = True[cite: 3]
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]
    if col2.button("Apply & Save", key="apply_rs"):
        save_user_settings_to_db()[cite: 3]
        st.rerun()[cite: 3]


@st.dialog("📊 Detailed Pillar Score Breakdown", width="large")
def show_pillar_details_modal(row_data):
    ticker = row_data['Ticker']
    st.subheader(f"Symbol: {ticker.replace('.NS', '')}")[cite: 3]
    st.caption(f"Sector: {row_data['Sector']} | Overall Score: {row_data['Total Score']:.2f} / 10")[cite: 3]
    
    tab_f, tab_t, tab_rs, tab_chart = st.tabs([
        "🏛️ Fundamental (CANSLIM)", 
        "📈 Technical Momentum", 
        "⚡ Relative Strength",
        "📉 Interactive Charts"
    ])
    
    with tab_f:
        st.markdown(f"**Fundamental Score:** `{row_data['Fundamental Score']:.2f} / 10`")[cite: 3]
        raw_fund = row_data.get("raw_fund", {})[cite: 3]
        fund_items = []
        for k, label in DEFAULT_FUND_PARAMS.items():
            status = "✅ Pass" if raw_fund.get(k, False) else "❌ Fail"[cite: 3]
            active = "Active" if st.session_state.get(f"fund_{k}", True) else "Disabled"[cite: 3]
            fund_items.append({"Code": k, "Rule": label, "Status": status, "Rule State": active})[cite: 3]
        st.dataframe(pd.DataFrame(fund_items), use_container_width=True, hide_index=True)[cite: 3]

    with tab_t:
        st.markdown(f"**Technical Score:** `{row_data['Technical Score']:.2f} / 10` (Passed: {row_data['Tech Passed']})")[cite: 3]
        raw_tech = row_data.get("raw_tech", {})[cite: 3]
        tech_items = []
        for k, label in DEFAULT_TECH_PARAMS.items():
            status = "✅ Pass" if raw_tech.get(k, False) else "❌ Fail"[cite: 3]
            active = "Active" if st.session_state.get(f"tech_{k}", True) else "Disabled"[cite: 3]
            tech_items.append({"Code": k, "Rule": label, "Status": status, "Rule State": active})[cite: 3]
        st.dataframe(pd.DataFrame(tech_items), use_container_width=True, hide_index=True)[cite: 3]

    with tab_rs:
        st.markdown(f"**Relative Strength Score:** `{row_data['Relative Strength Score']:.2f} / 10`")[cite: 3]
        raw_rs = row_data.get("raw_rs", {})[cite: 3]
        c_rs1, c_rs2 = st.columns(2)[cite: 3]
        c_rs1.metric("RS vs Benchmark (Nifty 50)", f"{raw_rs.get('RS1_diff', 0):+.2f}%", delta=f"{raw_rs.get('RS1_score', 0):.2f}/5 pts")[cite: 3]
        c_rs2.metric("RS vs Sector Average", f"{raw_rs.get('RS2_diff', 0):+.2f}%", delta=f"{raw_rs.get('RS2_score', 0):.2f}/5 pts")[cite: 3]

    with tab_chart:
        st.markdown(f"**Technical & Momentum Visualizer for {ticker}**")
        df_daily = fetch_daily(ticker)
        if df_daily is not None and not df_daily.empty:
            chart_df = df_daily.tail(200).copy()
            chart_df["SMA50"] = chart_df["Close"].rolling(50).mean()
            chart_df["SMA200"] = chart_df["Close"].rolling(200).mean()
            chart_df["RSI"] = ta.rsi(chart_df["Close"], length=14)

            st.line_chart(chart_df[["Close", "SMA50", "SMA200"]], height=280)
            st.caption("Price vs 50 DMA & 200 DMA")
            st.line_chart(chart_df["RSI"], height=150)
            st.caption("14-Period Daily RSI")
        else:
            st.info("Unable to fetch chart data.")

    st.divider()[cite: 3]
    if st.button("❌ Close Breakdown", use_container_width=True, type="primary"):[cite: 3]
        st.session_state["active_inspect_ticker"] = None[cite: 3]
        st.rerun()[cite: 3]

# ----------------------------------------------------------------------------------
# Safe Session-Based Modal Trigger
# ----------------------------------------------------------------------------------
target_ticker = st.session_state.get("active_inspect_ticker")[cite: 3]
if target_ticker:
    found_row = None
    
    if "results_df" in st.session_state and not st.session_state["results_df"].empty:
        match = st.session_state["results_df"][st.session_state["results_df"]["Ticker"] == target_ticker][cite: 3]
        if not match.empty:
            found_row = match.iloc[0].to_dict()[cite: 3]

    if not found_row and "p_results_df" in st.session_state and not st.session_state["p_results_df"].empty:
        match = st.session_state["p_results_df"][st.session_state["p_results_df"]["Ticker"] == target_ticker][cite: 3]
        if not match.empty:
            found_row = match.iloc[0].to_dict()[cite: 3]

    st.session_state["active_inspect_ticker"] = None[cite: 3]

    if found_row:
        show_pillar_details_modal(found_row)[cite: 3]
    else:
        st.toast(f"No result data found for {target_ticker}. Please run analysis first.")[cite: 3]

# ----------------------------------------------------------------------------------
# Calculation Engines
# ----------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_daily(ticker: str, period: str = "2y", retries: int = 2):
    for attempt in range(retries):
        try:
            df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)[cite: 3]
            if df is None or df.empty or len(df) < 30:
                time.sleep(0.3)[cite: 3]
                continue
            required_cols = ["Open", "High", "Low", "Close", "Volume"][cite: 3]
            if not all(col in df.columns for col in required_cols):
                continue
            df.index = pd.to_datetime(df.index)[cite: 3]
            df = df[required_cols].copy().replace([np.inf, -np.inf], np.nan).dropna()[cite: 3]
            if len(df) >= 30:
                return df[cite: 3]
        except Exception:
            time.sleep(0.3)[cite: 3]
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_info(ticker: str) -> dict:
    """
    Robust Financial Extractor replacing yfinance's deprecated dict properties.
    Extracts directly from financials, quarterly_financials, and fast_info data structures.
    """
    default_info = {
        "earningsGrowth": None, "earningsQuarterlyGrowth": None, 
        "revenueGrowth": None, "fiftyTwoWeekHigh": None,
        "currentPrice": None, "regularMarketPrice": None, "heldPercentInstitutions": None,
        "sector": "Unknown",
    }
    try:
        t = yf.Ticker(ticker)
        
        # 1. Fast Info Fallback for High and Price
        try:
            default_info["fiftyTwoWeekHigh"] = t.fast_info.get("year_high")
            default_info["currentPrice"] = t.fast_info.get("last_price")
        except Exception:
            pass

        # 2. Extract EPS & Revenue Growth directly from Financial DataFrames
        try:
            q_fin = t.quarterly_financials
            if q_fin is not None and not q_fin.empty:
                # Find Revenue / Net Income rows
                rev_row = next((r for r in q_fin.index if "total revenue" in str(r).lower() or "revenue" in str(r).lower()), None)
                ni_row = next((r for r in q_fin.index if "net income" in str(r).lower()), None)

                if rev_row and len(q_fin.columns) >= 5:
                    cur_rev = q_fin.loc[rev_row].iloc[0]
                    yoy_rev = q_fin.loc[rev_row].iloc[4]
                    if yoy_rev and yoy_rev > 0:
                        default_info["revenueGrowth"] = (cur_rev - yoy_rev) / yoy_rev

                if ni_row and len(q_fin.columns) >= 5:
                    cur_ni = q_fin.loc[ni_row].iloc[0]
                    yoy_ni = q_fin.loc[ni_row].iloc[4]
                    if yoy_ni and yoy_ni > 0:
                        default_info["earningsQuarterlyGrowth"] = (cur_ni - yoy_ni) / yoy_ni
        except Exception:
            pass

        # 3. Legacy Dict Info Lookup Fallback
        try:
            raw_info = t.info
            if isinstance(raw_info, dict):
                for k, v in raw_info.items():
                    if default_info.get(k) is None and v is not None:
                        default_info[k] = v
        except Exception:
            pass

    except Exception:
        pass
    return default_info


def resample_ohlc(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    if daily is None or daily.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])[cite: 3]
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}[cite: 3]
    try:
        return daily.resample(rule).agg(agg).dropna()[cite: 3]
    except ValueError:
        fallback_rule = "M" if rule == "ME" else "W"[cite: 3]
        try:
            return daily.resample(fallback_rule).agg(agg).dropna()[cite: 3]
        except Exception:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])[cite: 3]
    except Exception:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])[cite: 3]


def slope_up(series: pd.Series, lookback: int = 5) -> bool:
    s = series.dropna()[cite: 3]
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])[cite: 3]


def is_rising(series: pd.Series, lookback: int = 2) -> bool:
    s = series.dropna()[cite: 3]
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])[cite: 3]


def compute_fundamental_score(info: dict, daily: pd.DataFrame, bench_daily: pd.DataFrame):
    raw_results = {}[cite: 3]
    valid_metrics = {}[cite: 3]

    eps_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")[cite: 3]
    if eps_growth is not None and pd.notna(eps_growth):
        raw_results["C"] = bool(eps_growth > 0.15)[cite: 3]
        valid_metrics["C"] = True[cite: 3]
    else:
        raw_results["C"] = False[cite: 3]
        valid_metrics["C"] = False[cite: 3]

    rev_growth = info.get("revenueGrowth")[cite: 3]
    if rev_growth is not None and pd.notna(rev_growth):
        raw_results["A"] = bool(rev_growth > 0.10)[cite: 3]
        valid_metrics["A"] = True[cite: 3]
    else:
        raw_results["A"] = False[cite: 3]
        valid_metrics["A"] = False[cite: 3]

    fifty2_high = info.get("fiftyTwoWeekHigh")[cite: 3]
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")[cite: 3]

    if not current_price and daily is not None and not daily.empty:
        current_price = daily["Close"].iloc[-1][cite: 3]

    if fifty2_high and current_price:
        raw_results["N"] = bool(current_price >= 0.75 * fifty2_high)[cite: 3]
        valid_metrics["N"] = True[cite: 3]
    else:
        raw_results["N"] = False[cite: 3]
        valid_metrics["N"] = True[cite: 3]

    if daily is not None and len(daily) >= 50:
        close = daily["Close"][cite: 3]
        sma50 = close.rolling(50).mean().iloc[-1][cite: 3]
        vol_std = close.tail(10).std() / close.tail(10).mean() * 100[cite: 3]
        near_50 = abs(close.iloc[-1] - sma50) / sma50 * 100 if pd.notna(sma50) else 99[cite: 3]
        raw_results["S"] = bool(near_50 <= 5 and vol_std <= 6)[cite: 3]
    else:
        raw_results["S"] = False[cite: 3]
    valid_metrics["S"] = True[cite: 3]

    if daily is not None and len(daily) >= 14:
        rsi = ta.rsi(daily["Close"], length=14)[cite: 3]
        raw_results["L"] = bool(rsi is not None and not rsi.empty and rsi.iloc[-1] > 55)[cite: 3]
    else:
        raw_results["L"] = False[cite: 3]
    valid_metrics["L"] = True[cite: 3]

    inst_hold = info.get("heldPercentInstitutions")[cite: 3]
    if inst_hold is not None and pd.notna(inst_hold):
        raw_results["I"] = bool(inst_hold > 0.30)[cite: 3]
        valid_metrics["I"] = True[cite: 3]
    else:
        raw_results["I"] = False[cite: 3]
        valid_metrics["I"] = False[cite: 3]

    if bench_daily is not None and len(bench_daily) >= 200:
        bench_close = bench_daily["Close"][cite: 3]
        bench_sma200 = bench_close.rolling(200).mean().iloc[-1][cite: 3]
        raw_results["M"] = bool(bench_close.iloc[-1] > bench_sma200)[cite: 3]
    else:
        raw_results["M"] = False[cite: 3]
    valid_metrics["M"] = True[cite: 3]

    active_passed = 0
    active_total = 0
    passed_labels = []

    for k in DEFAULT_FUND_PARAMS:
        if st.session_state.get(f"fund_{k}", True):
            if valid_metrics.get(k, True):
                active_total += 1
                if raw_results.get(k, False):
                    active_passed += 1
                    passed_labels.append(k)[cite: 3]

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0[cite: 3]
    status_str = ",".join(passed_labels) if passed_labels else "None"[cite: 3]
    return round(norm_score, 2), status_str, raw_results


def compute_technical_score(daily: pd.DataFrame):
    if daily is None or len(daily) < 30:
        return 0.0, "0/0", {}[cite: 3]

    close = daily["Close"][cite: 3]
    d = daily.copy()[cite: 3]
    d["SMA20"] = close.rolling(20).mean()[cite: 3]
    d["SMA50"] = close.rolling(50).mean()[cite: 3]
    d["SMA200"] = close.rolling(200).mean()[cite: 3]
    d["RSI14"] = ta.rsi(close, length=14)[cite: 3]

    last_close = close.iloc[-1][cite: 3]
    sma20 = d["SMA20"].iloc[-1][cite: 3]
    sma50 = d["SMA50"].iloc[-1][cite: 3]
    sma200 = d["SMA200"].iloc[-1][cite: 3]
    rsi_daily = d["RSI14"].iloc[-1] if not d["RSI14"].empty else np.nan[cite: 3]

    weekly = resample_ohlc(daily, "W")[cite: 3]
    monthly = resample_ohlc(daily, "ME")[cite: 3]

    rsi_weekly = ta.rsi(weekly["Close"], length=14) if not weekly.empty else None[cite: 3]
    rsi_monthly = ta.rsi(monthly["Close"], length=14) if not monthly.empty else None[cite: 3]

    macd_w = ta.macd(weekly["Close"]) if not weekly.empty and len(weekly) > 3 else None[cite: 3]
    macd_m = ta.macd(monthly["Close"]) if not monthly.empty and len(monthly) > 3 else None[cite: 3]
    macd_d = ta.macd(close) if len(close) > 3 else None[cite: 3]

    raw = {}[cite: 3]
    near_50_pct = abs(last_close - sma50) / sma50 * 100 if pd.notna(sma50) else 99[cite: 3]
    raw["T1"] = bool(pd.notna(sma200) and last_close > sma200 and near_50_pct <= 5)[cite: 3]

    vol_pct = close.tail(10).std() / close.tail(10).mean() * 100[cite: 3]
    near_20_pct = abs(last_close - sma20) / sma20 * 100 if pd.notna(sma20) else 99[cite: 3]
    raw["T2"] = bool((near_50_pct <= 5 or near_20_pct <= 5) and vol_pct <= 6)[cite: 3]
    raw["T3"] = bool(pd.notna(sma200) and last_close <= 1.25 * sma200 and last_close > sma200)[cite: 3]
    raw["T4"] = bool(slope_up(d["SMA50"], 5) and slope_up(d["SMA200"], 5))[cite: 3]
    raw["T5"] = bool(rsi_monthly is not None and not rsi_monthly.empty and rsi_monthly.iloc[-1] > 50 and is_rising(rsi_monthly, 2))[cite: 3]
    raw["T6"] = bool(rsi_weekly is not None and not rsi_weekly.empty and rsi_weekly.iloc[-1] > 50 and is_rising(rsi_weekly, 2))[cite: 3]
    raw["T7"] = bool(pd.notna(rsi_daily) and rsi_daily > 50 and is_rising(d["RSI14"], 2))[cite: 3]
    raw["T8"] = bool(macd_m is not None and not macd_m.empty and is_rising(macd_m.iloc[:, 0], 2))[cite: 3]

    if macd_w is not None and not macd_w.empty:
        raw["T9"] = bool(macd_w.iloc[-1, 0] > macd_w.iloc[-1, 2] and macd_w.iloc[-1, 0] > 0 and is_rising(macd_w.iloc[:, 0], 2))[cite: 3]
    else:
        raw["T9"] = False[cite: 3]

    raw["T10"] = bool(macd_d is not None and not macd_d.empty and is_rising(macd_d.iloc[:, 0], 2))[cite: 3]

    active_passed = 0
    active_total = 0

    for k in DEFAULT_TECH_PARAMS:
        if st.session_state.get(f"tech_{k}", True):
            active_total += 1
            if raw.get(k, False):
                active_passed += 1[cite: 3]

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0[cite: 3]
    status_str = f"{active_passed}/{active_total}"[cite: 3]
    return round(norm_score, 2), status_str, raw


def compute_relative_strength_score(daily: pd.DataFrame, bench_daily: pd.DataFrame, sector_avg_ret: float, lookback: int = 63):
    if daily is None or bench_daily is None or len(daily) < 10 or len(bench_daily) < 10:
        return 0.0, "B:N/A | S:N/A", {}[cite: 3]

    n = min(lookback, len(daily) - 1, len(bench_daily) - 1)[cite: 3]
    stock_ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-n] - 1) * 100[cite: 3]
    bench_ret = (bench_daily["Close"].iloc[-1] / bench_daily["Close"].iloc[-n] - 1) * 100[cite: 3]

    outperform_bench = stock_ret - bench_ret[cite: 3]
    outperform_sector = stock_ret - sector_avg_ret if pd.notna(sector_avg_ret) else outperform_bench[cite: 3]

    score_rs1 = float(np.clip(2.5 + (outperform_bench / 10 * 2.5), 0, 5))[cite: 3]
    score_rs2 = float(np.clip(2.5 + (outperform_sector / 10 * 2.5), 0, 5))[cite: 3]

    pts_earned = 0.0
    pts_max = 0.0

    if st.session_state.get("rs_RS1", True):
        pts_earned += score_rs1[cite: 3]
        pts_max += 5.0[cite: 3]

    if st.session_state.get("rs_RS2", True):
        pts_earned += score_rs2[cite: 3]
        pts_max += 5.0[cite: 3]

    norm_score = (pts_earned / pts_max * 10) if pts_max > 0 else 0.0[cite: 3]
    status_str = f"B:{outperform_bench:+.1f}% | S:{outperform_sector:+.1f}%"[cite: 3]

    raw_rs = {
        "RS1_score": round(score_rs1, 2),
        "RS1_diff": round(outperform_bench, 2),
        "RS2_score": round(score_rs2, 2),
        "RS2_diff": round(outperform_sector, 2)
    }[cite: 3]
    return round(norm_score, 2), status_str, raw_rs


def fetch_single_stock(tkr: str):
    """Worker task for multi-threaded fetch operations."""
    daily = fetch_daily(tkr)
    info = fetch_info(tkr) if daily is not None else {}
    return tkr, daily, info


def execute_scan(ticker_list, w_fund, w_tech, w_rs):
    bench_daily = fetch_daily(BENCHMARK)[cite: 3]
    stock_data = {}
    sector_returns = {}
    
    progress = st.progress(0, text="Fetching stock data (Multi-Threaded Engine)...")
    
    # Accelerated ThreadPool Execution
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_stock, tkr): tkr for tkr in ticker_list}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            progress.progress(completed / len(ticker_list), text=f"Processing universe... ({completed}/{len(ticker_list)})")
            tkr, daily, info = future.result()
            if daily is not None:
                stock_data[tkr] = {"daily": daily, "info": info}
                if len(daily) >= 63:
                    ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-63] - 1) * 100
                    sec = info.get("sector", "Unknown")
                    sector_returns.setdefault(sec, []).append(ret)

    progress.empty()[cite: 3]

    sector_avg = {sec: np.mean(rets) for sec, rets in sector_returns.items() if rets}[cite: 3]

    results = []
    skipped = []

    for tkr in ticker_list:
        if tkr not in stock_data:
            skipped.append(tkr)[cite: 3]
            continue
        
        daily = stock_data[tkr]["daily"][cite: 3]
        info = stock_data[tkr]["info"][cite: 3]
        raw_sec = info.get("sector", "Unknown")[cite: 3]
        sec_abbrev = abbreviate_sector(raw_sec)[cite: 3]
        sec_ret = sector_avg.get(raw_sec, np.nan)[cite: 3]

        fund_score, fund_status, raw_fund = compute_fundamental_score(info, daily, bench_daily)[cite: 3]
        tech_score, tech_status, raw_tech = compute_technical_score(daily)[cite: 3]
        rs_score, rs_status, raw_rs = compute_relative_strength_score(daily, bench_daily, sec_ret)[cite: 3]

        total_score = (fund_score * w_fund + tech_score * w_tech + rs_score * w_rs) / 10[cite: 3]

        results.append({
            "Ticker": tkr,
            "Total Score": round(total_score, 2),
            "Fundamental Score": fund_score,
            "Technical Score": tech_score,
            "Relative Strength Score": rs_score,
            "Tech Passed": tech_status,
            "CANSLIM Hits": fund_status,
            "RS Details": rs_status,
            "Sector": sec_abbrev,
            "raw_fund": raw_fund,
            "raw_tech": raw_tech,
            "raw_rs": raw_rs,
        })[cite: 3]

    return pd.DataFrame(results), skipped

# ----------------------------------------------------------------------------------
# Sidebar Controls & Weight Auto-Saver
# ----------------------------------------------------------------------------------
st.sidebar.header("⚙️ Engine Controls")[cite: 3]

st.sidebar.subheader("1. Pillar Weights (Sum to 10)")[cite: 3]

def on_weight_change():
    save_user_settings_to_db()[cite: 3]

w_fund = st.sidebar.slider(
    "Fundamental Weight", 0, 10, key="w_fund", on_change=on_weight_change
)[cite: 3]
w_tech = st.sidebar.slider(
    "Technical Weight", 0, 10, key="w_tech", on_change=on_weight_change
)[cite: 3]

w_rs_calc = 10 - w_fund - w_tech[cite: 3]

if w_rs_calc < 0:
    st.sidebar.error("Weight total exceeds 10. Adjust sliders.")[cite: 3]
    w_rs = 0[cite: 3]
else:
    w_rs = w_rs_calc[cite: 3]
    st.sidebar.metric("Relative Strength Weight", w_rs)[cite: 3]

st.sidebar.divider()[cite: 3]

st.sidebar.subheader("2. Pillar Customization")[cite: 3]
if st.sidebar.button("⚙️ Fundamental Rules", use_container_width=True):[cite: 3]
    customize_fundamental_modal()[cite: 3]

if st.sidebar.button("⚙️ Technical Rules", use_container_width=True):[cite: 3]
    customize_technical_modal()[cite: 3]

if st.sidebar.button("⚙️ Relative Strength Rules", use_container_width=True):[cite: 3]
    customize_rs_modal()[cite: 3]

# ----------------------------------------------------------------------------------
# Dynamic Navigation Tabs
# ----------------------------------------------------------------------------------
tab_list = ["🔍 Stock Screener", "⚡ Chartink Integrator", "💼 Portfolio Evaluator", "ℹ️ User Guide"]
if user_is_admin:
    tab_list.append("🛠️ Admin Panel")[cite: 3]

tabs = st.tabs(tab_list)
tab_screener = tabs[0]
tab_chartink = tabs[1]
tab_portfolio = tabs[2]
tab_guide = tabs[3]
tab_admin = tabs[4] if user_is_admin else None

# ==================================================================================
# TAB 1: STOCK SCREENER
# ==================================================================================
with tab_screener:
    st.sidebar.divider()[cite: 3]
    st.sidebar.subheader("3. Screener Universe")[cite: 3]
    
    with st.sidebar.expander("📤 Upload Custom CSV List", expanded=False):[cite: 3]
        uploaded_csv = st.file_uploader("Upload Universe CSV", type=["csv"], key="scr_csv", label_visibility="collapsed")[cite: 3]

    csv_tickers = [][cite: 3]
    if uploaded_csv is not None:
        try:
            csv_df = pd.read_csv(uploaded_csv)[cite: 3]
            csv_tickers = parse_broker_symbols(csv_df)[cite: 3]
            if csv_tickers:
                st.sidebar.success(f"Loaded {len(csv_tickers)} tickers.")[cite: 3]
        except Exception as e:
            st.sidebar.error(f"Error parsing universe file: {e}")[cite: 3]

    full_options = list(dict.fromkeys(DEFAULT_UNIVERSE + csv_tickers + st.session_state.get("chartink_tickers", [])))
    selected_universe = st.sidebar.multiselect("Active Tickers", options=full_options, default=(csv_tickers if csv_tickers else DEFAULT_UNIVERSE[:30]))[cite: 3]
    custom_raw = st.sidebar.text_input("Add Custom Tickers", value="")[cite: 3]
    custom_tickers = [t.strip().upper() if t.strip().upper().endswith(".NS") else f"{t.strip().upper()}.NS" for t in custom_raw.split(",") if t.strip()][cite: 3]
    universe = list(dict.fromkeys(selected_universe + custom_tickers))[cite: 3]

    run_scan = st.sidebar.button("🔍 Run Screener Scan", use_container_width=True)[cite: 3]

    if run_scan:
        if not universe:
            st.warning("Select at least one ticker.")[cite: 3]
        else:
            st.cache_data.clear()[cite: 3]
            with st.spinner("Running quantitative scan..."):[cite: 3]
                results_df, skipped = execute_scan(universe, w_fund, w_tech, w_rs)[cite: 3]
                st.session_state["results_df"] = results_df[cite: 3]
                st.session_state["skipped_tickers"] = skipped[cite: 3]

    if "results_df" in st.session_state:
        df = st.session_state["results_df"][cite: 3]
        skipped = st.session_state.get("skipped_tickers", [])[cite: 3]

        if not df.empty:
            df = df.sort_values("Total Score", ascending=False).reset_index(drop=True)[cite: 3]

            c1, c2, c3 = st.columns(3)[cite: 3]
            c1.metric("Screened Tickers", len(df))[cite: 3]
            c2.metric("Highest Total Score", f"{df['Total Score'].max():.2f}")[cite: 3]
            c3.metric("Average Score", f"{df['Total Score'].mean():.2f}")[cite: 3]

            st.divider()[cite: 3]

            # TradingView Exporter
            st.subheader("📈 TradingView 1-Click Clipboard Exporter")[cite: 3]
            col_tv1, col_tv2 = st.columns([1, 2])[cite: 3]
            
            with col_tv1:
                threshold = st.slider("Min Score Filter", 0.0, 10.0, 6.0, 0.5, key="scr_tv_thresh")[cite: 3]
            
            filtered_df = df[df["Total Score"] >= threshold][cite: 3]
            tv_symbols = [f"NSE:{s.replace('.NS', '')}" for s in filtered_df["Ticker"].tolist()][cite: 3]
            tv_content = ",".join(tv_symbols)[cite: 3]

            with col_tv2:
                st.write(f"**{len(tv_symbols)} matching tickers** ($\ge {threshold:.1f}$). Copy below ➡️")[cite: 3]
                if tv_symbols:
                    st.code(tv_content, language="text")[cite: 3]
                else:
                    st.info("No tickers match this score threshold.")[cite: 3]

            st.divider()[cite: 3]

            # Screening Table with Toolbar Control
            st.subheader("📋 Screening Results Table")[cite: 3]
            st.info("💡 Select a holding below or choose a symbol to inspect its detailed pillar breakdown.")[cite: 3]

            display_table = df[[
                "Ticker", "Total Score", "Fundamental Score", 
                "Technical Score", "Relative Strength Score", 
                "Tech Passed", "CANSLIM Hits", "RS Details", "Sector"
            ]].copy()[cite: 3]

            c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])[cite: 3]
            
            with c_ctrl1:
                selected_ticker = st.selectbox(
                    "Select Stock to Inspect:", 
                    options=df["Ticker"].tolist(),
                    key="scr_select_tkr",
                    label_visibility="collapsed"
                )[cite: 3]
            with c_ctrl2:
                st.write(f"Selected: **{selected_ticker}**")[cite: 3]
            with c_ctrl3:
                if st.button("🔍 Breakdown", key="scr_view_btn", use_container_width=True, type="primary"):[cite: 3]
                    st.session_state["active_inspect_ticker"] = selected_ticker[cite: 3]
                    st.rerun()[cite: 3]

            st.dataframe(
                display_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                    "Total Score": st.column_config.NumberColumn("Total", format="%.2f"),
                    "Fundamental Score": st.column_config.NumberColumn("Fund", format="%.2f"),
                    "Technical Score": st.column_config.NumberColumn("Tech", format="%.2f"),
                    "Relative Strength Score": st.column_config.NumberColumn("RS", format="%.2f"),
                }
            )[cite: 3]

# ==================================================================================
# TAB 2: CHARTINK STRATEGY INTEGRATOR
# ==================================================================================
with tab_chartink:
    st.subheader("⚡ Chartink Custom Scanner Sync Engine")
    st.caption("Directly paste Chartink scanner text output, HTML table text, or symbol lists to evaluate setups against CANSLIM, Technical, and RS models.")

    c_ci1, c_ci2 = st.columns([2, 1])
    with c_ci1:
        raw_chartink_text = st.text_area(
            "Paste Raw Chartink Scanner Results / Stock Table:", 
            placeholder="Paste text directly from Chartink scanner output table or symbol list e.g.\nTRENT, HAL, ZOMATO, BEL, TATAMOTORS...", 
            height=180
        )
    with c_ci2:
        st.markdown("#### **Integration Steps:**")
        st.markdown("1. Run scanner on **Chartink.com**")
        st.markdown("2. Select all stock symbols in table & Copy")
        st.markdown("3. Paste into text box on the left")
        st.markdown("4. Click **Parse & Load Chartink Setups** below")

    if st.button("⚡ Parse & Synchronize Chartink Setups", use_container_width=True, type="primary"):
        parsed_ci = parse_chartink_input(raw_chartink_text)
        if parsed_ci:
            st.session_state["chartink_tickers"] = parsed_ci
            st.success(f"Successfully extracted **{len(parsed_ci)} stocks** from Chartink input.")
        else:
            st.warning("Could not identify valid stock symbols. Please check input text format.")

    if "chartink_tickers" in st.session_state and st.session_state["chartink_tickers"]:
        ci_tickers = st.session_state["chartink_tickers"]
        st.write(f"**Current Active Chartink Import ({len(ci_tickers)}):** `" + ", ".join([s.replace(".NS", "") for s in ci_tickers]) + "`")

        if st.button("🚀 Analyze Chartink Candidates with 3-Pillar Model", use_container_width=True):
            with st.spinner("Executing evaluation engine..."):
                ci_results, ci_skipped = execute_scan(ci_tickers, w_fund, w_tech, w_rs)
                if not ci_results.empty:
                    st.session_state["results_df"] = ci_results
                    st.success("Chartink evaluation complete. Results loaded into Screener matrix above.")

# ==================================================================================
# TAB 3: PORTFOLIO EVALUATOR
# ==================================================================================
with tab_portfolio:
    st.subheader("💼 Multi-Broker Portfolio Health Evaluator")[cite: 3]
    st.caption("Supports raw holdings exports from Zerodha, Groww, Dhan, Upstox, Angel One, ICICI Direct, and Kotak.")[cite: 3]
    
    col_input1, col_input2 = st.columns([1, 1])[cite: 3]
    parsed_portfolio_tickers = [][cite: 3]
    
    with col_input1:
        st.markdown("##### **Option A: Upload Broker Holdings Export**")[cite: 3]
        port_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"], key="port_upload")[cite: 3]
        
        if port_file is not None:
            try:
                if port_file.name.endswith(".csv"):
                    p_df = pd.read_csv(port_file)[cite: 3]
                else:
                    p_df = pd.read_excel(port_file)[cite: 3]
                    
                parsed_portfolio_tickers = parse_broker_symbols(p_df)[cite: 3]
                if parsed_portfolio_tickers:
                    st.success(f"✅ Auto-parsed **{len(parsed_portfolio_tickers)} symbols**.")[cite: 3]
                else:
                    st.error("⚠️ Could not detect symbol column. Use Option B.")[cite: 3]
            except Exception as e:
                st.error(f"Error reading file: {e}")[cite: 3]

    with col_input2:
        st.markdown("##### **Option B: Paste Stock Symbols Directly**")[cite: 3]
        raw_pasted = st.text_area("Paste symbols (comma, space, or line separated):", placeholder="TATAMOTORS, HDFCBANK, TRENT, AUBANK", height=100)[cite: 3]
        
        if raw_pasted.strip():
            delimiters = [",", "\n", " ", ";"][cite: 3]
            temp_str = raw_pasted[cite: 3]
            for d in delimiters:
                temp_str = temp_str.replace(d, "|")[cite: 3]
            pasted_symbols = [s.strip().upper() for s in temp_str.split("|") if s.strip()][cite: 3]
            
            pasted_formatted = [
                f"{s.replace('NSE:', '').replace('-EQ', '')}.NS" if not s.endswith(".NS") else s
                for s in pasted_symbols
            ][cite: 3]
            
            if not parsed_portfolio_tickers:
                parsed_portfolio_tickers = list(dict.fromkeys(pasted_formatted))[cite: 3]
                st.info(f"Loaded **{len(parsed_portfolio_tickers)} symbols** from text.")[cite: 3]

    st.divider()[cite: 3]

    if parsed_portfolio_tickers:
        st.write(f"**Loaded Holdings ({len(parsed_portfolio_tickers)}):** `" + ", ".join([s.replace(".NS", "") for s in parsed_portfolio_tickers]) + "`")[cite: 3]
        
        if st.button("🚀 Evaluate Portfolio Health", use_container_width=True):[cite: 3]
            with st.spinner("Evaluating portfolio holdings against 3-Pillar engine..."):[cite: 3]
                p_results, p_skipped = execute_scan(parsed_portfolio_tickers, w_fund, w_tech, w_rs)[cite: 3]
                
                if not p_results.empty:
                    p_results = p_results.sort_values("Total Score", ascending=False).reset_index(drop=True)[cite: 3]
                    st.session_state["p_results_df"] = p_results[cite: 3]

    if "p_results_df" in st.session_state:
        p_results = st.session_state["p_results_df"][cite: 3]
        p_avg_score = p_results["Total Score"].mean()[cite: 3]
        p_weak = p_results[p_results["Total Score"] < 5.0][cite: 3]
        p_strong = p_results[p_results["Total Score"] >= 7.0][cite: 3]

        col_p1, col_p2, col_p3 = st.columns(3)[cite: 3]
        col_p1.metric("Portfolio Health Score", f"{p_avg_score:.2f} / 10")[cite: 3]
        col_p2.metric("Strong Holdings (Score ≥ 7.0)", len(p_strong))[cite: 3]
        col_p3.metric("Weak Holdings (Score < 5.0)", len(p_weak))[cite: 3]

        st.divider()[cite: 3]
        st.subheader("📊 Portfolio Scoring Matrix")[cite: 3]
        st.info("💡 Select a holding below or choose a symbol to inspect its detailed pillar breakdown.")[cite: 3]

        p_table = p_results[[
            "Ticker", "Total Score", "Fundamental Score", 
            "Technical Score", "Relative Strength Score", 
            "Tech Passed", "CANSLIM Hits", "RS Details", "Sector"
        ]].copy()[cite: 3]

        c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])[cite: 3]

        with c_ctrl1:
            p_selected_ticker = st.selectbox(
                "Select Holding to Inspect:", 
                options=p_results["Ticker"].tolist(),
                key="port_select_tkr",
                label_visibility="collapsed"
            )[cite: 3]
        with c_ctrl2:
            st.write(f"Selected: **{p_selected_ticker}**")[cite: 3]
        with c_ctrl3:
            if st.button("🔍 Breakdown", key="port_view_btn", use_container_width=True, type="primary"):[cite: 3]
                st.session_state["active_inspect_ticker"] = p_selected_ticker[cite: 3]
                st.rerun()[cite: 3]

        st.dataframe(
            p_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                "Total Score": st.column_config.NumberColumn("Total", format="%.2f"),
                "Fundamental Score": st.column_config.NumberColumn("Fund", format="%.2f"),
                "Technical Score": st.column_config.NumberColumn("Tech", format="%.2f"),
                "Relative Strength Score": st.column_config.NumberColumn("RS", format="%.2f"),
            }
        )[cite: 3]

        st.divider()[cite: 3]
        st.download_button(
            label="⬇️ Export Portfolio Evaluation CSV",
            data=p_results.to_csv(index=False).encode("utf-8"),
            file_name="portfolio_evaluation_results.csv",
            mime="text/csv",
            use_container_width=True
        )[cite: 3]

# ==================================================================================
# TAB 4: USER GUIDE
# ==================================================================================
with tab_guide:
    st.subheader("ℹ️ User Guide & Scoring Methodology")[cite: 3]
    st.markdown(
        """
        Welcome to the **Quantitative Multi-Pillar Engine**. This tool combines CANSLIM fundamental growth metrics, 
        multi-timeframe technical momentum rules, and relative strength alpha calculations to score NSE equities.
        """
    )[cite: 3]
    
    st.markdown("---")[cite: 3]
    
    col_g1, col_g2 = st.columns(2)[cite: 3]
    with col_g1:
        st.markdown("### 🏛️ Pillar 1: Fundamental Score")[cite: 3]
        st.markdown(
            """
            * **C - Current Earnings:** EPS growth > 15% YoY or QoQ.
            * **A - Annual Revenue:** Revenue growth > 10%.
            * **N - Near 52W High:** Price within 25% of 52-week high.
            * **S - Supply/Demand:** Tight price base consolidation near moving averages.
            * **L - Leader RS:** Daily RSI > 55.
            * **I - Institutional Sponsorship:** Institutional holdings > 30%.
            * **M - Market Direction:** Benchmark Nifty 50 above its 200 DMA.
            """
        )[cite: 3]
    with col_g2:
        st.markdown("### 📈 Pillar 2: Technical Score")[cite: 3]
        st.markdown(
            """
            * **Trend Alignment:** Close > 200 DMA and near 50 DMA.
            * **Consolidation:** Low volatility base building.
            * **Moving Averages:** 50 and 200 DMA sloping upward.
            * **Momentum Oscillators:** RSI and MACD confirmation across Daily, Weekly, and Monthly timeframes.
            """
        )[cite: 3]

    st.markdown("---")[cite: 3]
    st.markdown("### ⚡ Pillar 3: Relative Strength & Portfolio Evaluation")[cite: 3]
    st.markdown(
        """
        * **RS vs Benchmark:** Measures 63-day percentage outperformance against Nifty 50 (`^NSEI`).
        * **RS vs Sector:** Compares stock returns against its specific industry sector average.
        * **Portfolio Evaluator:** Automatically parses holdings from broker CSV/Excel exports or pasted symbols to compute overall portfolio health and pinpoint weak holdings.
        * **Chartink Integrator:** Syncs Chartink scanner queries directly into the engine matrix.
        """
    )[cite: 3]

# ==================================================================================
# TAB 5: ADMIN PANEL
# ==================================================================================
if user_is_admin and tab_admin is not None:
    with tab_admin:
        st.subheader("🛠️ Administrator Control & User Management Dashboard")[cite: 3]
        st.success(f"Authenticated as Administrator: `{user_email}`")[cite: 3]
        
        st.divider()[cite: 3]
        
        col_adm1, col_adm2 = st.columns([1, 1])[cite: 3]
        
        with col_adm1:
            st.markdown("#### 📊 System Metrics & Diagnostics")[cite: 3]
            st.json({
                "Admin User": user_email,
                "Supabase Connection Active": SUPABASE_AVAILABLE and get_supabase_client() is not None,
                "Default Nifty 500 Universe Tickers": len(DEFAULT_UNIVERSE),
                "Active Pillar Weights": {
                    "Fundamental": w_fund,
                    "Technical": w_tech,
                    "Relative Strength": w_rs
                }
            })[cite: 3]
            
            if st.button("🧹 Clear Global Streamlit Data Cache", use_container_width=True):[cite: 3]
                st.cache_data.clear()[cite: 3]
                st.success("Global application cache cleared successfully.")[cite: 3]

        with col_adm2:
            st.markdown("#### 👥 Registered Users & Access Audit")[cite: 3]
            supabase = get_supabase_client()[cite: 3]
            if supabase:
                try:
                    users_list = []
                    try:
                        auth_users_res = supabase.auth.admin.list_users()[cite: 3]
                        if auth_users_res:
                            for u in auth_users_res:
                                users_list.append({
                                    "User ID": getattr(u, "id", str(u)),
                                    "Email": getattr(u, "email", "N/A"),
                                    "Created At": getattr(u, "created_at", "N/A"),
                                    "Last Sign In": getattr(u, "last_sign_in_at", "N/A")
                                })[cite: 3]
                    except Exception:
                        pass
                    
                    if not users_list:
                        res = supabase.table("user_settings").select("user_id, updated_at, w_fund, w_tech").execute()[cite: 3]
                        if res.data:
                            for row in res.data:
                                users_list.append({
                                    "User ID": row.get("user_id"),
                                    "Email": "Registered User",
                                    "Created At": "N/A",
                                    "Last Sign In": row.get("updated_at")
                                })[cite: 3]

                    if users_list:
                        st.dataframe(pd.DataFrame(users_list), use_container_width=True, hide_index=True)[cite: 3]
                    else:
                        st.info("No user records retrieved from authentication system.")[cite: 3]
                except Exception as e:
                    st.error(f"Error retrieving user audit records: {e}")[cite: 3]
            else:
                st.warning("Supabase connection unavailable in local or offline mode.")[cite: 3]

        st.divider()[cite: 3]
        st.markdown("#### 🗄️ Raw Database Inspection (`user_settings` Table)")[cite: 3]
        if supabase:
            try:
                full_res = supabase.table("user_settings").select("*").execute()[cite: 3]
                if full_res.data:
                    st.dataframe(pd.DataFrame(full_res.data), use_container_width=True)[cite: 3]
            except Exception as e:
                st.error(f"Error fetching table data: {e}")[cite: 3]

# ----------------------------------------------------------------------------------
# Footer
# ----------------------------------------------------------------------------------
st.divider()[cite: 3]
st.caption(
    "**Disclaimer:** Third-party data feeds may be delayed or unsynchronized. "
    "Strictly educational content, not financial advice. Verify all setups prior to trading. "
    "For queries: vkiyer@hotmail.com."
)[cite: 3]