"""
NSE Stock Screener — Interactive Analysis Engine (Auth Gated, Admin Enabled & Supabase Persisted)
----------------------------------------------------------------------------------
Includes Enforced Main-Screen Supabase Authentication, Settings Persistence (Save/Load),
Admin Email Privilege Checking, Mobile-First Responsive CSS, Multi-Broker Auto-Parser, 
API Data-Drop Protection, 1-Click TradingView Exporter, and User Guide.

Run with: streamlit run app.py
"""

import os
import time
import numpy as np

# --- Compatibility patch for pandas_ta on newer numpy ---
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import pandas as pd
import streamlit as st
import yfinance as yf
import pandas_ta as ta

# Add this temporarily near the top of app.py to inspect secret parsing
with st.sidebar.expander("🔑 Supabase Key Diagnostics", expanded=True):
    raw_url = str(st.secrets.get("SUPABASE_URL") or "")
    raw_key = str(st.secrets.get("SUPABASE_KEY") or "")
    
    st.write(f"**URL Found:** `{bool(raw_url)}` (Length: {len(raw_url)})")
    st.write(f"**Key Found:** `{bool(raw_key)}` (Length: {len(raw_key)})")
    
    if raw_key:
        st.write(f"**Key Prefix:** `{raw_key[:12]}...`")
        st.write(f"**Key Suffix:** `...{raw_key[-6:]}`")
        st.write(f"**Contains Spaces/Newlines:** `{(' ' in raw_key) or ('\\n' in raw_key)}`")
 # Add this temporarily near the top of app.py to inspect secret parsing
       

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
    /* Global Mobile Touch Targets & Typography */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Touch-friendly input fields and buttons */
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

    /* Mobile Responsive Media Queries (< 768px) */
    @media only screen and (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 1rem !important;
        }

        div[data-testid="column"] {
            width: 100% !important;
            min-width: 100% !important;
            white-space: normal !important;
            word-break: break-word !important;
        }

        .stButton > button {
            width: 100% !important;
            margin-bottom: 0.5rem;
        }

        div[data-baseweb="tab-list"] {
            gap: 2px !important;
            width: 100% !important;
        }
        
        button[data-baseweb="tab"] {
            padding: 8px 10px !important;
            font-size: 12px !important;
            flex-grow: 1 !important;
            text-align: center !important;
        }

        div[data-testid="stTable"], div[data-testid="stDataFrame"] {
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------------
# Constants, Defaults & Admin Access Control
# ----------------------------------------------------------------------------------
ADMIN_EMAILS = ["vkiyer@hotmail.com"]  # Add additional admin emails here if needed

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

SECTOR_MAP = {
    "Financial Services": "Fin Services",
    "Consumer Cyclical": "Cons Cyclical",
    "Consumer Defensive": "Cons Defensive",
    "Healthcare": "Healthcare",
    "Technology": "Tech",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Comm Services",
    "Unknown": "Unknown"
}

BROKER_SYMBOL_HEADERS = [
    "instrument", "trading symbol", "tradingsymbol", "symbol", 
    "ticker", "company name", "stock name", "stock", "scrip name", "display name"
]

def is_admin(user) -> bool:
    if not user:
        return False
    email = user.get("email") if isinstance(user, dict) else getattr(user, "email", "")
    return email.lower() in [e.lower() for e in ADMIN_EMAILS]

# ----------------------------------------------------------------------------------
# Safe Supabase Helper & Persistence Engine
# ----------------------------------------------------------------------------------
def get_supabase_client():
    if not SUPABASE_AVAILABLE:
        return None
    
    url = str(st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url") or os.environ.get("SUPABASE_URL") or "").strip()
    key = str(st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase", {}).get("key") or os.environ.get("SUPABASE_KEY") or "").strip()

    if url and key and url != "None" and key != "None":
        try:
            # Force apikey header into client options to ensure auth requests aren't dropped by gateway
            from supabase.lib.client_options import ClientOptions
            options = ClientOptions(
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}"
                }
            )
            return create_client(url, key, options=options)
        except Exception:
            try:
                # Fallback standard initialization
                return create_client(url, key)
            except Exception:
                return None
    return None


def load_user_settings_from_db(user_id: str):
    supabase = get_supabase_client()
    if not supabase or not user_id:
        return
    
    try:
        response = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            data = response.data[0]
            st.session_state["w_fund"] = data.get("w_fund", 4)
            st.session_state["w_tech"] = data.get("w_tech", 4)
            
            fund_rules = data.get("fund_rules") or {}
            for k, val in fund_rules.items():
                st.session_state[f"fund_{k}"] = val
                
            tech_rules = data.get("tech_rules") or {}
            for k, val in tech_rules.items():
                st.session_state[f"tech_{k}"] = val

            rs_rules = data.get("rs_rules") or {}
            for k, val in rs_rules.items():
                st.session_state[f"rs_{k}"] = val
    except Exception as e:
        st.warning(f"Could not load saved settings from database: {e}")


def save_user_settings_to_db():
    supabase = get_supabase_client()
    user = st.session_state.get("user")
    
    if not supabase or not user:
        return

    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
    if not user_id:
        return

    fund_dict = {k: st.session_state.get(f"fund_{k}", True) for k in DEFAULT_FUND_PARAMS}
    tech_dict = {k: st.session_state.get(f"tech_{k}", True) for k in DEFAULT_TECH_PARAMS}
    rs_dict = {k: st.session_state.get(f"rs_{k}", True) for k in DEFAULT_RS_PARAMS}

    payload = {
        "user_id": user_id,
        "w_fund": st.session_state.get("w_fund", 4),
        "w_tech": st.session_state.get("w_tech", 4),
        "fund_rules": fund_dict,
        "tech_rules": tech_dict,
        "rs_rules": rs_dict,
        "updated_at": "now()"
    }

    try:
        supabase.table("user_settings").upsert(payload).execute()
    except Exception as e:
        st.error(f"Failed to save settings: {e}")


def init_auth_session():
    if "user" not in st.session_state:
        st.session_state["user"] = None


def render_login_screen():
    init_auth_session()
    supabase = get_supabase_client()

    st.title("🔐 NSE Stock Screener")
    st.caption("Please log in to access the Quantitative Analysis Engine.")
    st.divider()

    if not SUPABASE_AVAILABLE or supabase is None:
        st.warning("⚠️ **Supabase configuration not detected.**")
        st.info("Configure `SUPABASE_URL` and `SUPABASE_KEY` in `.streamlit/secrets.toml` to enable auth & persistence.")
        
        if st.button("Bypass Login (Developer / Local Mode)", use_container_width=True):
            st.session_state["user"] = {"id": "local-dev-id", "email": "vkiyer@hotmail.com"}
            st.rerun()
        return False

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Account Access")
        auth_mode = st.radio("Choose Mode", ["Login", "Sign Up"], key="auth_mode")
        email = st.text_input("Email", key="auth_email")
        password = st.text_input("Password", type="password", key="auth_pass")

        if auth_mode == "Login":
            if st.button("Log In", use_container_width=True, type="primary"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state["user"] = res.user
                    user_id = getattr(res.user, "id", None)
                    if user_id:
                        load_user_settings_from_db(user_id)
                    st.success("Login successful!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")
        else:
            if st.button("Create Account", use_container_width=True, type="primary"):
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    st.success("Account created! Check your email or log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")

    with col2:
        st.markdown(
            """
            ### 🏛️ What's Inside:
            * **CANSLIM-7 Fundamental Engine:** Quantitative growth scoring.
            * **10-Point Technical System:** Multi-timeframe trend & momentum.
            * **Relative Strength Matrix:** Sector & Nifty 50 outperformance filters.
            * **Multi-Broker Portfolio Evaluator:** Auto-parse holdings.
            * **1-Click TradingView Exporter:** Instant watchlist sync.
            """
        )

    return False

# Enforce Authentication Gate BEFORE loading sidebar or app
if "user" not in st.session_state or st.session_state["user"] is None:
    render_login_screen()
    st.stop()

# ----------------------------------------------------------------------------------
# Session State Initialization (Fallback Defaults)
# ----------------------------------------------------------------------------------
if "w_fund" not in st.session_state:
    st.session_state["w_fund"] = 4
if "w_tech" not in st.session_state:
    st.session_state["w_tech"] = 4

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
# Main App Header & User Info
# ----------------------------------------------------------------------------------
current_user = st.session_state["user"]
user_email = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", "User")
user_is_admin = is_admin(current_user)

st.sidebar.markdown(f"👤 **User:** `{user_email}`")
if user_is_admin:
    st.sidebar.markdown("⭐ **Role:** `Administrator`")

if st.sidebar.button("🚪 Log Out", use_container_width=True):
    supabase = get_supabase_client()
    if supabase:
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
    st.session_state["user"] = None
    st.rerun()

st.sidebar.divider()

st.title("📊 NSE Stock Screener & Portfolio Evaluator")
st.caption("Quantitative Multi-Pillar Engine for Swing Traders & Growth Investors.")

# ----------------------------------------------------------------------------------
# Helper Functions & Data Fetchers
# ----------------------------------------------------------------------------------
def abbreviate_sector(sector_raw: str) -> str:
    if not sector_raw or sector_raw == "Unknown":
        return "Unknown"
    return SECTOR_MAP.get(sector_raw.strip(), sector_raw.strip())


def parse_broker_symbols(df: pd.DataFrame) -> list:
    matched_col = None
    cleaned_cols = {str(c).strip().lower(): c for c in df.columns}
    
    for key in BROKER_SYMBOL_HEADERS:
        if key in cleaned_cols:
            matched_col = cleaned_cols[key]
            break
            
    if not matched_col:
        return []

    raw_symbols = df[matched_col].dropna().astype(str).tolist()
    formatted_symbols = []
    
    for sym in raw_symbols:
        clean = sym.strip().upper()
        clean = clean.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-BE", "").strip()
        if clean and not clean.startswith("^"):
            formatted_symbols.append(f"{clean}.NS" if not clean.endswith(".NS") else clean)
            
    return list(dict.fromkeys(formatted_symbols))


@st.cache_data(ttl=86400, show_spinner=False)
def load_default_nifty500():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        df = pd.read_csv(url, storage_options=headers)
        symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
        if symbol_col:
            return [f"{str(s).strip().upper()}.NS" for s in df[symbol_col].dropna().tolist() if str(s).strip()]
    except Exception:
        pass
    return [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "AUBANK.NS", "TRENT.NS", "HAL.NS", "TATAMOTORS.NS", "BAJFINANCE.NS",
        "LT.NS", "SBIN.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS"
    ]

DEFAULT_UNIVERSE = load_default_nifty500()

# ----------------------------------------------------------------------------------
# Dialog Modals with Database Sync
# ----------------------------------------------------------------------------------
@st.dialog("⚙️ Customize Fundamental Parameters")
def customize_fundamental_modal():
    st.write("Select CANSLIM-7 criteria to include:")
    for k, label in DEFAULT_FUND_PARAMS.items():
        st.session_state[f"fund_{k}"] = st.checkbox(label, value=st.session_state[f"fund_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_fund"):
        for k in DEFAULT_FUND_PARAMS:
            st.session_state[f"fund_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="apply_fund"):
        save_user_settings_to_db()
        st.rerun()


@st.dialog("⚙️ Customize Technical Parameters")
def customize_technical_modal():
    st.write("Select rules to include in Technical Score:")
    for k, label in DEFAULT_TECH_PARAMS.items():
        st.session_state[f"tech_{k}"] = st.checkbox(label, value=st.session_state[f"tech_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_tech"):
        for k in DEFAULT_TECH_PARAMS:
            st.session_state[f"tech_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="apply_tech"):
        save_user_settings_to_db()
        st.rerun()


@st.dialog("⚙️ Customize Relative Strength Parameters")
def customize_rs_modal():
    st.write("Select relative strength benchmarks to include:")
    for k, label in DEFAULT_RS_PARAMS.items():
        st.session_state[f"rs_{k}"] = st.checkbox(label, value=st.session_state[f"rs_{k}"])
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_rs"):
        for k in DEFAULT_RS_PARAMS:
            st.session_state[f"rs_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="apply_rs"):
        save_user_settings_to_db()
        st.rerun()

# ----------------------------------------------------------------------------------
# Calculation Engines
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
        "earningsGrowth": None, "earningsQuarterlyGrowth": None, 
        "revenueGrowth": None, "fiftyTwoWeekHigh": None,
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


def compute_fundamental_score(info: dict, daily: pd.DataFrame, bench_daily: pd.DataFrame):
    raw_results = {}
    valid_metrics = {}

    eps_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    if eps_growth is not None and pd.notna(eps_growth):
        raw_results["C"] = bool(eps_growth > 0.15)
        valid_metrics["C"] = True
    else:
        raw_results["C"] = False
        valid_metrics["C"] = False

    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None and pd.notna(rev_growth):
        raw_results["A"] = bool(rev_growth > 0.10)
        valid_metrics["A"] = True
    else:
        raw_results["A"] = False
        valid_metrics["A"] = False

    fifty2_high = info.get("fiftyTwoWeekHigh")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    if not current_price and daily is not None and not daily.empty:
        current_price = daily["Close"].iloc[-1]

    if fifty2_high and current_price:
        raw_results["N"] = bool(current_price >= 0.75 * fifty2_high)
        valid_metrics["N"] = True
    else:
        raw_results["N"] = False
        valid_metrics["N"] = True

    if daily is not None and len(daily) >= 50:
        close = daily["Close"]
        sma50 = close.rolling(50).mean().iloc[-1]
        vol_std = close.tail(10).std() / close.tail(10).mean() * 100
        near_50 = abs(close.iloc[-1] - sma50) / sma50 * 100 if pd.notna(sma50) else 99
        raw_results["S"] = bool(near_50 <= 5 and vol_std <= 6)
    else:
        raw_results["S"] = False
    valid_metrics["S"] = True

    if daily is not None and len(daily) >= 14:
        rsi = ta.rsi(daily["Close"], length=14)
        raw_results["L"] = bool(rsi is not None and not rsi.empty and rsi.iloc[-1] > 55)
    else:
        raw_results["L"] = False
    valid_metrics["L"] = True

    inst_hold = info.get("heldPercentInstitutions")
    if inst_hold is not None and pd.notna(inst_hold):
        raw_results["I"] = bool(inst_hold > 0.30)
        valid_metrics["I"] = True
    else:
        raw_results["I"] = False
        valid_metrics["I"] = False

    if bench_daily is not None and len(bench_daily) >= 200:
        bench_close = bench_daily["Close"]
        bench_sma200 = bench_close.rolling(200).mean().iloc[-1]
        raw_results["M"] = bool(bench_close.iloc[-1] > bench_sma200)
    else:
        raw_results["M"] = False
    valid_metrics["M"] = True

    active_passed = 0
    active_total = 0
    passed_labels = []

    for k in DEFAULT_FUND_PARAMS:
        if st.session_state.get(f"fund_{k}", True):
            if valid_metrics.get(k, True):
                active_total += 1
                if raw_results.get(k, False):
                    active_passed += 1
                    passed_labels.append(k)

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    status_str = ",".join(passed_labels) if passed_labels else "None"
    return round(norm_score, 2), status_str, raw_results


def compute_technical_score(daily: pd.DataFrame):
    if daily is None or len(daily) < 30:
        return 0.0, "0/0", {}

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
    near_50_pct = abs(last_close - sma50) / sma50 * 100 if pd.notna(sma50) else 99
    raw["T1"] = bool(pd.notna(sma200) and last_close > sma200 and near_50_pct <= 5)

    vol_pct = close.tail(10).std() / close.tail(10).mean() * 100
    near_20_pct = abs(last_close - sma20) / sma20 * 100 if pd.notna(sma20) else 99
    raw["T2"] = bool((near_50_pct <= 5 or near_20_pct <= 5) and vol_pct <= 6)
    raw["T3"] = bool(pd.notna(sma200) and last_close <= 1.25 * sma200 and last_close > sma200)
    raw["T4"] = bool(slope_up(d["SMA50"], 5) and slope_up(d["SMA200"], 5))
    raw["T5"] = bool(rsi_monthly is not None and not rsi_monthly.empty and rsi_monthly.iloc[-1] > 50 and is_rising(rsi_monthly, 2))
    raw["T6"] = bool(rsi_weekly is not None and not rsi_weekly.empty and rsi_weekly.iloc[-1] > 50 and is_rising(rsi_weekly, 2))
    raw["T7"] = bool(pd.notna(rsi_daily) and rsi_daily > 50 and is_rising(d["RSI14"], 2))
    raw["T8"] = bool(macd_m is not None and not macd_m.empty and is_rising(macd_m.iloc[:, 0], 2))

    if macd_w is not None and not macd_w.empty:
        raw["T9"] = bool(macd_w.iloc[-1, 0] > macd_w.iloc[-1, 2] and macd_w.iloc[-1, 0] > 0 and is_rising(macd_w.iloc[:, 0], 2))
    else:
        raw["T9"] = False

    raw["T10"] = bool(macd_d is not None and not macd_d.empty and is_rising(macd_d.iloc[:, 0], 2))

    active_passed = 0
    active_total = 0

    for k in DEFAULT_TECH_PARAMS:
        if st.session_state.get(f"tech_{k}", True):
            active_total += 1
            if raw.get(k, False):
                active_passed += 1

    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    status_str = f"{active_passed}/{active_total}"
    return round(norm_score, 2), status_str, raw


def compute_relative_strength_score(daily: pd.DataFrame, bench_daily: pd.DataFrame, sector_avg_ret: float, lookback: int = 63):
    if daily is None or bench_daily is None or len(daily) < 10 or len(bench_daily) < 10:
        return 0.0, "B:N/A | S:N/A", {}

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
    status_str = f"B:{outperform_bench:+.1f}% | S:{outperform_sector:+.1f}%"

    raw_rs = {
        "RS1_score": round(score_rs1, 2),
        "RS1_diff": round(outperform_bench, 2),
        "RS2_score": round(score_rs2, 2),
        "RS2_diff": round(outperform_sector, 2)
    }
    return round(norm_score, 2), status_str, raw_rs


def execute_scan(ticker_list, w_fund, w_tech, w_rs):
    bench_daily = fetch_daily(BENCHMARK)
    stock_data = {}
    sector_returns = {}
    
    progress = st.progress(0, text="Evaluating universe...")
    for i, tkr in enumerate(ticker_list):
        progress.progress((i + 1) / len(ticker_list), text=f"Processing {tkr}...")
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

    for tkr in ticker_list:
        if tkr not in stock_data:
            skipped.append(tkr)
            continue
        
        daily = stock_data[tkr]["daily"]
        info = stock_data[tkr]["info"]
        raw_sec = info.get("sector", "Unknown")
        sec_abbrev = abbreviate_sector(raw_sec)
        sec_ret = sector_avg.get(raw_sec, np.nan)

        fund_score, fund_status, raw_fund = compute_fundamental_score(info, daily, bench_daily)
        tech_score, tech_status, raw_tech = compute_technical_score(daily)
        rs_score, rs_status, raw_rs = compute_relative_strength_score(daily, bench_daily, sec_ret)

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
            "Sector": sec_abbrev,
            "raw_fund": raw_fund,
            "raw_tech": raw_tech,
            "raw_rs": raw_rs,
        })

    return pd.DataFrame(results), skipped

# ----------------------------------------------------------------------------------
# Sidebar Controls & Weight Auto-Saver
# ----------------------------------------------------------------------------------
st.sidebar.header("⚙️ Engine Controls")

st.sidebar.subheader("1. Pillar Weights (Sum to 10)")

w_fund = st.sidebar.slider(
    "Fundamental Weight", 0, 10, key="w_fund", on_change=save_user_settings_to_db
)
w_tech = st.sidebar.slider(
    "Technical Weight", 0, 10, key="w_tech", on_change=save_user_settings_to_db
)

w_rs_calc = 10 - w_fund - w_tech

if w_rs_calc < 0:
    st.sidebar.error("Weight total exceeds 10. Adjust sliders.")
    w_rs = 0
else:
    w_rs = w_rs_calc
    st.sidebar.metric("Relative Strength Weight", w_rs)

st.sidebar.divider()

st.sidebar.subheader("2. Pillar Customization")
if st.sidebar.button("⚙️ Fundamental Rules", use_container_width=True):
    customize_fundamental_modal()

if st.sidebar.button("⚙️ Technical Rules", use_container_width=True):
    customize_technical_modal()

if st.sidebar.button("⚙️ Relative Strength Rules", use_container_width=True):
    customize_rs_modal()

# ----------------------------------------------------------------------------------
# Dynamic Navigation Tabs (Admin Tab Unlocked Conditionally)
# ----------------------------------------------------------------------------------
tab_list = ["🔍 Stock Screener", "💼 Portfolio Evaluator", "ℹ️ User Guide"]
if user_is_admin:
    tab_list.append("🛠️ Admin Panel")

tabs = st.tabs(tab_list)
tab_screener = tabs[0]
tab_portfolio = tabs[1]
tab_guide = tabs[2]
tab_admin = tabs[3] if user_is_admin else None

# ==================================================================================
# TAB 1: STOCK SCREENER
# ==================================================================================
with tab_screener:
    st.sidebar.divider()
    st.sidebar.subheader("3. Screener Universe")
    
    with st.sidebar.expander("📤 Upload Custom CSV List", expanded=False):
        uploaded_csv = st.file_uploader("Upload Universe CSV", type=["csv"], key="scr_csv", label_visibility="collapsed")

    csv_tickers = []
    if uploaded_csv is not None:
        try:
            csv_df = pd.read_csv(uploaded_csv)
            csv_tickers = parse_broker_symbols(csv_df)
            if csv_tickers:
                st.sidebar.success(f"Loaded {len(csv_tickers)} tickers.")
        except Exception as e:
            st.sidebar.error(f"Error parsing universe file: {e}")

    full_options = list(dict.fromkeys(DEFAULT_UNIVERSE + csv_tickers))
    selected_universe = st.sidebar.multiselect("Active Tickers", options=full_options, default=(csv_tickers if csv_tickers else DEFAULT_UNIVERSE))
    custom_raw = st.sidebar.text_input("Add Custom Tickers", value="")
    custom_tickers = [t.strip().upper() if t.strip().upper().endswith(".NS") else f"{t.strip().upper()}.NS" for t in custom_raw.split(",") if t.strip()]
    universe = list(dict.fromkeys(selected_universe + custom_tickers))

    run_scan = st.sidebar.button("🔍 Run Screener Scan", use_container_width=True)

    if run_scan:
        if not universe:
            st.warning("Select at least one ticker.")
        else:
            st.cache_data.clear()
            with st.spinner("Running quantitative scan..."):
                results_df, skipped = execute_scan(universe, w_fund, w_tech, w_rs)
                st.session_state["results_df"] = results_df
                st.session_state["skipped_tickers"] = skipped

    if "results_df" in st.session_state:
        df = st.session_state["results_df"]
        skipped = st.session_state.get("skipped_tickers", [])

        if not df.empty:
            df = df.sort_values("Total Score", ascending=False).reset_index(drop=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("Screened Tickers", len(df))
            c2.metric("Highest Total Score", f"{df['Total Score'].max():.2f}")
            c3.metric("Average Score", f"{df['Total Score'].mean():.2f}")

            st.divider()

            # TradingView Exporter
            st.subheader("📈 TradingView 1-Click Clipboard Exporter")
            col_tv1, col_tv2 = st.columns([1, 2])
            
            with col_tv1:
                threshold = st.slider("Min Score Filter", 0.0, 10.0, 6.0, 0.5)
            
            filtered_df = df[df["Total Score"] >= threshold]
            tv_symbols = [f"NSE:{s.replace('.NS', '')}" for s in filtered_df["Ticker"].tolist()]
            tv_content = ",".join(tv_symbols)

            with col_tv2:
                st.write(f"**{len(tv_symbols)} matching tickers** ($\ge {threshold:.1f}$). Copy below ➡️")
                if tv_symbols:
                    st.code(tv_content, language="text")
                else:
                    st.info("No tickers match this score threshold.")

            st.divider()

            # Screening Table
            st.subheader("📋 Screening Results Table")
            st.info("💡 **Symbol name** stays frozen on the left when swiping horizontally.")

            display_table = df[[
                "Ticker", "Total Score", "Fundamental Score", 
                "Technical Score", "Relative Strength Score", 
                "Tech Passed", "CANSLIM Hits", "RS Details", "Sector"
            ]].copy()

            st.dataframe(
                display_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn(
                        "Symbol",
                        pinned=True,
                        width="small"
                    ),
                    "Total Score": st.column_config.NumberColumn("Total", format="%.2f"),
                    "Fundamental Score": st.column_config.NumberColumn("Fund", format="%.2f"),
                    "Technical Score": st.column_config.NumberColumn("Tech", format="%.2f"),
                    "Relative Strength Score": st.column_config.NumberColumn("RS", format="%.2f"),
                }
            )

# ==================================================================================
# TAB 2: PORTFOLIO EVALUATOR
# ==================================================================================
with tab_portfolio:
    st.subheader("💼 Multi-Broker Portfolio Health Evaluator")
    st.caption("Supports raw holdings exports from Zerodha, Groww, Dhan, Upstox, Angel One, ICICI Direct, and Kotak.")
    
    col_input1, col_input2 = st.columns([1, 1])
    parsed_portfolio_tickers = []
    
    with col_input1:
        st.markdown("##### **Option A: Upload Broker Holdings Export**")
        port_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"], key="port_upload")
        
        if port_file is not None:
            try:
                if port_file.name.endswith(".csv"):
                    p_df = pd.read_csv(port_file)
                else:
                    p_df = pd.read_excel(port_file)
                    
                parsed_portfolio_tickers = parse_broker_symbols(p_df)
                if parsed_portfolio_tickers:
                    st.success(f"✅ Auto-parsed **{len(parsed_portfolio_tickers)} symbols**.")
                else:
                    st.error("⚠️ Could not detect symbol column. Use Option B.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    with col_input2:
        st.markdown("##### **Option B: Paste Stock Symbols Directly**")
        raw_pasted = st.text_area("Paste symbols (comma, space, or line separated):", placeholder="TATAMOTORS, HDFCBANK, TRENT, AUBANK", height=100)
        
        if raw_pasted.strip():
            delimiters = [",", "\n", " ", ";"]
            temp_str = raw_pasted
            for d in delimiters:
                temp_str = temp_str.replace(d, "|")
            pasted_symbols = [s.strip().upper() for s in temp_str.split("|") if s.strip()]
            
            pasted_formatted = [
                f"{s.replace('NSE:', '').replace('-EQ', '')}.NS" if not s.endswith(".NS") else s
                for s in pasted_symbols
            ]
            
            if not parsed_portfolio_tickers:
                parsed_portfolio_tickers = list(dict.fromkeys(pasted_formatted))
                st.info(f"Loaded **{len(parsed_portfolio_tickers)} symbols** from text.")

    st.divider()

    if parsed_portfolio_tickers:
        st.write(f"**Loaded Holdings ({len(parsed_portfolio_tickers)}):** `" + ", ".join([s.replace(".NS", "") for s in parsed_portfolio_tickers]) + "`")
        
        if st.button("🚀 Evaluate Portfolio Health", use_container_width=True):
            with st.spinner("Evaluating portfolio holdings against 3-Pillar engine..."):
                p_results, p_skipped = execute_scan(parsed_portfolio_tickers, w_fund, w_tech, w_rs)
                
                if not p_results.empty:
                    p_results = p_results.sort_values("Total Score", ascending=False).reset_index(drop=True)
                    
                    p_avg_score = p_results["Total Score"].mean()
                    p_weak = p_results[p_results["Total Score"] < 5.0]
                    p_strong = p_results[p_results["Total Score"] >= 7.0]

                    col_p1, col_p2, col_p3 = st.columns(3)
                    col_p1.metric("Portfolio Health Score", f"{p_avg_score:.2f} / 10")
                    col_p2.metric("Strong Holdings (Score ≥ 7.0)", len(p_strong))
                    col_p3.metric("Weak Holdings (Score < 5.0)", len(p_weak))

                    st.divider()
                    st.subheader("📊 Portfolio Scoring Matrix")

                    p_table = p_results[[
                        "Ticker", "Total Score", "Fundamental Score", 
                        "Technical Score", "Relative Strength Score", 
                        "Tech Passed", "CANSLIM Hits", "RS Details", "Sector"
                    ]].copy()

                    st.dataframe(
                        p_table,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Ticker": st.column_config.TextColumn(
                                "Symbol",
                                pinned=True,
                                width="small"
                            ),
                            "Total Score": st.column_config.NumberColumn("Total", format="%.2f"),
                            "Fundamental Score": st.column_config.NumberColumn("Fund", format="%.2f"),
                            "Technical Score": st.column_config.NumberColumn("Tech", format="%.2f"),
                            "Relative Strength Score": st.column_config.NumberColumn("RS", format="%.2f"),
                        }
                    )

                    st.divider()
                    st.download_button(
                        label="⬇️ Export Portfolio Evaluation CSV",
                        data=p_results.to_csv(index=False).encode("utf-8"),
                        file_name="portfolio_evaluation_results.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

# ==================================================================================
# TAB 3: USER GUIDE
# ==================================================================================
with tab_guide:
    st.subheader("ℹ️ Application Overview & User Guide")
    st.markdown(
        """
        Automated quantitative scoring engine for Indian equities (NSE). Evaluates stocks using 
        **CANSLIM fundamental growth**, **10-point multi-timeframe technical momentum**, and 
        **relative strength**.
        """
    )

    st.divider()

    st.markdown("### 🏛️ The 3 Scoring Pillars")

    col_g1, col_g2, col_g3 = st.columns(3)

    with col_g1:
        st.markdown("#### 1. Fundamental Pillar")
        st.markdown(
            """
            * **C:** Current EPS Growth > 15%
            * **A:** Annual Revenue Growth > 10%
            * **N:** Near 52-Week High (within 25%)
            * **S:** Tight Base Consolidation
            * **L:** Daily RSI > 55
            * **I:** Institutional Ownership > 30%
            * **M:** Broad Market Direction
            """
        )

    with col_g2:
        st.markdown("#### 2. Technical Pillar")
        st.markdown(
            """
            * **Moving Averages:** 200 DMA & 50 DMA upward slope.
            * **Consolidation:** Proximity to 50/20 DMA.
            * **Multi-Timeframe RSI:** Monthly, Weekly, Daily > 50 & rising.
            * **Multi-Timeframe MACD:** Positive momentum alignment.
            """
        )

    with col_g3:
        st.markdown("#### 3. Relative Strength")
        st.markdown(
            """
            * **RS vs Market:** Outperformance vs Nifty 50 (^NSEI).
            * **RS vs Sector:** Outperformance vs sector average return.
            """
        )

# ==================================================================================
# TAB 4: ADMIN PANEL (RESTRICTED ACCESS)
# ==================================================================================
if user_is_admin and tab_admin is not None:
    with tab_admin:
        st.subheader("🛠️ Administrator Control & Database Inspection")
        st.success(f"Authenticated as Admin: `{user_email}`")
        
        st.divider()
        
        col_adm1, col_adm2 = st.columns([1, 1])
        
        with col_adm1:
            st.markdown("#### 📊 System Status & Active Session")
            st.json({
                "User Email": user_email,
                "Is Admin": True,
                "Supabase Connected": SUPABASE_AVAILABLE and get_supabase_client() is not None,
                "Default Universe Size": len(DEFAULT_UNIVERSE),
                "Active Weights": {
                    "Fundamental": w_fund,
                    "Technical": w_tech,
                    "Relative Strength": w_rs
                }
            })
            
            if st.button("🧹 Clear Streamlit Data Cache", use_container_width=True):
                st.cache_data.clear()
                st.success("Global application cache cleared successfully.")

        with col_adm2:
            st.markdown("#### 🗄️ Database Inspection (`user_settings` Table)")
            supabase = get_supabase_client()
            if supabase:
                try:
                    res = supabase.table("user_settings").select("*").execute()
                    if res.data:
                        admin_db_df = pd.DataFrame(res.data)
                        st.dataframe(admin_db_df, use_container_width=True)
                    else:
                        st.info("No saved user records found in `user_settings` table yet.")
                except Exception as e:
                    st.error(f"Error reading Supabase table: {e}")
            else:
                st.warning("Supabase connection unavailable in local or dev mode.")

# ----------------------------------------------------------------------------------
# Footer
# ----------------------------------------------------------------------------------
st.divider()
st.caption(
    "**Disclaimer:** Third-party data feeds may be delayed or unsynchronized. "
    "Strictly educational content, not financial advice. Verify all setups prior to trading. "
    "For queries: vkiyer@hotmail.com."
)