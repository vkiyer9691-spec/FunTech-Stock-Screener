"""
NSE Stock Screener — Interactive Analysis Engine (Auth Gated, Admin Enabled & Supabase Persisted)
----------------------------------------------------------------------------------
Includes Enforced Main-Screen Supabase Authentication, Settings Persistence (Save/Load),
Dynamic Database-Driven Admin Privilege Checking, Multi-Broker Auto-Parser, 
Parallel Execution Engine, and 1-Click TradingView Exporter.
Run with: streamlit run app.py
"""
import os
import time
import re
import csv
import io
import json
import uuid
from pathlib import Path
import requests
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import pandas_ta as ta

def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False

def _ss_get(key, default=None):
    if _SCORE_OVERRIDES is not None:
        return _SCORE_OVERRIDES.get(key, default)
    if not _in_streamlit():
        return default
    try:
        return st.session_state.get(key, default)
    except Exception:
        return default

_SCORE_OVERRIDES = None

def set_score_overrides(overrides: dict | None) -> None:
    """Apply a user's saved rule toggles for a non-UI digest scan."""
    global _SCORE_OVERRIDES
    _SCORE_OVERRIDES = overrides

def _cfg(name: str, nested_section: str | None = None, nested_key: str | None = None) -> str:
    env = str(os.environ.get(name) or "").strip()
    if env:
        return env
    try:
        val = st.secrets.get(name)
        if val:
            return str(val).strip()
        if nested_section and nested_key:
            section = st.secrets.get(nested_section) or {}
            return str(section.get(nested_key) or "").strip()
    except Exception:
        pass
    return ""

# Optional Supabase Import with Graceful Fallback
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ----------------------------------------------------------------------------------
# Page Config & CSS Scaffolding
# ----------------------------------------------------------------------------------

def _apply_page_chrome():
    st.set_page_config(
        page_title="NSE Stock Screener & Portfolio Evaluator",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        section[data-testid="stSidebar"],
        div[data-testid="collapsedControl"],
        div[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
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
# Constants & Defaults
# ----------------------------------------------------------------------------------
BENCHMARK = "^NSEI"

NSE_INDEX_FILES = {
    "Nifty 50": "ind_nifty50list",
    "Nifty Next 50": "ind_niftynext50list",
    "Nifty Midcap 150": "ind_niftymidcap150list",
    "Nifty Smallcap 250": "ind_niftysmallcap250list",
    "Nifty 500": "ind_nifty500list",
}
UNIVERSE_SOURCE_OPTIONS = list(NSE_INDEX_FILES.keys()) + ["F&O Stocks"]

AVAILABLE_SETUPS = [
    "Pullback (DW)",
    "Pullback (WM)",
    "Breakout Retest",
    "RSI Resumption",
    "Vol Squeeze",
    "20-EMA Bounce",
    "Bottom Fisher",
    "Pocket Pivot",
]

DEFAULT_FUND_PARAMS = {
    "C": "C: Quarterly EPS vs same quarter last year > 15%",
    "A": "A: Quarterly Total Revenue vs same quarter last year > 10%",
    "N": "N: Within 10% of 52-week high",
    "S": "S: Demand — more volume on up days than down days (20 sessions)",
    "L": "L: 63-day return beats Nifty 50",
    "Ls": "Ls: 63-day return beats sector peers in this scan",
    "I": "I: Institutional ownership > 30%",
    "M": "M: Nifty 50 above its 200-DMA",
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
FUND_HELP = {
    "C": "On: latest-quarter diluted EPS (else net income) must be more than 15% above the same quarter last year. Yahoo’s annual growth rate is not used. Off: this rule is ignored.",
    "A": "On: latest-quarter Total Revenue must be more than 10% above the same quarter last year. Yahoo’s annual sales growth is not used. Off: this rule is ignored.",
    "N": "On: last price must sit within 10% of the 52-week high (the high is the better of Yahoo’s figure and the last 252 daily highs). Off: proximity to highs is ignored.",
    "S": "On: over the last 20 sessions, volume on up-close days must exceed volume on down-close days. Tight bases are scored in T1/T2, not here. Off: this rule is ignored.",
    "L": "On: the stock’s ~3-month (63-day) return must beat Nifty 50. Off: vs-Nifty leadership is ignored.",
    "Ls": "On: the same 63-day return must beat the average of same-sector names in this scan. Skipped when sector is unknown. Off: vs-sector leadership is ignored.",
    "I": "On: Yahoo institutional ownership must be above 30% of shares outstanding (promoter-heavy names often fail). Off: ownership is ignored.",
    "M": "On: Nifty 50 must be above its 200-day average. Every stock in the scan gets the same result. Off: market direction is ignored.",
}
TECH_HELP = {
    "T1": "On: close must be above the 200-DMA and within 5% of the 50-DMA. Off: this trend/mean-reversion check is skipped.",
    "T2": "On: price must be coiled near the 50- and 20-DMA. Off: consolidation is not scored.",
    "T3": "On: close cannot be more than 25% above the 200-DMA (early Stage 2). Off: extension is ignored.",
    "T4": "On: both 200-DMA and 50-DMA must be sloping up over the last 5 bars. Off: moving-average slope is ignored.",
    "T5": "On: monthly RSI must be above 50 and rising. Off: monthly RSI is ignored.",
    "T6": "On: weekly RSI must be above 50 and rising. Off: weekly RSI is ignored.",
    "T7": "On: daily RSI must be above 50 and rising. Off: daily RSI is ignored.",
    "T8": "On: monthly MACD line must be rising. Off: monthly MACD is ignored.",
    "T9": "On: weekly MACD must have a positive crossover and a rising line. Off: weekly MACD is ignored.",
    "T10": "On: daily MACD line must be rising. Off: daily MACD is ignored.",
}
SECTOR_MAP = {
    "Financial Services": "Fin Services", "Consumer Cyclical": "Cons Cyclical",
    "Consumer Defensive": "Cons Defensive", "Healthcare": "Healthcare",
    "Technology": "Tech", "Industrials": "Industrials", "Basic Materials": "Materials",
    "Energy": "Energy", "Utilities": "Utilities", "Real Estate": "Real Estate",
    "Communication Services": "Comm Services", "Unknown": "Unknown"
}
BROKER_SYMBOL_HEADERS = [
    "instrument", "trading symbol", "tradingsymbol", "symbol", 
    "ticker", "company name", "stock name", "stock", "scrip name", "display name"
]

@st.cache_resource
def _get_freshness_tracker() -> dict:
    return {}

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

FALLBACK_INDEX_LISTS = {
    "Nifty 50": [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "BHARTIARTL.NS",
        "ITC.NS", "LT.NS", "SBIN.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "MARUTI.NS",
        "M&M.NS", "SUNPHARMA.NS", "TATAMOTORS.NS", "KOTAKBANK.NS", "ULTRACEMCO.NS", "TITAN.NS",
        "AXISBANK.NS", "NTPC.NS", "ADANIENT.NS", "POWERGRID.NS", "ASIANPAINT.NS", "COALINDIA.NS",
        "BAJAJFINSV.NS", "NESTLEIND.NS", "ONGC.NS", "TATASTEEL.NS", "HCLTECH.NS", "JSWSTEEL.NS",
        "WIPRO.NS", "GRASIM.NS", "TECHM.NS", "INDUSINDBK.NS", "CIPLA.NS", "SBILIFE.NS",
        "HDFCLIFE.NS", "DRREDDY.NS", "APOLLOHOSP.NS", "BRITANNIA.NS", "EICHERMOT.NS", "DIVISLAB.NS",
        "HINDALCO.NS", "BPCL.NS", "TATACONSUM.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "SHRIRAMFIN.NS",
        "ADANIPORTS.NS", "TRENT.NS",
    ],
    "Nifty Next 50": [
        "ABB.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS", "BANKBARODA.NS",
        "BEL.NS", "BOSCHLTD.NS", "CANBK.NS", "CHOLAFIN.NS", "DLF.NS", "GAIL.NS",
        "GODREJCP.NS", "HAL.NS", "ICICIGI.NS", "ICICIPRULI.NS", "INDHOTEL.NS", "IOC.NS",
        "IRFC.NS", "JINDALSTEL.NS", "LTIM.NS", "LODHA.NS", "PFC.NS", "PIDILITIND.NS",
        "PNB.NS", "RECLTD.NS", "SIEMENS.NS", "TATAPOWER.NS", "TVSMOTOR.NS", "VBL.NS", "VEDL.NS", "ZOMATO.NS",
    ],
    "Nifty Midcap 150": [
        "AUBANK.NS", "PERSISTENT.NS", "COFORGE.NS", "SUPREMEIND.NS", "POLYCAB.NS", "MPHASIS.NS",
        "ASTRAL.NS", "OBEROIRLTY.NS", "PAGEIND.NS", "MFSL.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS",
        "AUROPHARMA.NS", "BALKRISIND.NS", "GODREJPROP.NS", "TIINDIA.NS", "APLAPOLLO.NS", "CUMMINSIND.NS",
    ],
    "Nifty Smallcap 250": [
        "CENTURYPLY.NS", "RATNAMANI.NS", "ROUTE.NS", "TTKPRESTIG.NS", "CAMPUS.NS", "REDINGTON.NS",
        "GESHIP.NS", "SHYAMMETL.NS", "TRIVENI.NS", "GRINDWELL.NS", "JKLAKSHMI.NS", "KIRLOSENG.NS",
    ],
    "Nifty 500": [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "AUBANK.NS",
        "TRENT.NS", "HAL.NS", "TATAMOTORS.NS", "BAJFINANCE.NS", "LT.NS", "SBIN.NS",
        "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS",
    ],
}
FALLBACK_FO_STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "BHARTIARTL.NS",
    "ITC.NS", "LT.NS", "SBIN.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "MARUTI.NS",
    "M&M.NS", "SUNPHARMA.NS", "TATAMOTORS.NS", "KOTAKBANK.NS", "ULTRACEMCO.NS", "TITAN.NS",
    "AXISBANK.NS", "NTPC.NS", "ADANIENT.NS", "POWERGRID.NS", "ASIANPAINT.NS", "COALINDIA.NS",
    "BAJAJFINSV.NS", "NESTLEIND.NS", "TATASTEEL.NS", "HCLTECH.NS", "JSWSTEEL.NS", "WIPRO.NS",
    "GRASIM.NS", "TECHM.NS", "INDUSINDBK.NS", "CIPLA.NS", "SBILIFE.NS", "HDFCLIFE.NS",
    "DRREDDY.NS", "APOLLOHOSP.NS", "BRITANNIA.NS", "EICHERMOT.NS", "DIVISLAB.NS", "HINDALCO.NS",
    "BPCL.NS", "TATACONSUM.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "SHRIRAMFIN.NS", "ADANIPORTS.NS",
    "TRENT.NS", "ONGC.NS", "DLF.NS", "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS",
    "AUBANK.NS", "PFC.NS", "RECLTD.NS", "IRFC.NS", "MFSL.NS", "CHOLAFIN.NS",
    "ICICIGI.NS", "ICICIPRULI.NS", "LICHSGFIN.NS", "BANDHANBNK.NS", "PEL.NS", "MUTHOOTFIN.NS",
    "SBICARD.NS", "M&MFIN.NS", "IDBI.NS", "IEX.NS", "CDSL.NS", "BSE.NS", "ANGELONE.NS",
    "IIFL.NS", "POONAWALLA.NS", "PNBHOUSING.NS", "LTIM.NS", "MPHASIS.NS", "PERSISTENT.NS", "COFORGE.NS", "LTTS.NS", "OFSS.NS", "TATAELXSI.NS",
    "TVSMOTOR.NS", "ASHOKLEY.NS", "BOSCHLTD.NS", "MOTHERSON.NS", "BALKRISIND.NS", "MRF.NS",
    "EXIDEIND.NS", "BHARATFORG.NS", "TIINDIA.NS", "APOLLOTYRE.NS", "VEDL.NS", "NMDC.NS", "SAIL.NS", "JINDALSTEL.NS", "NATIONALUM.NS", "HINDCOPPER.NS",
    "GAIL.NS", "IOC.NS", "PETRONET.NS", "IGL.NS", "ATGL.NS", "ADANIENSOL.NS", "ADANIGREEN.NS",
    "ADANIPOWER.NS", "TATAPOWER.NS", "NHPC.NS", "SJVN.NS", "AMBUJACEM.NS", "SHREECEM.NS", "ACC.NS", "JKCEMENT.NS", "DALBHARAT.NS", "IRCTC.NS",
    "RVNL.NS", "HAL.NS", "BEL.NS", "BHEL.NS", "CUMMINSIND.NS", "SIEMENS.NS", "ABB.NS",
    "POLYCAB.NS", "HAVELLS.NS", "AUROPHARMA.NS", "LUPIN.NS", "TORNTPHARM.NS", "ALKEM.NS", "BIOCON.NS", "ZYDUSLIFE.NS",
    "GLENMARK.NS", "LAURUSLABS.NS", "IPCALAB.NS", "MANKIND.NS", "GODREJCP.NS", "DABUR.NS", "MARICO.NS", "COLPAL.NS", "UBL.NS", "MCDOWELL-N.NS",
    "PIDILITIND.NS", "PAGEIND.NS", "VBL.NS", "JUBLFOOD.NS", "DMART.NS", "NYKAA.NS",
    "GODREJPROP.NS", "OBEROIRLTY.NS", "LODHA.NS", "PHOENIXLTD.NS", "PRESTIGE.NS",
    "ZOMATO.NS", "PAYTM.NS", "POLICYBZR.NS", "NAUKRI.NS", "DELHIVERY.NS",
    "PIIND.NS", "SRF.NS", "UPL.NS", "GNFC.NS", "DEEPAKNTR.NS", "AARTIIND.NS",
    "VOLTAS.NS", "CONCOR.NS", "GMRAIRPORT.NS", "INDIGO.NS", "TRIDENT.NS", "SUNTV.NS",
    "PVRINOX.NS", "ESCORTS.NS", "SYNGENE.NS", "ABFRL.NS", "IDEA.NS", "GRANULES.NS",
    "CANFINHOME.NS", "MANAPPURAM.NS", "L&TFH.NS", "INDUSTOWER.NS", "COROMANDEL.NS",
    "BALRAMCHIN.NS", "NAVINFLUOR.NS", "TATACOMM.NS", "ASTRAL.NS", "SUPREMEIND.NS",
    "APLAPOLLO.NS", "HINDPETRO.NS", "RAMCOCEM.NS", "METROPOLIS.NS", "LALPATHLAB.NS",
]
SYMBOL_SECTOR_MAP = {}

def _register_sector(sector_name: str, tickers: list):
    for t in tickers:
        SYMBOL_SECTOR_MAP[t] = sector_name
_register_sector("Financial Services", [
    "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS",
    "BAJAJFINSV.NS", "INDUSINDBK.NS", "SBILIFE.NS", "HDFCLIFE.NS", "SHRIRAMFIN.NS", "PNB.NS",
    "BANKBARODA.NS", "CANBK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS", "AUBANK.NS", "PFC.NS",
    "RECLTD.NS", "IRFC.NS", "MFSL.NS", "CHOLAFIN.NS", "ICICIGI.NS", "ICICIPRULI.NS",
    "LICHSGFIN.NS", "BANDHANBNK.NS", "PEL.NS", "MUTHOOTFIN.NS", "SBICARD.NS", "M&MFIN.NS",
    "IDBI.NS", "IEX.NS", "CDSL.NS", "BSE.NS", "ANGELONE.NS", "IIFL.NS", "POONAWALLA.NS",
    "PNBHOUSING.NS", "CANFINHOME.NS", "MANAPPURAM.NS", "L&TFH.NS",
])
_register_sector("Technology", [
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS", "MPHASIS.NS",
    "PERSISTENT.NS", "COFORGE.NS", "LTTS.NS", "OFSS.NS", "TATAELXSI.NS",
])
_register_sector("Consumer Cyclical", [
    "MARUTI.NS", "M&M.NS", "TATAMOTORS.NS", "TITAN.NS", "EICHERMOT.NS", "BAJAJ-AUTO.NS",
    "HEROMOTOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "MOTHERSON.NS", "BALKRISIND.NS", "MRF.NS",
    "EXIDEIND.NS", "BHARATFORG.NS", "TIINDIA.NS", "APOLLOTYRE.NS", "TRENT.NS", "DMART.NS",
    "NYKAA.NS", "PAGEIND.NS", "JUBLFOOD.NS", "INDIGO.NS", "PVRINOX.NS", "IRCTC.NS",
])
_register_sector("Consumer Defensive", [
    "ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS", "GODREJCP.NS",
    "DABUR.NS", "MARICO.NS", "COLPAL.NS", "UBL.NS", "MCDOWELL-N.NS", "VBL.NS",
])
_register_sector("Healthcare", [
    "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "APOLLOHOSP.NS", "DIVISLAB.NS", "AUROPHARMA.NS",
    "LUPIN.NS", "TORNTPHARM.NS", "ALKEM.NS", "BIOCON.NS", "ZYDUSLIFE.NS", "GLENMARK.NS",
    "LAURUSLABS.NS", "IPCALAB.NS", "MANKIND.NS", "SYNGENE.NS", "METROPOLIS.NS", "LALPATHLAB.NS",
])
_register_sector("Basic Materials", [
    "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "NMDC.NS", "SAIL.NS",
    "JINDALSTEL.NS", "NATIONALUM.NS", "HINDCOPPER.NS", "UPL.NS", "GNFC.NS", "DEEPAKNTR.NS",
    "AARTIIND.NS", "SRF.NS", "PIIND.NS", "COROMANDEL.NS", "BALRAMCHIN.NS", "NAVINFLUOR.NS",
    "AMBUJACEM.NS", "SHREECEM.NS", "ACC.NS", "JKCEMENT.NS", "DALBHARAT.NS", "RAMCOCEM.NS",
])
_register_sector("Energy", [
    "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "GAIL.NS", "IOC.NS", "PETRONET.NS", "IGL.NS",
    "ATGL.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "TATAPOWER.NS", "NHPC.NS",
    "SJVN.NS", "COALINDIA.NS", "NTPC.NS", "POWERGRID.NS", "HINDPETRO.NS",
])
_register_sector("Industrials", [
    "LT.NS", "ADANIPORTS.NS", "ADANIENT.NS", "RVNL.NS", "HAL.NS", "BEL.NS", "BHEL.NS",
    "CUMMINSIND.NS", "SIEMENS.NS", "ABB.NS", "POLYCAB.NS", "HAVELLS.NS", "VOLTAS.NS",
    "CONCOR.NS", "GMRAIRPORT.NS", "ESCORTS.NS", "ASTRAL.NS", "SUPREMEIND.NS", "APLAPOLLO.NS",
])
_register_sector("Real Estate", [
    "DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "LODHA.NS", "PHOENIXLTD.NS", "PRESTIGE.NS",
])
_register_sector("Communication Services", [
    "BHARTIARTL.NS", "IDEA.NS", "INDUSTOWER.NS", "TATACOMM.NS", "SUNTV.NS", "NAUKRI.NS",
])

def _nse_session(referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    })
    session.get(referer, timeout=6)
    return session

def _fo_tier1_stock_indices() -> list:
    for _ in range(2):
        try:
            session = _nse_session("https://www.nseindia.com/market-data/live-equity-market")
            resp = session.get(
                "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O",
                timeout=8,
            )
            if resp.status_code == 200:
                rows = resp.json().get("data", [])
                tickers = sorted(set(
                    f"{r['symbol'].strip().upper()}.NS" for r in rows
                    if r.get("symbol") and not r["symbol"].upper().startswith("NIFTY")
                ))
                if len(tickers) >= 100:
                    return tickers
        except Exception:
            pass
        time.sleep(0.5)
    return []

def _fo_tier2_equity_master() -> list:
    try:
        session = _nse_session("https://www.nseindia.com/market-data/live-equity-market")
        resp = session.get("https://www.nseindia.com/api/equity-master", timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                tickers = set()
                for key, val in data.items():
                    key_norm = key.lower().replace("&", "").replace(" ", "").replace("_", "")
                    if "fo" in key_norm or "fno" in key_norm or "futuresoptions" in key_norm:
                        if isinstance(val, list):
                            for s in val:
                                if isinstance(s, str) and s.strip() and not s.upper().startswith("NIFTY"):
                                    tickers.add(f"{s.strip().upper()}.NS")
                tickers = sorted(tickers)
                if len(tickers) >= 100:
                    return tickers
    except Exception:
        pass
    return []

def _parse_fo_mktlots_csv(text: str) -> list:
    lines = text.splitlines()
    start_idx = next((i for i, ln in enumerate(lines) if "derivatives on individual securities" in ln.lower()), None)
    if start_idx is None or start_idx + 1 >= len(lines):
        return []
    header = next(csv.reader([lines[start_idx + 1]]))
    symbol_col = next((i for i, h in enumerate(header) if h.strip().lower() == "symbol"), None)
    if symbol_col is None:
        return []
    tickers = set()
    symbol_pattern = re.compile(r"^[A-Z0-9&\-]{1,20}$")
    for line in lines[start_idx + 2:]:
        if not line.strip():
            break
        row = next(csv.reader([line]))
        if len(row) <= symbol_col:
            continue
        sym = row[symbol_col].strip().upper()
        if sym and symbol_pattern.match(sym) and not sym.startswith("NIFTY"):
            tickers.add(f"{sym}.NS")
    return sorted(tickers)

def _fo_tier3_dated_csv() -> list:
    today = date.today()
    candidate_dates = set()
    for months_back in range(2):
        year, month = today.year, today.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        if month == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        for offset in range(-3, 2): 
            candidate_dates.add(last_day + timedelta(days=offset))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for d in sorted(candidate_dates, reverse=True):
        url = f"https://nsearchives.nseindia.com/content/fo/fo_mktlots_{d.strftime('%d%m%Y')}.csv"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200 and "symbol" in resp.text.lower():
                tickers = _parse_fo_mktlots_csv(resp.text)
                if len(tickers) >= 100:
                    return tickers
        except Exception:
            continue
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def load_index_list(index_name: str) -> list:
    filename = NSE_INDEX_FILES.get(index_name)
    if not filename:
        return []
    urls = [
        f"https://nsearchives.nseindia.com/content/indices/{filename}.csv",
        f"https://archives.nseindia.com/content/indices/{filename}.csv",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for url in urls:
        try:
            df = pd.read_csv(url, storage_options=headers)
            symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
            if symbol_col:
                tickers = [f"{str(s).strip().upper()}.NS" for s in df[symbol_col].dropna().tolist() if str(s).strip()]
                if tickers:
                    _get_freshness_tracker()[f"universe:{index_name}"] = (pd.Timestamp.now(), "live")
                    return tickers
        except Exception:
            continue
    _get_freshness_tracker()[f"universe:{index_name}"] = (pd.Timestamp.now(), "fallback")
    return FALLBACK_INDEX_LISTS.get(index_name, [])

@st.cache_data(ttl=86400, show_spinner=False)
def load_fo_stocks() -> list:
    for tier_fn in (_fo_tier1_stock_indices, _fo_tier2_equity_master, _fo_tier3_dated_csv):
        tickers = tier_fn()
        if tickers:
            _get_freshness_tracker()["universe:F&O Stocks"] = (pd.Timestamp.now(), "live")
            return tickers
    _get_freshness_tracker()["universe:F&O Stocks"] = (pd.Timestamp.now(), "fallback")
    return FALLBACK_FO_STOCKS

@st.cache_data(ttl=1800, show_spinner=False)
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
                _get_freshness_tracker()["prices"] = pd.Timestamp.now()
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
        "sector": None,
    }
    try:
        t = yf.Ticker(ticker)
        try:
            default_info["fiftyTwoWeekHigh"] = t.fast_info.get("year_high")
            default_info["currentPrice"] = t.fast_info.get("last_price")
        except Exception:
            pass
        try:
            q_fin = t.quarterly_financials
            q_inc = None
            try:
                q_inc = t.quarterly_income_stmt
            except Exception:
                q_inc = None
            default_info["quarterly_eps_yoy"] = _yoy_latest_vs_year_ago(
                q_inc if q_inc is not None and not getattr(q_inc, "empty", True) else q_fin,
                ["diluted eps", "diluted earnings per share", "basic eps", "eps"],
            )
            default_info["quarterly_ni_yoy"] = _yoy_latest_vs_year_ago(
                q_inc if q_inc is not None and not getattr(q_inc, "empty", True) else q_fin,
                ["net income"],
            )
            default_info["quarterly_rev_yoy"] = _yoy_latest_vs_year_ago(
                q_fin if q_fin is not None and not getattr(q_fin, "empty", True) else None,
                ["total revenue", "operating revenue", "revenue"],
            )
        except Exception:
            pass
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
    if not default_info.get("sector"):
        default_info["sector"] = SYMBOL_SECTOR_MAP.get(ticker, "Unknown")
    return default_info

# ----------------------------------------------------------------------------------
# Supabase Persistence Engine & Auth
# ----------------------------------------------------------------------------------

def get_supabase_client():
    if not SUPABASE_AVAILABLE:
        return None
    url = _cfg("SUPABASE_URL", "supabase", "url")
    key = _cfg("SUPABASE_KEY", "supabase", "key")
    if url and key and url != "None" and key != "None":
        try:
            return create_client(url, key)
        except Exception:
            return None
    return None

def get_supabase_admin_client():
    if not SUPABASE_AVAILABLE:
        return None
    url = _cfg("SUPABASE_URL", "supabase", "url")
    # Tries to use the Service Role Key to bypass RLS in the Admin Panel
    key = _cfg("SUPABASE_SERVICE_KEY", "supabase", "service_key") or _cfg("SUPABASE_SERVICE_ROLE_KEY", "supabase", "service_role_key")
    if url and key and url != "None" and key != "None":
        try:
            return create_client(url, key)
        except Exception:
            return None
    return None

def is_admin(user) -> bool:
    if not user:
        return False
    email = user.get("email") if isinstance(user, dict) else getattr(user, "email", "")
    if email.lower() == "vkiyer@hotmail.com":
        return True
        
    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
    if not user_id:
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        return False
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            return str(res.data[0].get("role")).lower().strip() == "admin"
    except Exception:
        pass
    return False

def is_authorized_or_admin(user) -> bool:
    if not user:
        return False
        
    email = user.get("email") if isinstance(user, dict) else getattr(user, "email", "")
    if email.lower() == "vkiyer@hotmail.com":
        return True
        
    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
    if not user_id:
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        return False
        
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            role = str(res.data[0].get("role")).lower().strip()
            return role in ["admin", "authorized"]
    except Exception:
        pass
    return False

def init_session_defaults():
    if "w_fund" not in st.session_state:
        st.session_state["w_fund"] = 5
    if "w_tech" not in st.session_state:
        st.session_state["w_tech"] = 5
    for k in DEFAULT_FUND_PARAMS:
        if f"fund_{k}" not in st.session_state:
            st.session_state[f"fund_{k}"] = True
    for k in DEFAULT_TECH_PARAMS:
        if f"tech_{k}" not in st.session_state:
            st.session_state[f"tech_{k}"] = True
    if "digest_opt_in" not in st.session_state:
        st.session_state["digest_opt_in"] = False
    if "digest_top_n" not in st.session_state:
        st.session_state["digest_top_n"] = 10
    if "su_universes" not in st.session_state:
        st.session_state["su_universes"] = ["Nifty 50"]
    if "su_setups" not in st.session_state:
        st.session_state["su_setups"] = AVAILABLE_SETUPS.copy()

def load_user_settings_from_db(user_id: str):
    supabase = get_supabase_client()
    if not supabase or not user_id:
        return
    
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        response = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            from digest import clamp_pillar_weights
            data = response.data[0]
            w_f, w_t = clamp_pillar_weights(data.get("w_fund", 5), data.get("w_tech", 5))
            st.session_state["w_fund"] = w_f
            st.session_state["w_tech"] = w_t
            
            fund_rules = data.get("fund_rules") or {}
            for k in DEFAULT_FUND_PARAMS:
                st.session_state[f"fund_{k}"] = bool(fund_rules.get(k, True))
                
            tech_rules = data.get("tech_rules") or {}
            for k in DEFAULT_TECH_PARAMS:
                st.session_state[f"tech_{k}"] = bool(tech_rules.get(k, True))
            if "digest_opt_in" in data:
                st.session_state["digest_opt_in"] = bool(data.get("digest_opt_in"))
            if data.get("digest_top_n"):
                st.session_state["digest_top_n"] = int(data.get("digest_top_n"))
            if "setup_universes" in data and isinstance(data["setup_universes"], list):
                st.session_state["su_universes"] = data["setup_universes"]
            if "setup_patterns" in data and isinstance(data["setup_patterns"], list):
                st.session_state["su_setups"] = data["setup_patterns"]
    except Exception as e:
        st.warning(f"Could not load saved settings: {e}")

def save_user_settings_to_db():
    supabase = get_supabase_client()
    user = st.session_state.get("user")
    session = st.session_state.get("supabase_session")
    
    if not supabase or not user:
        return
    if session and hasattr(session, "access_token"):
        supabase.postgrest.auth(session.access_token)
    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
    if not user_id:
        return
    fund_dict = {k: st.session_state.get(f"fund_{k}", True) for k in DEFAULT_FUND_PARAMS}
    tech_dict = {k: st.session_state.get(f"tech_{k}", True) for k in DEFAULT_TECH_PARAMS}
    payload = {
        "user_id": user_id,
        "w_fund": st.session_state.get("w_fund", 5),
        "w_tech": st.session_state.get("w_tech", 5),
        "fund_rules": fund_dict,
        "tech_rules": tech_dict,
        "digest_opt_in": bool(st.session_state.get("digest_opt_in", False)),
        "digest_top_n": int(st.session_state.get("digest_top_n", 10)),
        "setup_universes": st.session_state.get("su_universes", ["Nifty 50"]),
        "setup_patterns": st.session_state.get("su_setups", AVAILABLE_SETUPS),
        "updated_at": "now()"
    }
    try:
        supabase.table("user_settings").upsert(payload).execute()
    except Exception:
        payload.pop("digest_opt_in", None)
        payload.pop("digest_top_n", None)
        payload.pop("setup_universes", None)
        payload.pop("setup_patterns", None)
        try:
            supabase.table("user_settings").upsert(payload).execute()
        except Exception as e:
            st.error(f"Failed to save settings: {e}")

def _current_user_id():
    user = st.session_state.get("user")
    if not user:
        return None
    return user.get("id") if isinstance(user, dict) else getattr(user, "id", None)

def save_scan_history(results_df: pd.DataFrame):
    supabase = get_supabase_client()
    user_id = _current_user_id()
    if not supabase or not user_id or results_df is None or results_df.empty:
        return
    session = st.session_state.get("supabase_session")
    if session and hasattr(session, "access_token"):
        supabase.postgrest.auth(session.access_token)
    now_iso = pd.Timestamp.now(tz="UTC").isoformat()
    rows = []
    for _, r in results_df.iterrows():
        rows.append({
            "user_id": user_id,
            "ticker": r["Ticker"],
            "scan_time": now_iso,
            "total_score": float(r["Total Score"]),
            "fundamental_score": float(r["Fundamental Score"]),
            "technical_score": float(r["Technical Score"]),
            "rs_score": 0.0,
            "sector": r.get("Sector"),
        })
    try:
        chunk_size = 200
        for i in range(0, len(rows), chunk_size):
            supabase.table("scan_history").insert(rows[i:i + chunk_size]).execute()
    except Exception:
        pass

@st.cache_data(ttl=300, show_spinner=False)
def _load_scan_history_cached(user_id: str, ticker: str, _supabase_url: str) -> pd.DataFrame:
    supabase = get_supabase_client()
    if not supabase or not user_id:
        return pd.DataFrame()
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        res = (
            supabase.table("scan_history")
            .select("scan_time,total_score,fundamental_score,technical_score,rs_score")
            .eq("user_id", user_id)
            .eq("ticker", ticker)
            .order("scan_time", desc=False)
            .execute()
        )
        if res.data:
            df = pd.DataFrame(res.data)
            df["scan_time"] = pd.to_datetime(df["scan_time"])
            return df
    except Exception:
        pass
    return pd.DataFrame()

def load_scan_history(user_id: str, ticker: str) -> pd.DataFrame:
    supabase = get_supabase_client()
    url_key = _cfg("SUPABASE_URL") if supabase else ""
    return _load_scan_history_cached(user_id, ticker, url_key)

def get_watchlist() -> list:
    supabase = get_supabase_client()
    user_id = _current_user_id()
    if not supabase or not user_id:
        return []
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        res = supabase.table("watchlist").select("ticker").eq("user_id", user_id).execute()
        return [r["ticker"] for r in (res.data or [])]
    except Exception:
        return []

def add_to_watchlist(ticker: str) -> bool:
    supabase = get_supabase_client()
    user_id = _current_user_id()
    if not supabase or not user_id:
        return False
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        supabase.table("watchlist").upsert({"user_id": user_id, "ticker": ticker}).execute()
        return True
    except Exception:
        return False

def remove_from_watchlist(ticker: str) -> bool:
    supabase = get_supabase_client()
    user_id = _current_user_id()
    if not supabase or not user_id:
        return False
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        supabase.table("watchlist").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
        return True
    except Exception:
        return False

AUTH_COOKIE = "funtech_sid"
AUTH_DIR = Path(__file__).resolve().parent / "data" / "auth_sessions"
STAY_SIGNED_IN_SECONDS = 30 * 24 * 60 * 60

def _valid_auth_sid(sid: str) -> bool:
    try:
        uuid.UUID(str(sid))
        return True
    except Exception:
        return False

def _auth_cookie_secure_flag() -> str:
    try:
        url = str(getattr(st.context, "url", "") or "")
        if url.startswith("https"):
            return "; Secure"
    except Exception:
        pass
    return ""

def _flush_auth_cookie_js() -> None:
    pending = st.session_state.pop("_auth_cookie", None)
    if pending is None:
        return
    sid = str(pending.get("sid") or "")
    max_age = int(pending.get("max_age") or 0)
    secure = _auth_cookie_secure_flag()
    if max_age <= 0 or not sid:
        script = (
            f"window.parent.document.cookie = '{AUTH_COOKIE}=; path=/; max-age=0; SameSite=Lax{secure}';"
        )
    else:
        script = (
            f"window.parent.document.cookie = '{AUTH_COOKIE}={sid}; path=/; max-age={max_age}; SameSite=Lax{secure}';"
        )
    st.components.v1.html(f"<script>{script}</script>", height=0)

def _read_auth_sid() -> str:
    try:
        sid = str(st.context.cookies.get(AUTH_COOKIE) or "").strip()
    except Exception:
        return ""
    return sid if _valid_auth_sid(sid) else ""

def _write_stay_session(payload: dict) -> str:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    sid = str(uuid.uuid4())
    (AUTH_DIR / f"{sid}.json").write_text(json.dumps(payload), encoding="utf-8")
    st.session_state["_auth_cookie"] = {"sid": sid, "max_age": STAY_SIGNED_IN_SECONDS}
    return sid

def _clear_stay_session() -> None:
    sid = _read_auth_sid()
    if sid:
        path = AUTH_DIR / f"{sid}.json"
        try:
            path.unlink()
        except Exception:
            pass
    st.session_state["_auth_cookie"] = {"sid": "", "max_age": 0}

def _session_tokens(session) -> tuple[str, str]:
    if session is None:
        return "", ""
    if isinstance(session, dict):
        return str(session.get("access_token") or ""), str(session.get("refresh_token") or "")
    return str(getattr(session, "access_token", "") or ""), str(getattr(session, "refresh_token", "") or "")

def _persist_login_if_requested(user, session) -> None:
    if not st.session_state.get("stay_signed_in", True):
        _clear_stay_session()
        return
    access, refresh = _session_tokens(session)
    if isinstance(user, dict):
        uid, email = user.get("id"), user.get("email")
    else:
        uid, email = getattr(user, "id", None), getattr(user, "email", None)
    if access and refresh:
        _write_stay_session({"mode": "supabase", "access_token": access, "refresh_token": refresh, "email": email, "id": uid})
        return
    _write_stay_session({"mode": "bypass", "email": email, "id": uid or "local-dev-id"})

def _try_restore_stay_signed_in() -> None:
    if st.session_state.get("user"):
        return
    sid = _read_auth_sid()
    if not sid:
        return
    path = AUTH_DIR / f"{sid}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if data.get("mode") == "bypass":
        st.session_state["user"] = {
            "id": data.get("id") or "local-dev-id",
            "email": data.get("email") or "vkiyer@hotmail.com",
        }
        st.session_state["supabase_session"] = None
        return
    access, refresh = data.get("access_token") or "", data.get("refresh_token") or ""
    supabase = get_supabase_client()
    if not supabase or not access or not refresh:
        return
    try:
        supabase.auth.set_session(access, refresh)
        got = supabase.auth.get_user()
        user = getattr(got, "user", None) or got
        session = supabase.auth.get_session()
        st.session_state["user"] = user
        st.session_state["supabase_session"] = session
        uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
        if uid:
            load_user_settings_from_db(uid)
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass

def init_auth_session():
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "supabase_session" not in st.session_state:
        st.session_state["supabase_session"] = None
    if "stay_signed_in" not in st.session_state:
        st.session_state["stay_signed_in"] = True
    init_session_defaults()

def render_login_screen():
    init_auth_session()
    supabase = get_supabase_client()
    st.title("🔐 NSE Stock Screener")
    st.caption("Please log in to access the Quantitative Analysis Engine.")
    st.divider()
    if not SUPABASE_AVAILABLE or supabase is None:
        st.warning("⚠️ **Supabase configuration not detected.**")
        st.info("Configure `SUPABASE_URL` and `SUPABASE_KEY` in `.streamlit/secrets.toml` to enable auth & persistence.")
        
        st.checkbox(
            "Stay signed in",
            key="stay_signed_in",
            help="Keep this browser signed in for about 30 days, or until you log out. Uncheck to require login again after you close the tab.",
        )
        if st.button(
            "Bypass Login (Developer / Local Mode)",
            use_container_width=True,
            help="Open the screener without Supabase. Settings stay on this device only and are not saved to the cloud.",
        ):
            st.session_state["user"] = {"id": "local-dev-id", "email": "vkiyer@hotmail.com"}
            st.session_state["supabase_session"] = None
            _persist_login_if_requested(st.session_state["user"], None)
            st.rerun()
        return False
        
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Account Access")
        auth_mode = st.radio(
            "Choose Mode",
            ["Login", "Sign Up", "Reset Password"],
            key="auth_mode",
            help="Login uses an existing account. Sign Up creates one. Reset Password sends a recovery email.",
        )
        email = st.text_input(
            "Email",
            key="auth_email",
            help="The address used for this account and, if you opt in, the daily top-scores email.",
        )
        
        if auth_mode != "Reset Password":
            password = st.text_input(
                "Password",
                type="password",
                key="auth_pass",
                help="Supabase account password. This app never emails your password.",
            )
            st.checkbox(
                "Stay signed in",
                key="stay_signed_in",
                help="Keep this browser signed in for about 30 days, or until you log out.",
            )
            
        if auth_mode == "Login":
            if st.button(
                "Log In",
                use_container_width=True,
                type="primary",
                help="Sign in and load your saved weights, rules, and top-scores email preference.",
            ):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state["user"] = res.user
                    st.session_state["supabase_session"] = res.session
                    
                    user_id = getattr(res.user, "id", None)
                    if user_id:
                        load_user_settings_from_db(user_id)
                    _persist_login_if_requested(res.user, res.session)
                    st.success("Login successful!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")
                    
        elif auth_mode == "Sign Up":
            if st.button(
                "Create Account",
                use_container_width=True,
                type="primary",
                help="Register this email. If confirmation is enabled in Supabase, check your inbox before logging in.",
            ):
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    if res.user and res.session:
                        st.session_state["user"] = res.user
                        st.session_state["supabase_session"] = res.session
                        _persist_login_if_requested(res.user, res.session)
                    st.success("Account created! Check your email or log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")
                    
        elif auth_mode == "Reset Password":
            if "reset_email_sent" not in st.session_state:
                st.session_state["reset_email_sent"] = False

            if not st.session_state["reset_email_sent"]:
                if st.button(
                    "Send Reset Code",
                    use_container_width=True,
                    type="primary",
                    help="Send a 6-digit password recovery code to your registered email address.",
                ):
                    if not email:
                        st.warning("Please enter your email address first.")
                    else:
                        try:
                            supabase.auth.reset_password_for_email(email)
                            st.session_state["reset_email_sent"] = True
                            st.session_state["reset_email"] = email
                            st.success("Reset code sent! Please check your inbox.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to send reset email: {e}")
            else:
                st.info(f"Enter the 6-digit code sent to **{st.session_state.get('reset_email')}**")
                otp_code = st.text_input("6-Digit Reset Code", key="reset_otp")
                new_password = st.text_input("New Password", type="password", key="reset_new_pass")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("Update Password", use_container_width=True, type="primary"):
                        if not otp_code or not new_password:
                            st.warning("Please enter both the 6-digit code and your new password.")
                        else:
                            try:
                                supabase.auth.verify_otp({
                                    "email": st.session_state["reset_email"], 
                                    "token": otp_code, 
                                    "type": "recovery"
                                })
                                supabase.auth.update_user({"password": new_password})
                                
                                st.success("Password updated successfully! You can now log in.")
                                st.session_state["reset_email_sent"] = False
                                supabase.auth.sign_out()
                            except Exception as e:
                                st.error(f"Error resetting password: {e}")
                with col_btn2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state["reset_email_sent"] = False
                        st.rerun()

    with col2:
        st.markdown(
            """
            ### 🏛️ What's Inside:
            * **CANSLIM fundamental engine:** earnings, sales, highs, demand, leadership vs Nifty/sector, institutions, market.
            * **10-point technical system:** multi-timeframe trend and momentum.
            * **Multi-broker portfolio evaluator:** auto-parse holdings.
            * **1-click TradingView exporter:** instant watchlist strings.
            """
        )
    return False

# ----------------------------------------------------------------------------------
# Dialog Modals
# ----------------------------------------------------------------------------------
@st.dialog("⚙️ Customize Fundamental Parameters")
def customize_fundamental_modal():
    st.write("Select CANSLIM criteria to include:")
    for k, label in DEFAULT_FUND_PARAMS.items():
        st.session_state[f"fund_{k}"] = st.checkbox(
            label, value=st.session_state.get(f"fund_{k}", True), help=FUND_HELP.get(k, "")
        )
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_fund", help="Turn every fundamental rule back on and save."):
        for k in DEFAULT_FUND_PARAMS:
            st.session_state[f"fund_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="apply_fund", help="Store these toggles for scans and the daily top-scores email."):
        save_user_settings_to_db()
        st.rerun()

@st.dialog("⚙️ Customize Technical Parameters")
def customize_technical_modal():
    st.write("Select rules to include in Technical Score:")
    for k, label in DEFAULT_TECH_PARAMS.items():
        st.session_state[f"tech_{k}"] = st.checkbox(
            label, value=st.session_state.get(f"tech_{k}", True), help=TECH_HELP.get(k, "")
        )
    
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="reset_tech", help="Turn every technical rule back on and save."):
        for k in DEFAULT_TECH_PARAMS:
            st.session_state[f"tech_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="apply_tech", help="Store these toggles for scans and the daily top-scores email."):
        save_user_settings_to_db()
        st.rerun()

@st.dialog("🔍 Pillar Breakdown Details", width="large")
def show_pillar_details_modal(row_data):
    ticker = row_data['Ticker']
    st.subheader(f"Symbol: {ticker.replace('.NS', '')}")
    st.caption(f"Sector: {row_data['Sector']} | Overall Score: {row_data['Total Score']:.2f} / 10")
    
    tab_f, tab_t = st.tabs([
        "🏛️ Fundamental (CANSLIM)",
        "📈 Technical Momentum",
    ])
    
    with tab_f:
        st.markdown(f"**Fundamental Score:** `{row_data['Fundamental Score']:.2f} / 10`")
        raw_fund = row_data.get("raw_fund", {})
        fund_items = []
        for k, label in DEFAULT_FUND_PARAMS.items():
            val = raw_fund.get(k, False)
            if val is None:
                status = "⏭ Skip"
            elif val:
                status = "✅ Pass"
            else:
                status = "❌ Fail"
            active = "Active" if st.session_state.get(f"fund_{k}", True) else "Disabled"
            fund_items.append({"Code": k, "Rule": label, "Status": status, "Rule State": active})
        st.dataframe(pd.DataFrame(fund_items), use_container_width=True, hide_index=True)
        l_diff = raw_fund.get("L_diff")
        ls_diff = raw_fund.get("Ls_diff")
        c_l1, c_l2 = st.columns(2)
        c_l1.metric("63-day return vs Nifty 50", f"{l_diff:+.1f}%" if l_diff is not None else "N/A")
        c_l2.metric("63-day return vs sector peers", f"{ls_diff:+.1f}%" if ls_diff is not None else "N/A")
    with tab_t:
        st.markdown(f"**Technical Score:** `{row_data['Technical Score']:.2f} / 10` (Passed: {row_data['Tech Passed']})")
        raw_tech = row_data.get("raw_tech", {})
        tech_items = []
        for k, label in DEFAULT_TECH_PARAMS.items():
            status = "✅ Pass" if raw_tech.get(k, False) else "❌ Fail"
            active = "Active" if st.session_state.get(f"tech_{k}", True) else "Disabled"
            tech_items.append({"Code": k, "Rule": label, "Status": status, "Rule State": active})
        st.dataframe(pd.DataFrame(tech_items), use_container_width=True, hide_index=True)
    
    st.divider()
    if st.button("❌ Close Breakdown", use_container_width=True, type="primary"):
        st.rerun()

@st.dialog("📚 Setup Logic Documentation")
def show_setup_documentation_modal():
    st.markdown("""
    ### Setup Engine Rules Breakdown
    
    **1. Multi-Timeframe Pullback (DW & WM)**
    - **Daily/Weekly (DW):** Daily Stochastic (K) crosses above D below 60 within the last 3 days, backed by a Weekly MACD line sloping upwards.
    - **Weekly/Monthly (WM):** Weekly Stochastic (K) crosses above D below 60 within the last 2 weeks, backed by a Monthly MACD line sloping upwards.
    
    **2. Breakout Retest**
    Price broke its 40-day high within the last 5 days on above-average volume, and is now resting quietly within 3% of that breakout line on lower volume. Identifies low-risk entries on prior resistance turning into support.
    
    **3. RSI Momentum Resumption**
    RSI recently peaked > 60, cooled off below 55 naturally, and is now actively curling back up through 55 alongside confirming higher price action. 
    
    **4. Volatility Squeeze**
    Stock is forming two consecutive 'Inside Days' (tighter high/low ranges) on extremely low volume (drying up float), signaling a potential explosive breakout is imminent.
    
    **5. 20-EMA Trend Bounce**
    Stock is in a strong uptrend (20 EMA > 50 SMA), dips to touch the 20 EMA, and closes strongly in the upper half of its daily range showing institutional support.
    
    **6. Bottom Fisher (Macro MACD Regime)**
    Detects macro trend reversals purely on the Monthly timeframe:
    - **Phase 1 (The Bleed):** The Monthly MACD line must have remained below its Signal line for at least 6 full months leading up to the bottom (capturing a true Stage 4 downtrend regime).
    - **Phase 2 (The Curl):** The setup triggers during the months where the MACD is continuously sloping upward from the bottom, **up until the month it crosses its signal line**.
    - *Note:* This is inherently a high-risk setup since it attempts to catch a falling knife before daily confirmation. It is highly recommended to wait for another technical setup (like a 20-EMA Bounce or Pocket Pivot) to trigger simultaneously before entry.
    
    **7. Pocket Pivot (Base Accumulation)**
    Identifies institutional buying inside a constructive base before a traditional resistance breakout occurs:
    - **Context:** The stock is trading above its 200-DMA, and its 50-DMA is flattening or sloping upward.
    - **Support Interaction:** The low of the day must drop within $1.5\\%$ of either the 10-EMA or the 50-SMA (a "kiss" of support) and close firmly in the upper $40\\%$ of its daily range.
    - **Volume Signature:** It must be an "Up" day (Close > Yesterday Close) with trading volume strictly higher than the largest "Down" day volume seen over the previous 10 trading sessions.
    """)

    if st.button("Close", use_container_width=True):
        st.rerun()

# ----------------------------------------------------------------------------------
# Calculation Engines
# ----------------------------------------------------------------------------------

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

def compute_rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0) 
    return rsi

def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    if len(series.dropna()) < signal + 2:
        return pd.DataFrame(columns=["MACD", "MACDh", "MACDs"])
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"MACD": macd_line, "MACDh": hist, "MACDs": signal_line})

def check_stocks_setting_up(df, enabled_setups=None):
    if df is None or len(df) < 150:
        return []
    if enabled_setups is None:
        enabled_setups = AVAILABLE_SETUPS
        
    try:
        stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=14, d=3, smooth_k=3)
        df['STOCH_K'] = stoch['STOCHk_14_3_3']
        df['STOCH_D'] = stoch['STOCHd_14_3_3']
        
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        df['EMA_10'] = ta.ema(df['Close'], length=10)
        df['EMA_20'] = ta.ema(df['Close'], length=20)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['Vol_20_SMA'] = ta.sma(df['Volume'], length=20)
    except:
        return []
        
    today = df.iloc[-1]
    yest = df.iloc[-2]
    tags = []
    
    weekly = resample_ohlc(df, "W")
    monthly = resample_ohlc(df, "ME")
    
    if not weekly.empty:
        weekly['RSI_W'] = compute_rsi(weekly['Close'], 14)

    # SETUP 1: Multi-Timeframe Pullback (DW & WM variants)
    if "Pullback (DW)" in enabled_setups:
        daily_cross_below_60 = False
        if len(df) >= 5:
            for i in range(1, 4):
                curr_k = df['STOCH_K'].iloc[-i]
                curr_d = df['STOCH_D'].iloc[-i]
                prev_k = df['STOCH_K'].iloc[-(i+1)]
                prev_d = df['STOCH_D'].iloc[-(i+1)]
                if (prev_k < prev_d) and (curr_k > curr_d) and (curr_k < 60) and (curr_d < 60):
                    daily_cross_below_60 = True
                    break
                
        weekly_macd_up = False
        if not weekly.empty and len(weekly) > 3:
            macd_w = compute_macd(weekly['Close'])
            if not macd_w.empty and len(macd_w) > 2:
                weekly_macd_up = macd_w['MACD'].iloc[-1] > macd_w['MACD'].iloc[-2]

        if daily_cross_below_60 and weekly_macd_up:
            tags.append("✔️ Pullback (DW)")

    # WM Logic (Weekly Stoch / Monthly MACD)
    if "Pullback (WM)" in enabled_setups:
        weekly_cross_below_60 = False
        if not weekly.empty and len(weekly) >= 20:
            try:
                stoch_w = ta.stoch(weekly['High'], weekly['Low'], weekly['Close'], k=14, d=3, smooth_k=3)
                weekly['STOCH_K'] = stoch_w['STOCHk_14_3_3']
                weekly['STOCH_D'] = stoch_w['STOCHd_14_3_3']
                for i in range(1, 3):
                    if i < len(weekly) - 1:
                        curr_k = weekly['STOCH_K'].iloc[-i]
                        curr_d = weekly['STOCH_D'].iloc[-i]
                        prev_k = weekly['STOCH_K'].iloc[-(i+1)]
                        prev_d = weekly['STOCH_D'].iloc[-(i+1)]
                        if pd.notna(curr_k) and pd.notna(prev_k):
                            if (prev_k < prev_d) and (curr_k > curr_d) and (curr_k < 60) and (curr_d < 60):
                                weekly_cross_below_60 = True
                                break
            except Exception:
                pass

        monthly_macd_up = False
        if not monthly.empty and len(monthly) > 3:
            macd_m = compute_macd(monthly['Close'])
            if not macd_m.empty and len(macd_m) > 2:
                monthly_macd_up = macd_m['MACD'].iloc[-1] > macd_m['MACD'].iloc[-2]

        if weekly_cross_below_60 and monthly_macd_up:
            tags.append("✔️ Pullback (WM)")

    # SETUP 2: Breakout Retest
    if "Breakout Retest" in enabled_setups:
        lookback = 40
        resistance = df['High'].iloc[-lookback-5:-5].max() 
        recent_breakout = df.iloc[-5:]['Close'].max() > resistance
        resting_near_res = (resistance * 0.97) <= today['Close'] <= (resistance * 1.03)
        quiet_volume = today['Volume'] < today['Vol_20_SMA']
        if recent_breakout and resting_near_res and quiet_volume:
            tags.append("✔️ Breakout Retest")

    # SETUP 3: RSI Momentum Resumption
    if "RSI Resumption" in enabled_setups:
        rsi_hit_high = df['RSI'].iloc[-20:-5].max() >= 60
        rsi_cooled = df['RSI'].iloc[-5:-1].min() < 55
        rsi_curling_up = yest['RSI'] < 55 and today['RSI'] >= 55
        price_confirming = today['Close'] > yest['Close']
        if rsi_hit_high and rsi_cooled and rsi_curling_up and price_confirming:
            tags.append("✔️ RSI Resumption")

    # SETUP 4: Volatility Squeeze
    if "Vol Squeeze" in enabled_setups:
        inside_day_1 = (yest['High'] < df.iloc[-3]['High']) and (yest['Low'] > df.iloc[-3]['Low'])
        inside_day_2 = (today['High'] < yest['High']) and (today['Low'] > yest['Low'])
        vol_dry_up = today['Volume'] < (today['Vol_20_SMA'] * 0.6)
        if inside_day_1 and inside_day_2 and vol_dry_up:
            tags.append("✔️ Vol Squeeze")

    # SETUP 5: 20-EMA Trend Bounce
    if "20-EMA Bounce" in enabled_setups:
        strong_trend = today['EMA_20'] > today['SMA_50']
        touched_ema = today['Low'] <= today['EMA_20'] and today['Close'] > today['EMA_20']
        daily_range = today['High'] - today['Low']
        closed_strong = today['Close'] > (today['Low'] + (daily_range * 0.5))
        if strong_trend and touched_ema and closed_strong:
            tags.append("✔️ 20-EMA Bounce")

    # SETUP 6: Bottom Fisher (Macro MACD Regime)
    if "Bottom Fisher" in enabled_setups:
        try:
            if not monthly.empty and len(monthly) >= 18:
                macd_m = compute_macd(monthly['Close'])
                if not macd_m.empty and len(macd_m) >= 18:
                    mac = macd_m['MACD'].tolist()
                    sig = macd_m['MACDs'].tolist()
                    M = list(reversed(mac)) # M[0] = current month, M[1] = 1 month ago
                    S = list(reversed(sig))
                    
                    is_valid_macro_bottom = False
                    
                    # Search up to 12 months back for the MACD bottom to catch prolonged curls
                    for B in range(2, 12):
                        # Ensure MACD has been consecutively rising since the bottom B
                        rising = True
                        for i in range(B):
                            if M[i] <= M[i+1]:
                                rising = False
                                break
                        if not rising:
                            continue
                            
                        # Verify B is a distinct bottom
                        if M[B] >= M[B+1]:
                            continue
                            
                        # Phase 1: Macro Damage (Negative Crossover >= 6 months before B)
                        # This implies MACD was strictly below the Signal line for at least 6 months leading up to B
                        if B + 5 < len(M):
                            valid_downtrend = True
                            for i in range(B, B+6):
                                if M[i] > S[i]:
                                    valid_downtrend = False
                                    break
                            
                            if valid_downtrend:
                                # Pre-Stage 2 check: MACD was below Signal last month.
                                # (This flags it continuously until the month after it finally crosses over)
                                if M[1] <= S[1]:
                                    is_valid_macro_bottom = True
                                    break
                                
                    if is_valid_macro_bottom:
                        tags.append("✔️ Bottom Fisher")
        except Exception:
            pass

    # SETUP 7: Pocket Pivot (Institutional Accumulation inside Base)
    if "Pocket Pivot" in enabled_setups:
        try:
            ema10 = df['EMA_10'].iloc[-1]
            sma50 = df['SMA_50'].iloc[-1]
            sma200 = df['SMA_200'].iloc[-1]
            
            # Trend Context: Above 200-DMA, 50-DMA flattening/sloping up
            if pd.notna(sma200) and today['Close'] > sma200:
                sma50_5d_ago = df['SMA_50'].iloc[-5]
                if pd.notna(sma50_5d_ago) and sma50 >= sma50_5d_ago:
                    
                    # Support Interaction: Low dips within 1.5% of 10-EMA or 50-SMA
                    low_dist_10 = abs(today['Low'] - ema10) / ema10 if pd.notna(ema10) else 99
                    low_dist_50 = abs(today['Low'] - sma50) / sma50 if pd.notna(sma50) else 99
                    
                    if min(low_dist_10, low_dist_50) <= 0.015:
                        daily_range = today['High'] - today['Low']
                        if daily_range > 0:
                            close_pct = (today['Close'] - today['Low']) / daily_range
                            if close_pct >= 0.60: # Close in upper 40% of range
                                
                                # Volume Signature: Up day, Vol > Max Down Vol in last 10 days
                                if today['Close'] > yest['Close']:
                                    down_vols = []
                                    # Look back exactly 10 sessions before today
                                    for i in range(-11, -1):
                                        if df['Close'].iloc[i] < df['Close'].iloc[i-1]:
                                            down_vols.append(df['Volume'].iloc[i])
                                            
                                    max_down_vol = max(down_vols) if down_vols else 0
                                    
                                    if today['Volume'] > max_down_vol:
                                        tags.append("✔️ Pocket Pivot")
        except Exception:
            pass

    return tags

def _yoy_latest_vs_year_ago(df: pd.DataFrame | None, needles: list[str]) -> float | None:
    if df is None or getattr(df, "empty", True) or getattr(df, "shape", (0, 0))[1] < 5:
        return None
    row = None
    for needle in needles:
        for idx in df.index:
            if needle in str(idx).lower():
                row = idx
                break
        if row is not None:
            break
    if row is None:
        return None
    cur, yoy = df.loc[row].iloc[0], df.loc[row].iloc[4]
    if yoy in (0, None) or pd.isna(yoy) or pd.isna(cur):
        return None
    try:
        return float((float(cur) - float(yoy)) / abs(float(yoy)))
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def canslim_c_growth(info: dict) -> float | None:
    for key in ("quarterly_eps_yoy", "quarterly_ni_yoy"):
        val = info.get(key)
        if val is not None and pd.notna(val):
            return float(val)
    return None

def canslim_a_growth(info: dict) -> float | None:
    val = info.get("quarterly_rev_yoy")
    if val is not None and pd.notna(val):
        return float(val)
    return None

def period_return_pct(close: pd.Series | None, lookback: int = 63) -> float | None:
    if close is None:
        return None
    s = close.dropna()
    if len(s) < 22:
        return None
    n = min(lookback, len(s) - 1)
    prev, last = s.iloc[-n], s.iloc[-1]
    if prev in (0, None) or pd.isna(prev) or pd.isna(last):
        return None
    try:
        return float(last / float(prev) - 1.0) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def fifty_two_week_high(info: dict, daily: pd.DataFrame | None) -> float | None:
    highs: list[float] = []
    y = info.get("fiftyTwoWeekHigh") if info else None
    if y is not None and pd.notna(y):
        try:
            yf = float(y)
            if yf > 0:
                highs.append(yf)
        except (TypeError, ValueError):
            pass
    if daily is not None and not daily.empty:
        col = daily["High"] if "High" in daily.columns else daily["Close"]
        window = col.tail(252).dropna()
        if not window.empty:
            highs.append(float(window.max()))
    return max(highs) if highs else None

def up_volume_exceeds_down(daily: pd.DataFrame | None, sessions: int = 20) -> bool | None:
    if daily is None or daily.empty or "Volume" not in daily.columns or "Close" not in daily.columns:
        return None
    if len(daily) < sessions + 1:
        return None
    d = daily.tail(sessions + 1)
    chg = d["Close"].diff().iloc[1:]
    vol = d["Volume"].iloc[1:]
    if vol.isna().all():
        return None
    up = float(vol.loc[chg > 0].sum())
    down = float(vol.loc[chg < 0].sum())
    if up == 0 and down == 0:
        return None
    return bool(up > down)

def _set_fund_rule(raw: dict, valid: dict, key: str, passed: bool | None) -> None:
    raw[key] = passed
    valid[key] = passed is not None

def slope_up(series: pd.Series, lookback: int = 5) -> bool:
    s = series.dropna()
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])

def is_rising(series: pd.Series, lookback: int = 2) -> bool:
    s = series.dropna()
    return len(s) >= lookback + 1 and bool(s.iloc[-1] > s.iloc[-(lookback + 1)])

def compute_fundamental_score(info: dict, daily: pd.DataFrame, bench_daily: pd.DataFrame, sector_avg_ret=None):
    raw_results = {}
    valid_metrics = {}
    info = info or {}
    eps_growth = canslim_c_growth(info)
    if eps_growth is not None and pd.notna(eps_growth):
        _set_fund_rule(raw_results, valid_metrics, "C", bool(eps_growth > 0.15))
    else:
        _set_fund_rule(raw_results, valid_metrics, "C", None)
    rev_growth = canslim_a_growth(info)
    if rev_growth is not None and pd.notna(rev_growth):
        _set_fund_rule(raw_results, valid_metrics, "A", bool(rev_growth > 0.10))
    else:
        _set_fund_rule(raw_results, valid_metrics, "A", None)

    fifty2_high = fifty_two_week_high(info, daily)
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price and daily is not None and not daily.empty:
        current_price = daily["Close"].iloc[-1]
    if fifty2_high and current_price and float(fifty2_high) > 0:
        _set_fund_rule(raw_results, valid_metrics, "N", bool(float(current_price) >= 0.90 * float(fifty2_high)))
    else:
        _set_fund_rule(raw_results, valid_metrics, "N", None)

    _set_fund_rule(raw_results, valid_metrics, "S", up_volume_exceeds_down(daily, 20))

    stock_ret = period_return_pct(daily["Close"] if daily is not None and not daily.empty else None, 63)
    bench_ret = period_return_pct(bench_daily["Close"] if bench_daily is not None and not bench_daily.empty else None, 63)
    if stock_ret is not None and bench_ret is not None:
        raw_results["L_diff"] = round(stock_ret - bench_ret, 2)
        _set_fund_rule(raw_results, valid_metrics, "L", bool(stock_ret > bench_ret))
    else:
        raw_results["L_diff"] = None
        _set_fund_rule(raw_results, valid_metrics, "L", None)

    sector_available = sector_avg_ret is not None and pd.notna(sector_avg_ret)
    if stock_ret is not None and sector_available:
        raw_results["Ls_diff"] = round(stock_ret - float(sector_avg_ret), 2)
        _set_fund_rule(raw_results, valid_metrics, "Ls", bool(stock_ret > float(sector_avg_ret)))
    else:
        raw_results["Ls_diff"] = None
        _set_fund_rule(raw_results, valid_metrics, "Ls", None)

    inst_hold = info.get("heldPercentInstitutions")
    if inst_hold is not None and pd.notna(inst_hold):
        _set_fund_rule(raw_results, valid_metrics, "I", bool(inst_hold > 0.30))
    else:
        _set_fund_rule(raw_results, valid_metrics, "I", None)

    if bench_daily is not None and len(bench_daily) >= 200:
        bench_close = bench_daily["Close"]
        bench_sma200 = bench_close.rolling(200).mean().iloc[-1]
        if pd.notna(bench_sma200):
            _set_fund_rule(raw_results, valid_metrics, "M", bool(bench_close.iloc[-1] > bench_sma200))
        else:
            _set_fund_rule(raw_results, valid_metrics, "M", None)
    else:
        _set_fund_rule(raw_results, valid_metrics, "M", None)

    active_passed = 0
    active_total = 0
    passed_labels = []
    for k in DEFAULT_FUND_PARAMS:
        if _ss_get(f"fund_{k}", True):
            if valid_metrics.get(k, False):
                active_total += 1
                if raw_results.get(k) is True:
                    active_passed += 1
                    passed_labels.append(k)
    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    if active_total == 0:
        status_str = "No Data Available"
    else:
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
    d["RSI14"] = compute_rsi(close, 14)
    last_close = close.iloc[-1]
    sma20 = d["SMA20"].iloc[-1]
    sma50 = d["SMA50"].iloc[-1]
    sma200 = d["SMA200"].iloc[-1]
    rsi_daily = d["RSI14"].iloc[-1] if not d["RSI14"].empty else np.nan
    weekly = resample_ohlc(daily, "W")
    monthly = resample_ohlc(daily, "ME")
    rsi_weekly = compute_rsi(weekly["Close"], 14) if not weekly.empty else None
    rsi_monthly = compute_rsi(monthly["Close"], 14) if not monthly.empty else None
    macd_w = compute_macd(weekly["Close"]) if not weekly.empty and len(weekly) > 3 else None
    macd_m = compute_macd(monthly["Close"]) if not monthly.empty and len(monthly) > 3 else None
    macd_d = compute_macd(close) if len(close) > 3 else None
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
        if _ss_get(f"tech_{k}", True):
            active_total += 1
            if raw.get(k, False):
                active_passed += 1
    norm_score = (active_passed / active_total * 10) if active_total > 0 else 0.0
    status_str = f"{active_passed}/{active_total}"
    return round(norm_score, 2), status_str, raw

def fetch_single_stock(tkr: str):
    daily = fetch_daily(tkr)
    info = fetch_info(tkr) if daily is not None else {}
    return tkr, daily, info

def execute_scan(ticker_list, w_fund, w_tech, w_rs=None, show_progress=True):
    from digest import clamp_pillar_weights, weighted_total
    w_fund, w_tech = clamp_pillar_weights(w_fund, w_tech, w_rs)
    bench_daily = fetch_daily(BENCHMARK)
    stock_data = {}
    sector_returns = {}
    progress = None
    
    if _in_streamlit() and show_progress:
        progress = st.progress(0, text="Fetching stock data...")
        
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_stock, tkr): tkr for tkr in ticker_list}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if progress:
                progress.progress(completed / len(ticker_list), text=f"Scanning {completed} of {len(ticker_list)} tickers")
            elif show_progress:
                print(f"Digest scan {completed}/{len(ticker_list)}", flush=True)
            tkr, daily, info = future.result()
            if daily is not None:
                stock_data[tkr] = {"daily": daily, "info": info}
                if len(daily) >= 63:
                    ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-63] - 1) * 100
                    sec = info.get("sector", "Unknown")
                    if sec and sec != "Unknown":
                        sector_returns.setdefault(sec, []).append(ret)
    if progress:
        progress.empty()
    if _in_streamlit():
        st.session_state["scan_raw_daily"] = {tkr: v["daily"] for tkr, v in stock_data.items()}
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
        fund_score, fund_status, raw_fund = compute_fundamental_score(info, daily, bench_daily, sec_ret)
        tech_score, tech_status, raw_tech = compute_technical_score(daily)
        total_score = weighted_total(fund_score, tech_score, w_fund, w_tech)
        results.append({
            "Ticker": tkr,
            "Total Score": round(total_score, 2),
            "Fundamental Score": fund_score,
            "Technical Score": tech_score,
            "Tech Passed": tech_status,
            "CANSLIM Hits": fund_status,
            "Sector": sec_abbrev,
            "raw_fund": raw_fund,
            "raw_tech": raw_tech,
        })
    return pd.DataFrame(results), skipped

# ----------------------------------------------------------------------------------
# Main UI App Loop
# ----------------------------------------------------------------------------------

def _run_streamlit_ui():
    _apply_page_chrome()
    _flush_auth_cookie_js()
    init_auth_session()
    _try_restore_stay_signed_in()
    
    if "user" not in st.session_state or st.session_state["user"] is None:
        render_login_screen()
        st.stop()
        
    init_session_defaults()
    
    # Ensure weights are ints and sum to 10 safely
    _wf0 = int(st.session_state.get("w_fund", 5))
    _wt0 = int(st.session_state.get("w_tech", 5))
    if _wf0 + _wt0 != 10:
        try:
            from digest import clamp_pillar_weights as _clamp_w
            _wf0, _wt0 = _clamp_w(_wf0, _wt0)
        except Exception:
            _wf0, _wt0 = 5, 5
        st.session_state["w_fund"] = _wf0
        st.session_state["w_tech"] = _wt0
        
    current_user = st.session_state["user"]
    user_email = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", "User")
    _uid = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
    
    if _uid and "digest_pref_hydrated" not in st.session_state:
        from digest import load_pref_for_user
        stored = load_pref_for_user(str(_uid))
        if stored:
            st.session_state["digest_opt_in"] = bool(stored.get("opt_in", False))
            st.session_state["digest_top_n"] = int(stored.get("top_n") or 10)
        st.session_state["digest_pref_hydrated"] = True
    
    user_is_admin = is_admin(current_user)
    user_is_authorized_or_admin = is_authorized_or_admin(current_user)

    head_l, head_r = st.columns([3, 2])
    with head_l:
        st.title("📊 NSE Stock Screener & Portfolio Evaluator")
        st.caption("Two-pillar engine (CANSLIM fundamentals + technicals) for NSE traders and investors.")
    with head_r:
        st.markdown(
            f"<div style='text-align:right;padding-top:0.6rem'>"
            f"<strong>{user_email}</strong><br>"
            f"<span style='color:#666;font-size:0.9rem'>"
            f"{'Administrator' if user_is_admin else 'Authorized User' if user_is_authorized_or_admin else 'Signed in'}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
        if st.button("Log Out", use_container_width=True):
            _clear_stay_session()
            supabase = get_supabase_client()
            if supabase:
                try: supabase.auth.sign_out()
                except Exception: pass
            _flush_auth_cookie_js()
            st.session_state.clear()
            st.rerun()

    def _snapshot_engine():
        w_f = int(st.session_state.get("w_fund", 5))
        w_t = int(st.session_state.get("w_tech", 5))
        return {
            "w_fund": w_f,
            "w_tech": w_t,
            "fund_rules": {k: bool(st.session_state.get(f"fund_{k}", True)) for k in DEFAULT_FUND_PARAMS},
            "tech_rules": {k: bool(st.session_state.get(f"tech_{k}", True)) for k in DEFAULT_TECH_PARAMS},
        }

    def _persist_digest_pref():
        save_user_settings_to_db()
        from digest import save_pref
        _user = st.session_state.get("user") or {}
        _email = _user.get("email") if isinstance(_user, dict) else getattr(_user, "email", "")
        _id = _user.get("id") if isinstance(_user, dict) else getattr(_user, "id", "")
        save_pref(
            str(_id or ""), str(_email or ""),
            bool(st.session_state.get("digest_opt_in")),
            int(st.session_state.get("digest_top_n") or 10),
            settings=_snapshot_engine(),
        )

    def _on_digest_pref_change():
        _persist_digest_pref()

    w_fund = int(st.session_state.get("w_fund", 5))
    w_tech = int(st.session_state.get("w_tech", 5))

    tab_list = ["🔍 Stock Screener", "💼 Portfolio Evaluator"]
    if user_is_authorized_or_admin:
        tab_list.append("📈 Stocks Setting Up")
    tab_list.extend(["🎛️ User-defined controls", "ℹ️ User Guide"])
    if user_is_admin:
        tab_list.append("🛠️ Admin Panel")
        
    if "active_main_tab" not in st.session_state:
        st.session_state["active_main_tab"] = "🔍 Stock Screener"

    selected_tab = st.radio(
        "Navigation", 
        tab_list, 
        horizontal=True, 
        label_visibility="collapsed", 
        key="active_main_tab"
    )
    st.divider()

    # ==================================================================================
    # TAB 1: STOCK SCREENER
    # ==================================================================================
    if selected_tab == "🔍 Stock Screener":
        st.subheader("Screener universe")
        
        universe_sources = st.multiselect(
            "Universe Source",
            options=UNIVERSE_SOURCE_OPTIONS,
            default=["Nifty 500"],
            key="scr_universe_source",
            help="Select one or more NSE indices or F&O lists to load."
        )
        
        base_list = []
        if universe_sources:
            with st.status("Loading universes...", expanded=False) as _status:
                for univ in universe_sources:
                    if univ == "F&O Stocks":
                        base_list.extend(load_fo_stocks())
                    else:
                        base_list.extend(load_index_list(univ))
                base_list = list(dict.fromkeys(base_list))
                _status.update(label=f"Loaded {len(base_list)} tickers from selected universes", state="complete")
        
        _tracker = _get_freshness_tracker()
        _freshness_lines = []
        for univ in universe_sources:
            _univ_info = _tracker.get(f"universe:{univ}")
            if _univ_info:
                _ts, _kind = _univ_info
                _age_min = (pd.Timestamp.now() - _ts).total_seconds() / 60
                _icon = "✅" if _kind == "live" else "⚠️"
                _freshness_lines.append(f"{_icon} {univ}: {_kind}, {_age_min:.0f} min ago")
            else:
                _freshness_lines.append(f"ℹ️ {univ}: served from cache this session")

        _price_ts = _tracker.get("prices")
        if _price_ts:
            _age_min = (pd.Timestamp.now() - _price_ts).total_seconds() / 60
            _freshness_lines.append(f"✅ Price data: last fetched {_age_min:.0f} min ago")
        
        _last_scan = st.session_state.get("last_scan_time")
        if _last_scan:
            _age_min = (pd.Timestamp.now() - _last_scan).total_seconds() / 60
            _freshness_lines.append(f"🕒 Last scan run: {_age_min:.0f} min ago")
            
        if _freshness_lines:
            st.caption("  \n".join(_freshness_lines))
            
        with st.expander("📤 Upload Custom CSV/Excel List", expanded=False):
            uploaded_csv = st.file_uploader(
                "Upload Universe File",
                type=["csv", "xlsx", "xls"],
                key="scr_csv",
                label_visibility="collapsed",
                help="Broker or custom list. The parser looks for a symbol column (Zerodha, Groww, Dhan, Upstox, and similar exports).",
            )
        csv_tickers = []
        if uploaded_csv is not None:
            try:
                if uploaded_csv.name.lower().endswith((".xlsx", ".xls")):
                    csv_df = pd.read_excel(uploaded_csv)
                else:
                    csv_df = pd.read_csv(uploaded_csv)
                csv_tickers = parse_broker_symbols(csv_df)
                if csv_tickers:
                    st.success(f"Loaded {len(csv_tickers)} tickers from file.")
                else:
                    st.error("Could not detect a symbol column in the uploaded file.")
            except Exception as e:
                st.error(f"Error parsing universe file: {e}")
                
        full_options = list(dict.fromkeys(base_list + csv_tickers))
        if csv_tickers:
            default_selection = csv_tickers
            universe_state_tag = f"csv:{len(csv_tickers)}"
        else:
            default_selection = base_list
            universe_state_tag = "idx"
            
        univ_key_str = "_".join(universe_sources) if universe_sources else "none"
        
        selected_universe = st.multiselect(
            "Active Tickers",
            options=full_options,
            default=default_selection,
            key=f"scr_active_tickers::{univ_key_str}::{universe_state_tag}",
            help="Tickers that will be scored. Deselect names to skip them. Switching indices or uploading a file resets this list.",
        )
        
        custom_raw = st.text_input(
            "Add Custom Tickers",
            value="",
            help="Extra NSE symbols, comma-separated (e.g. TRENT, HDFCBANK). .NS is added if you omit it.",
        )
        
        # --- NEW AGGRESSIVE PARSER FOR SCREENER TAB ---
        temp_str_main = custom_raw.replace("\n", ",").replace(" ", ",").replace(";", ",").replace("\t", ",")
        raw_list_main = [s.strip().upper() for s in temp_str_main.split(",") if s.strip()]
        custom_tickers = []
        for sym in raw_list_main:
            clean = sym.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-BE", "").strip()
            if clean:
                custom_tickers.append(f"{clean}.NS" if not clean.endswith(".NS") else clean)
        # ----------------------------------------------
        
        watchlist_tickers = []
        universe = list(dict.fromkeys(selected_universe + custom_tickers + watchlist_tickers))
        
        if len(universe) > 150:
            st.warning(f"{len(universe)} tickers selected — a full scan will take a while.")
            
        force_refresh = st.checkbox(
            "Force fresh price data (ignore 30-min cache)",
            value=False,
            help="Normally price data is cached for 30 minutes so repeated scans are fast. "
                 "Check this to bypass that and re-fetch from yfinance — useful right after "
                 "market close, or if you suspect stale data. This does NOT re-fetch the "
                 "universe list (Nifty 500 etc.) — that's cached separately for 24h.",
        )
        run_scan = st.button(
            "🔍 Run Screener Scan",
            type="primary",
            use_container_width=True,
            help="Score every ticker in Active Tickers plus any custom symbols, using the weights and rules on User-defined controls. Large lists take several minutes.",
        )
        
        if run_scan:
            if not universe:
                st.warning("Select at least one ticker.")
            else:
                if force_refresh:
                    fetch_daily.clear()
                    fetch_info.clear()
                with st.spinner("Running quantitative scan..."):
                    results_df, skipped = execute_scan(universe, w_fund, w_tech)
                    st.session_state["results_df"] = results_df
                    st.session_state["skipped_tickers"] = skipped
                    st.session_state["last_scan_time"] = pd.Timestamp.now()
                    if SUPABASE_AVAILABLE and not results_df.empty:
                        save_scan_history(results_df)
                        
        if "results_df" in st.session_state:
            df = st.session_state["results_df"]
            skipped = st.session_state.get("skipped_tickers", [])
            if not df.empty:
                df = df.sort_values("Total Score", ascending=False).reset_index(drop=True)
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Screened Tickers",
                    len(df),
                    help="How many names returned a score. Skipped tickers (no price data) are listed separately if any failed.",
                )
                c2.metric(
                    "Highest Total Score",
                    f"{df['Total Score'].max():.2f}",
                    help="Best Total in this scan under your current weights. Pillar scores themselves stay 0–10.",
                )
                c3.metric(
                    "Average Score",
                    f"{df['Total Score'].mean():.2f}",
                    help="Mean Total across the screened set. Use it to see how demanding your weights and rules are.",
                )
                st.divider()
                st.subheader("📈 TradingView 1-Click Clipboard Exporter")
                col_tv1, col_tv2 = st.columns([1, 2])
            
                with col_tv1:
                    threshold = st.slider(
                        "Min Score Filter",
                        0.0,
                        10.0,
                        6.0,
                        0.5,
                        key="scr_tv_thresh",
                        help="Only names with Total at or above this value are listed for the TradingView paste. Does not change the table below.",
                    )
            
                filtered_df = df[df["Total Score"] >= threshold]
                tv_symbols = [f"NSE:{s.replace('.NS', '')}" for s in filtered_df["Ticker"].tolist()]
                tv_content = ",".join(tv_symbols)
                with col_tv2:
                    st.write(f"**{len(tv_symbols)} matching tickers** (score ≥ {threshold:.1f}). Copy below ➡️")
                    if tv_symbols:
                        st.code(tv_content, language="text")
                    else:
                        st.info("No tickers match this score threshold.")
                st.divider()
                st.subheader("📋 Screening Results Table")
                st.info("💡 Select a holding below or choose a symbol to inspect its detailed pillar breakdown.")
                display_table = df[[
                    "Ticker", "Total Score", "Fundamental Score",
                    "Technical Score", "Tech Passed", "CANSLIM Hits", "Sector"
                ]].copy()
                c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])
                with c_ctrl1:
                    selected_ticker = st.selectbox(
                        "Select Stock to Inspect:",
                        options=df["Ticker"].tolist(),
                        key="scr_select_tkr",
                        help="Choose a row to open the pass/fail breakdown for each fundamental and technical rule.",
                    )
                with c_ctrl2:
                    st.write(f"Selected: **{selected_ticker}**")
                with c_ctrl3:
                    if st.button(
                        "🔍 Breakdown",
                        key="scr_view_btn",
                        use_container_width=True,
                        type="primary",
                        help="Show why this ticker received its fundamental and technical scores.",
                    ):
                        sel_ticker = st.session_state.get("scr_select_tkr")
                        match = df[df["Ticker"] == sel_ticker]
                        if not match.empty:
                            show_pillar_details_modal(match.iloc[0].to_dict())
                        else:
                            st.toast(f"No result data found for {sel_ticker}.")
                st.dataframe(
                    display_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                        "Total Score": st.column_config.NumberColumn(
                            "Total", format="%.2f", help="Weighted blend of Fund and Tech. The two weights always add to 10."
                        ),
                        "Fundamental Score": st.column_config.NumberColumn(
                            "Fund", format="%.2f", help="0–10 from enabled CANSLIM rules that this ticker passed (L/Ls are vs Nifty and sector)."
                        ),
                        "Technical Score": st.column_config.NumberColumn(
                            "Tech", format="%.2f", help="0–10 from enabled technical rules that this ticker passed."
                        ),
                    }
                )
                st.divider()
                export_col1, export_col2 = st.columns(2)
                _export_stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M")
                with export_col1:
                    st.download_button(
                        label="⬇️ Export Full Results (CSV)",
                        data=df.drop(columns=["raw_fund", "raw_tech", "raw_rs"], errors="ignore").to_csv(index=False).encode("utf-8"),
                        file_name=f"screener_results_{_export_stamp}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        help="Download every scored ticker from this scan as CSV, including pillar scores.",
                    )
                with export_col2:
                    _excel_buf = io.BytesIO()
                    with pd.ExcelWriter(_excel_buf, engine="xlsxwriter") as _writer:
                        df.drop(columns=["raw_fund", "raw_tech", "raw_rs"], errors="ignore").to_excel(_writer, index=False, sheet_name="Screener Results")
                    st.download_button(
                        label="⬇️ Export Full Results (Excel)",
                        data=_excel_buf.getvalue(),
                        file_name=f"screener_results_{_export_stamp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        help="Same full scan as the CSV export, in an Excel workbook.",
                    )

    # ==================================================================================
    # TAB 2: PORTFOLIO Evaluator
    # ==================================================================================
    elif selected_tab == "💼 Portfolio Evaluator":
        st.subheader("💼 Multi-Broker Portfolio Health Evaluator")
        st.caption("Supports raw holdings exports from Zerodha, Groww, Dhan, Upstox, Angel One, ICICI Direct, and Kotak.")
    
        col_input1, col_input2 = st.columns([1, 1])
        parsed_portfolio_tickers = []
    
        with col_input1:
            st.markdown("##### **Option A: Upload Broker Holdings Export**")
            port_file = st.file_uploader(
                "Upload CSV or Excel file",
                type=["csv", "xlsx", "xls"],
                key="port_upload",
                help="Export holdings from Zerodha, Groww, Dhan, Upstox, Angel One, ICICI Direct, or Kotak. The symbol column is detected automatically.",
            )
        
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
            raw_pasted = st.text_area(
                "Paste symbols (comma, space, or line separated):",
                placeholder="TATAMOTORS, HDFCBANK, TRENT, AUBANK",
                height=100,
                help="If you did not upload a file, paste NSE symbols here. Used only when the upload box is empty.",
            )
        
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
        
            if st.button(
                "🚀 Evaluate Portfolio Health",
                use_container_width=True,
                help="Score every loaded holding with the same weights and rules as the screener. Average Total is the portfolio health score.",
            ):
                with st.spinner("Evaluating portfolio holdings against 3-Pillar engine..."):
                    p_results, p_skipped = execute_scan(parsed_portfolio_tickers, w_fund, w_tech)
                
                    if not p_results.empty:
                        p_results = p_results.sort_values("Total Score", ascending=False).reset_index(drop=True)
                        st.session_state["p_results_df"] = p_results
        if "p_results_df" in st.session_state:
            p_results = st.session_state["p_results_df"]
            p_avg_score = p_results["Total Score"].mean()
            p_weak = p_results[p_results["Total Score"] < 5.0]
            p_strong = p_results[p_results["Total Score"] >= 7.0]
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric(
                "Portfolio Health Score",
                f"{p_avg_score:.2f} / 10",
                help="Average Total score across holdings. It uses the same engine as the screener, not broker P&L.",
            )
            col_p2.metric(
                "Strong Holdings (Score ≥ 7.0)",
                len(p_strong),
                help="Count of names whose Total is 7.0 or higher under your current weights and rules.",
            )
            col_p3.metric(
                "Weak Holdings (Score < 5.0)",
                len(p_weak),
                help="Count of names whose Total is below 5.0. Inspect the breakdown before acting; this is not a sell call.",
            )
            st.divider()
            st.subheader("📊 Portfolio Scoring Matrix")
            st.info("💡 Select a holding below or choose a symbol to inspect its detailed pillar breakdown.")
            p_table = p_results[[
                "Ticker", "Total Score", "Fundamental Score",
                "Technical Score", "Tech Passed", "CANSLIM Hits", "Sector"
            ]].copy()
            c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])
            with c_ctrl1:
                p_selected_ticker = st.selectbox(
                    "Select Holding to Inspect:",
                    options=p_results["Ticker"].tolist(),
                    key="port_select_tkr",
                    help="Choose a holding to open the pass/fail breakdown for each scoring rule.",
                )
            with c_ctrl2:
                st.write(f"Selected: **{p_selected_ticker}**")
            with c_ctrl3:
                if st.button(
                    "🔍 Breakdown",
                    key="port_view_btn",
                    use_container_width=True,
                    type="primary",
                    help="Show why this holding received its fundamental and technical scores.",
                ):
                    sel_ticker = st.session_state.get("port_select_tkr")
                    match = p_results[p_results["Ticker"] == sel_ticker]
                    if not match.empty:
                        show_pillar_details_modal(match.iloc[0].to_dict())
                    else:
                        st.toast(f"No result data found for {sel_ticker}.")
            st.dataframe(
                p_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                    "Total Score": st.column_config.NumberColumn(
                        "Total", format="%.2f", help="Weighted blend of Fund and Tech. The two weights always add to 10."
                    ),
                    "Fundamental Score": st.column_config.NumberColumn(
                        "Fund", format="%.2f", help="0–10 from enabled CANSLIM rules that this holding passed."
                    ),
                    "Technical Score": st.column_config.NumberColumn(
                        "Tech", format="%.2f", help="0–10 from enabled technical rules that this holding passed."
                    ),
                }
            )
            st.divider()
            st.download_button(
                label="⬇️ Export Portfolio Evaluation CSV",
                data=p_results.to_csv(index=False).encode("utf-8"),
                file_name="portfolio_evaluation_results.csv",
                mime="text/csv",
                use_container_width=True,
                help="Download the scored holdings table as CSV.",
            )

    # ==================================================================================
    # TAB 3: STOCKS SETTING UP (Authorized/Admin Only)
    # ==================================================================================
    elif selected_tab == "📈 Stocks Setting Up":
        st.subheader("📈 Stocks Setting Up")
        
        col_doc, col_empty = st.columns([1, 4])
        with col_doc:
            if st.button("📚 Setup Logic Documentation", use_container_width=True):
                show_setup_documentation_modal()
        
        st.caption("⚠️ **Disclaimer:** These are setups based exclusively on technical indicators. The user must do proper due diligence and risk assessment before committing money in the market.")
        st.divider()
        
        st.markdown("Specify the universes, technical setups to hunt for, and custom lists. We will rank the stocks using your active Fundamental/Technical weights, take the **Top N**, and scan for your selected setups.")
        
        with st.form("su_form"):
            col_u1, col_u2 = st.columns([2, 1])
            with col_u1:
                su_default = st.session_state.get("su_universes", ["Nifty 50"])
                su_default = [x for x in su_default if x in UNIVERSE_SOURCE_OPTIONS]
                if not su_default: 
                    su_default = ["Nifty 50"]
                    
                selected_universes_su = st.multiselect(
                    "Select Universes",
                    options=UNIVERSE_SOURCE_OPTIONS,
                    default=su_default,
                    help="You can select multiple index lists or F&O stocks at once. These save to your profile automatically."
                )
            with col_u2:
                top_n_su = st.number_input(
                    "Top N Stocks to Scan for Setups", 
                    min_value=1, max_value=1000, value=50, 
                    help="We will rank the combined list and only look for setups in the top N."
                )
            
            su_setups_default = st.session_state.get("su_setups", AVAILABLE_SETUPS)
            su_setups_default = [x for x in su_setups_default if x in AVAILABLE_SETUPS]
            if not su_setups_default:
                su_setups_default = AVAILABLE_SETUPS.copy()

            selected_setups = st.multiselect(
                "Select Technical Setups to Scan",
                options=AVAILABLE_SETUPS,
                default=su_setups_default,
                help="Choose which setup conditions to evaluate. Tickers matching ANY of the selected setups will appear in results."
            )

            with st.expander("📤 Upload Custom CSV/Excel List", expanded=False):
                uploaded_csv_su = st.file_uploader(
                    "Upload Universe File",
                    type=["csv", "xlsx", "xls"],
                    key="su_csv",
                    label_visibility="collapsed",
                )
            
            custom_raw_su = st.text_input(
                "Add Custom Tickers",
                value="",
                key="su_custom",
                help="A comma separated symbol list is expected (e.g. TRENT, HAL, TATAMOTORS). Spaces are fine, and .NS is added automatically."
            )
            
            force_refresh_su = st.checkbox("Force fresh price data (ignore cache)", value=False)

            btn_run_setups = st.form_submit_button("Run Scan", type="primary", use_container_width=True)

        if btn_run_setups:
            if not selected_setups:
                st.warning("Please select at least one technical setup to scan.")
            else:
                st.session_state["su_universes"] = selected_universes_su
                st.session_state["su_setups"] = selected_setups
                save_user_settings_to_db()

                csv_tickers_su = []
                if uploaded_csv_su is not None:
                    try:
                        if uploaded_csv_su.name.lower().endswith((".xlsx", ".xls")):
                            csv_df_su = pd.read_excel(uploaded_csv_su)
                        else:
                            csv_df_su = pd.read_csv(uploaded_csv_su)
                        csv_tickers_su = parse_broker_symbols(csv_df_su)
                        if csv_tickers_su:
                            st.success(f"Loaded {len(csv_tickers_su)} tickers from file.")
                        else:
                            st.error("Could not detect a symbol column in the uploaded file.")
                    except Exception as e:
                        st.error(f"Error parsing universe file: {e}")

                all_tickers_su = []
                for univ in selected_universes_su:
                    if univ == "F&O Stocks":
                        all_tickers_su.extend(load_fo_stocks())
                    else:
                        all_tickers_su.extend(load_index_list(univ))
                
                # --- NEW AGGRESSIVE PARSER FOR SETUPS TAB ---
                temp_str_su = custom_raw_su.replace("\n", ",").replace(" ", ",").replace(";", ",").replace("\t", ",")
                raw_list_su = [s.strip().upper() for s in temp_str_su.split(",") if s.strip()]
                custom_tickers_su = []
                for sym in raw_list_su:
                    clean = sym.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-BE", "").strip()
                    if clean:
                        custom_tickers_su.append(f"{clean}.NS" if not clean.endswith(".NS") else clean)
                # ----------------------------------------------
                
                all_tickers_su.extend(csv_tickers_su)
                all_tickers_su.extend(custom_tickers_su)
                all_tickers_su = list(set(all_tickers_su))
                
                if not all_tickers_su:
                    st.warning("No tickers found. Please select a universe, upload a CSV, or add custom tickers.")
                else:
                    if force_refresh_su:
                        fetch_daily.clear()
                        fetch_info.clear()
                        
                    with st.spinner(f"Ranking all {len(all_tickers_su)} combined stocks to find the Top {top_n_su}..."):
                        ranked_df_su, skipped_su = execute_scan(all_tickers_su, w_fund, w_tech, show_progress=False)
                    
                    if ranked_df_su.empty:
                        st.error("Could not retrieve price data to rank the selected stocks.")
                    else:
                        top_ranked_df = ranked_df_su.sort_values("Total Score", ascending=False).head(top_n_su)
                        top_tickers_list = top_ranked_df["Ticker"].tolist()
                        
                        st.write(f"Hunting for technical setups ({', '.join(selected_setups)}) within the **Top {len(top_tickers_list)}** highest-scoring stocks...")
                        progress_bar = st.progress(0)
                        setup_results = []
                        
                        for i, ticker in enumerate(top_tickers_list):
                            df = fetch_daily(ticker)
                            if df is not None and not df.empty:
                                triggered_tags = check_stocks_setting_up(df, enabled_setups=selected_setups)
                                if triggered_tags:
                                    setup_results.append({
                                        "Ticker": ticker.replace('.NS', ''),
                                        "Total Score": top_ranked_df[top_ranked_df["Ticker"] == ticker]["Total Score"].iloc[0],
                                        "LTP": round(df['Close'].iloc[-1], 2),
                                        "Setups Triggered": " | ".join(triggered_tags)
                                    })
                            progress_bar.progress((i + 1) / len(top_tickers_list))
                            
                        st.success("Setup Scan Complete!")
                        
                        if setup_results:
                            results_df_su = pd.DataFrame(setup_results)
                            
                            st.divider()
                            st.subheader("📈 TradingView 1-Click Clipboard Exporter")
                            tv_symbols_su = [f"NSE:{s}" for s in results_df_su["Ticker"].tolist()]
                            tv_content_su = ",".join(tv_symbols_su)
                            
                            st.write(f"**{len(tv_symbols_su)} matching tickers**. Copy below ➡️")
                            if tv_symbols_su:
                                st.code(tv_content_su, language="text")
                                
                            st.divider()
                            st.subheader("📋 Stocks Setting Up")
                            st.dataframe(results_df_su, use_container_width=True, hide_index=True)
                        else:
                            st.info(f"None of the Top {top_n_su} ranked stocks triggered your selected setup(s) today.")

    # ==================================================================================
    # TAB 4: USER GUIDE
    # ==================================================================================
    elif selected_tab == "🎛️ User-defined controls":
        st.subheader("User-defined controls")
        st.caption("These apply to every scan and to the top-scores email. They are saved for this account.")
        
        st.markdown("**Pillar weights (sum to 10)**")
        
        def update_fund_from_num():
            val = st.session_state.num_w_fund
            st.session_state["w_fund"] = val
            st.session_state["w_tech"] = 10 - val
            st.session_state.num_w_tech = 10 - val
            save_user_settings_to_db()
            _persist_digest_pref()

        def update_tech_from_num():
            val = st.session_state.num_w_tech
            st.session_state["w_tech"] = val
            st.session_state["w_fund"] = 10 - val
            st.session_state.num_w_fund = 10 - val
            save_user_settings_to_db()
            _persist_digest_pref()
            
        if "num_w_fund" not in st.session_state:
            st.session_state.num_w_fund = int(st.session_state.get("w_fund", 5))
        if "num_w_tech" not in st.session_state:
            st.session_state.num_w_tech = int(st.session_state.get("w_tech", 5))
            
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            st.number_input(
                "Fundamental Weight",
                min_value=0, max_value=10, step=1,
                key="num_w_fund",
                on_change=update_fund_from_num,
                help="Share of Total from the CANSLIM score. Technical is set to 10 minus this.",
            )
        with col_w2:
            st.number_input(
                "Technical Weight",
                min_value=0, max_value=10, step=1,
                key="num_w_tech",
                on_change=update_tech_from_num,
                help="Share of Total from the 10-point technical score. Fundamental is set to 10 minus this.",
            )
            
        st.caption(f"Fundamental {st.session_state.get('w_fund', 5)} + Technical {st.session_state.get('w_tech', 5)} = 10")
        
        st.markdown("**Pillar customization**")
        c_fund, c_tech = st.columns(2)
        with c_fund:
            if st.button(
                "⚙️ Fundamental Rules",
                use_container_width=True,
                help="Choose which CANSLIM checks count toward the fundamental score. Disabled rules are skipped for every ticker.",
            ):
                customize_fundamental_modal()
        with c_tech:
            if st.button(
                "⚙️ Technical Rules",
                use_container_width=True,
                help="Choose which of the 10 technical checks count. Each enabled rule that passes adds to the technical score.",
            ):
                customize_technical_modal()
        st.divider()
        st.markdown("**Top scores**")
        st.caption(
            "Sent once every day. Uses your pillar weights and which rules you have turned on. "
            "Not a stock pick or recommendation."
        )
        
        def update_opt_in():
            st.session_state["digest_opt_in"] = st.session_state.chk_digest_opt_in
            _on_digest_pref_change()
            
        def update_top_n():
            st.session_state["digest_top_n"] = st.session_state.num_digest_top_n
            _on_digest_pref_change()

        st.checkbox(
            "Email me top scores",
            value=bool(st.session_state.get("digest_opt_in", False)),
            key="chk_digest_opt_in",
            on_change=update_opt_in,
            help="This is sent once every day. Highest-scoring stocks from Nifty 50, Next 50, Midcap 150, Smallcap 250, Nifty 500, and F&O, ranked with your settings. Scores only — not picks.",
        )
        st.number_input(
            "Number of stocks per group/index",
            min_value=3,
            max_value=25,
            step=1,
            value=int(st.session_state.get("digest_top_n", 10)),
            key="num_digest_top_n",
            on_change=update_top_n,
            help="How many highest-scoring tickers to list under each index or F&O group (3–25).",
        )
        digest_quick = st.checkbox(
            "Quick preview (Nifty 50 + Next 50 fallback lists)",
            value=True,
            key="digest_quick_preview",
            help="Uncheck to score every live universe. That can take several minutes.",
        )
        
        if st.button(
            "Show top scores",
            use_container_width=True,
            help="Score the selected lists and open an inline preview below, including a TradingView copy of the top names across all indices.",
        ):
            from digest import run_digest
            
            digest_result = run_digest(
                quick=bool(digest_quick),
                send=False,
                extra_recipients=[],
                top_n=int(st.session_state.get("digest_top_n") or 10),
                skip_weekends=False,
                settings=_snapshot_engine(),
            )
            st.session_state["digest_preview"] = digest_result
            
        if st.session_state.get("digest_preview"):
            preview = st.session_state["digest_preview"]
            if preview.get("status") == "ok":
                st.divider()
                st.subheader("🏆 Top Scores Preview")
                st.caption(f"Scored {preview.get('ticker_count', 0)} unique tickers.")
                
                st.components.v1.html(preview.get("html") or "", height=480, scrolling=True)
                if preview.get("outbox_path"):
                    st.caption(f"Also saved to `{preview.get('outbox_path')}`.")

                st.subheader("📈 TradingView")
                st.caption(
                    "Every top-score name from all index/group lists in this preview "
                    "(Nifty 50, Next 50, Midcap, Smallcap, Nifty 500, F&O — whichever were scored). "
                    "A stock that appears in more than one list is included once. Copy the NSE:SYMBOL string into TradingView."
                )
                from digest import tradingview_watchlist
                tv_content = tradingview_watchlist(preview.get("sections") or [])
                tv_symbols = [part for part in tv_content.split(",") if part] if tv_content else []
                st.write(f"**{len(tv_symbols)} unique tickers** across all lists. Copy below ➡️")
                
                if tv_symbols:
                    st.code(tv_content, language="text")
                else:
                    st.info("No top-score tickers to copy.")
                    
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("Close Preview", use_container_width=True):
                        st.session_state.pop("digest_preview", None)
                        st.rerun()
                
                with col_btn2:
                    if st.session_state.get("digest_opt_in"):
                        from digest import is_smtp_configured, send_email
                        if is_smtp_configured() and st.button(
                            "Send preview to my email",
                            use_container_width=True,
                            help="Send the last preview HTML to the address on this login. Uses SMTP from secrets, not GitHub Actions.",
                        ):
                            html = preview.get("html") or ""
                            status = send_email(user_email, "FunTech top scores (preview)", html)
                            if status == "sent":
                                st.success(f"Sent to {user_email}")
                            else:
                                st.info(f"Not sent ({status}). HTML is in digest_outbox/.")
            else:
                st.warning(preview.get("status"))
                if st.button("Dismiss", key="dismiss_warning"):
                    st.session_state.pop("digest_preview", None)
                    st.rerun()

        st.divider()
        st.markdown("**Manual Save**")
        if st.button("💾 Save All Settings Now", use_container_width=True, type="primary"):
            save_user_settings_to_db()
            _persist_digest_pref()
            st.success("All your weights, rules, and preferences have been securely saved to your account!")

    elif selected_tab == "ℹ️ User Guide":
        st.subheader("ℹ️ Comprehensive User Guide & Feature Workflows")
        st.markdown(
            """
            Welcome to the **Quantitative Multi-Pillar Engine**. Hover the small **?** next to a control for a one- or two-sentence explanation. Below are step-by-step workflows for screening, portfolio health, weights, and TradingView export.
            """
        )
    
        st.divider()
    
        st.markdown("### 🎯 Core Features & Workflows")
    
        st.markdown("#### **1. Stock Screener (Finding High-Growth Momentum Candidates)**")
        st.markdown(
            """
            * **Step A (Select Universe):** On the **Stock Screener** tab, pick a live source — **Nifty 50, Next 50, Midcap 150, Smallcap 250, Nifty 500, or F&O Stocks** — or upload your own CSV/Excel file of stock symbols.
            * **Step B (Execute Scan):** Click **Run Screener Scan**. The multi-threaded engine fetches quarterly fundamentals and technical indicators in real-time.
            * **Step C (Inspect Detailed Rules):** Click **Breakdown** next to any stock to view exactly which CANSLIM metrics or technical rules passed, failed, or were skipped.
            """
        )
        st.markdown("#### **2. Portfolio Evaluator (Auditing Holdings Health)**")
        st.markdown(
            """
            * **Step A (Import Holdings):** Export your portfolio CSV/Excel statement from Zerodha, Groww, Upstox, Dhan, or Kotak and upload it under **Option A**, or paste tickers under **Option B**.
            * **Step B (Analyze Health):** Click **Evaluate Portfolio Health**. The system calculates an aggregate **Portfolio Health Score** (0-10) and flags lagging stocks scoring below 5.0.
            * **Step C (Export Audit):** Download the complete evaluation report as a CSV for off-line record keeping.
            """
        )
        st.markdown("#### **3. User-defined controls (weights, rules, top scores)**")
        st.markdown(
            """
            * **Adjust Weights:** On **User-defined controls**, change **Fundamental Weight** or **Technical Weight**. They always add to **10** — changing one adjusts the other automatically.
            * **Customize Rules:** On **User-defined controls**, click **Fundamental Rules** or **Technical Rules** to toggle specific criteria on/off.
            * **Auto-Persistence:** Your customized weights and active rule parameters automatically save to Supabase and persist across future logins.
            * **Top scores email:** On **User-defined controls**, check **Email me top scores**. This is sent once every day with the highest-scoring stocks from each NSE index/group. Set **Number of stocks per group/index** for how many rows to include. Click **Show top scores** to preview now — the preview also has a TradingView copy of the unique top names across all lists. This is a score ranking, not a stock pick.
            """
        )
        st.markdown("#### **4. Export to TradingView**")
        st.markdown(
            """
            * **Step A (Set Minimum Threshold):** Adjust the score slider (e.g., set to 7.0 or higher for top candidates).
            * **Step B (Copy Formatted Strings):** Click the copy icon in the formatted code snippet box (e.g., `NSE:TRENT,NSE:HAL,NSE:TATAMOTORS`).
            * **Step C (Import to TradingView):** Open TradingView -> Create New Watchlist -> Click **+ Add Symbol** -> Paste directly to add all stocks simultaneously.
            * **Top scores preview:** After **Show top scores**, copy the NSE:SYMBOL list of every unique top name across all scored indices (no score cutoff).
            """
        )
        st.divider()
        st.markdown("### 🏛️ Scoring documentation")
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.markdown("#### **Pillar 1: Fundamental (CANSLIM)**")
            st.markdown(
                """
                Enabled rules that can be evaluated are pass/fail. Missing data is **skipped** (not a fail). Score = passes ÷ evaluated × 10.

                * **C — Current earnings:** Latest quarter vs same quarter last year. Diluted EPS preferred, else net income. Pass if growth > **15%**. Yahoo annual `earningsGrowth` is not used.
                * **A — Sales:** Latest quarter **Total Revenue** vs same quarter last year. Pass if growth > **10%**. Cost of goods and Yahoo annual `revenueGrowth` are not used.
                * **N — New high:** Last price within **10%** of the 52-week high. The high is the better of Yahoo’s figure and the last **252** daily highs.
                * **S — Demand:** Over the last **20** sessions, volume on up-close days must exceed volume on down-close days. Tight bases are **T1/T2**, not S.
                * **L — Leader vs Nifty:** ~63-day return beats Nifty 50.
                * **Ls — Leader vs sector:** The same 63-day return beats same-sector names **in this scan**. Skipped if sector is unknown.
                * **I — Institutions:** Yahoo `heldPercentInstitutions` > **30%** of shares outstanding. Promoter-heavy names often fail. Skipped if missing.
                * **M — Market:** Nifty 50 above its 200-DMA. **Every stock gets the same result.** Does not rank names against each other.

                You can turn any letter off. This is a strength score, not a go/no-go filter.
                """
            )
        with col_g2:
            st.markdown("#### **Pillar 2: Technical (T1–T10)**")
            st.markdown(
                """
                Ten pass/fail chart checks. Missing data **fails**. Fewer than 30 daily bars → technical score 0. (These tests are unchanged pending a later review.)

                * **T1:** Close > 200-DMA and within 5% of the 50-DMA.
                * **T2:** Within 5% of the 20- **or** 50-DMA, and 10-day close volatility ≤ 6%.
                * **T3:** Close above the 200-DMA but not more than 25% above it.
                * **T4:** 50-DMA and 200-DMA each higher than 5 bars ago.
                * **T5 / T6 / T7:** RSI > 50 and rising (monthly / weekly / daily). “Rising” = higher than 2 bars ago.
                * **T8 / T10:** MACD line rising (monthly / daily).
                * **T9:** Weekly MACD above its signal, MACD > 0, and the line rising.

                Total = (Fundamental × fund weight + Technical × tech weight) ÷ 10. The two weights always add to 10.
                """
            )

    # ==================================================================================
    # TAB 5: ADMIN PANEL (DYNAMIC ROLE-BASED)
    # ==================================================================================
    elif selected_tab == "🛠️ Admin Panel":
        st.subheader("🛠️ Administrator Control & Registered System Users")
        st.success(f"Authenticated Administrator Access: `{user_email}`")
    
        st.divider()
    
        col_adm1, col_adm2 = st.columns([1, 1.2])
    
        with col_adm1:
            st.markdown("#### 📊 System Diagnostics")
            st.json({
                "Admin Email": user_email,
                "Admin Status": "Verified via profiles.role",
                "Supabase Connection": SUPABASE_AVAILABLE and get_supabase_client() is not None,
                "Active Weights": {
                    "Fundamental": w_fund,
                    "Technical": w_tech,
                }
            })
        
            if st.button(
                "🧹 Clear Global Application Cache",
                use_container_width=True,
                help="Drop cached NSE lists and price downloads so the next scan fetches live data. Does not delete user settings.",
            ):
                st.cache_data.clear()
                st.success("Global application cache cleared.")
            if st.button(
                "🌐 Check Universe Source Status (live fetch)",
                use_container_width=True,
                help="Hit NSE for every index and F&O source and report whether live lists or fallbacks were used.",
            ):
                with st.spinner("Fetching all 6 universe sources — this hits NSE live and may take a moment..."):
                    status_rows = []
                    for name in NSE_INDEX_FILES:
                        lst = load_index_list(name)
                        is_fallback = lst == FALLBACK_INDEX_LISTS.get(name)
                        status_rows.append({"Source": name, "Tickers": len(lst), "Using Fallback?": "⚠️ Yes" if is_fallback else "✅ Live"})
                    
                    fo_tier_used = "None — using fallback"
                    fo_tickers = []
                    for tier_name, tier_fn in [
                        ("Tier 1: stockIndices API", _fo_tier1_stock_indices),
                        ("Tier 2: equity-master API", _fo_tier2_equity_master),
                        ("Tier 3: dated CSV guess", _fo_tier3_dated_csv),
                    ]:
                        fo_tickers = tier_fn()
                        if fo_tickers:
                            fo_tier_used = tier_name
                            break
                    if not fo_tickers:
                        fo_tickers = FALLBACK_FO_STOCKS
                    status_rows.append({
                        "Source": "F&O Stocks", "Tickers": len(fo_tickers), "Using Fallback?": fo_tier_used
                    })
                st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
                st.caption(
                    "F&O now tries 3 independent live sources before falling back — this shows which one "
                        "(if any) actually succeeded, so you know exactly where the data came from."
                )
        with col_adm2:
            st.markdown("#### 👥 Registered System Users Directory")
            supabase = get_supabase_client()
            admin_supabase = get_supabase_admin_client()
            db_client = admin_supabase if admin_supabase else supabase
            
            user_list = []
        
            if supabase:
                try:
                    session = st.session_state.get("supabase_session")
                    if session and hasattr(session, "access_token"):
                        supabase.postgrest.auth(session.access_token)
                    profiles_res = supabase.table("profiles").select("*").execute()
                
                    if profiles_res.data:
                        for u in profiles_res.data:
                            user_list.append({
                                "Email": u.get("email", "N/A"),
                                "Role": u.get("role", "user").capitalize(),
                                "User ID": u.get("id"),
                                "Created At": str(u.get("created_at", ""))[:10]
                            })
                except Exception as e:
                    st.error(f"Error reading profiles table: {e}")
            
            if user_list:
                st.dataframe(pd.DataFrame(user_list), use_container_width=True, hide_index=True)
                st.caption(f"Total Registered Users Located: **{len(user_list)}**")
                
                st.divider()
                st.markdown("#### 🔐 User Authorization Management")
                st.caption("Grant users 'Authorized' status to unlock the 'Stocks Setting Up' module.")
                
                user_options = { f"{u['Email']} (Role: {u['Role']})": u['User ID'] for u in user_list }
                selected_user_label = st.selectbox("Select User to Modify:", options=list(user_options.keys()), key="admin_auth_user")
                
                if selected_user_label:
                    selected_uid = user_options[selected_user_label]
                    c_auth1, c_auth2 = st.columns(2)
                    with c_auth1:
                        if st.button("Grant 'Authorized' Access", use_container_width=True):
                            try:
                                res = db_client.table("profiles").update({"role": "authorized"}).eq("id", selected_uid).execute()
                                if res.data:
                                    st.success("User authorized! (Refresh page to see changes)")
                                else:
                                    st.error("⚠️ Update blocked by Supabase RLS. Add `SUPABASE_SERVICE_KEY` to your secrets.toml, or manually change their role in the Supabase dashboard.")
                            except Exception as e:
                                st.error(f"Error updating user: {e}")
                    with c_auth2:
                        if st.button("Revoke Access (Set to 'user')", use_container_width=True):
                            try:
                                res = db_client.table("profiles").update({"role": "user"}).eq("id", selected_uid).execute()
                                if res.data:
                                    st.success("User access revoked! (Refresh page to see changes)")
                                else:
                                    st.error("⚠️ Update blocked by Supabase RLS. Add `SUPABASE_SERVICE_KEY` to your secrets.toml, or manually change their role in the Supabase dashboard.")
                            except Exception as e:
                                st.error(f"Error updating user: {e}")
            else:
                st.info("ℹ️ No users found in `profiles` table. Make sure you ran the SQL trigger setup in Supabase Editor.")
        
        st.divider()
        st.markdown("#### 🗄️ Database Record Inspection (`user_settings`)")
        if supabase:
            try:
                full_res = supabase.table("user_settings").select("*").execute()
                if full_res.data:
                    st.dataframe(pd.DataFrame(full_res.data), use_container_width=True)
            except Exception as e:
                st.error(f"Error fetching table data: {e}")

    # ----------------------------------------------------------------------------------
    # Footer
    # ----------------------------------------------------------------------------------
    st.divider()
    st.caption(
        "**Disclaimer:** Third-party data feeds may be delayed or unsynchronized. "
        "Strictly educational content, not financial advice. Verify all setups prior to trading. "
        "For queries: vkiyer@hotmail.com."
    )

if __name__ == "__main__":
    _run_streamlit_ui()