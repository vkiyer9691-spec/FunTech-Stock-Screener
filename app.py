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
from pathlib import Path
import requests
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

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
# Constants & Defaults

# ----------------------------------------------------------------------------------
BENCHMARK = "^NSEI"
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

# ----------------------------------------------------------------------------------
# Dynamic Universe Sources (NSE Index Constituents & F&O List)

# ----------------------------------------------------------------------------------
# Stable, unchanging filenames for NSE's official index constituent CSVs.
NSE_INDEX_FILES = {
    "Nifty 50": "ind_nifty50list",
    "Nifty Next 50": "ind_niftynext50list",
    "Nifty Midcap 150": "ind_niftymidcap150list",
    "Nifty Smallcap 250": "ind_niftysmallcap250list",
    "Nifty 500": "ind_nifty500list",
}
# Small emergency fallbacks — only used if NSE's live endpoints are unreachable
# (e.g. blocked cloud IP). Not exhaustive; the app always tries live data first.
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
# Fallback for F&O eligible stocks — used only if NSE's live JSON API is unreachable.
# This is a manually curated approximation (~180 names) of the F&O universe, spanning
# all major sectors. NSE reviews F&O eligibility quarterly, so treat this as a safety
# net, not a source of truth — the live fetch is always tried first.
FALLBACK_FO_STOCKS = [
    # Nifty 50 + large caps
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "BHARTIARTL.NS",
    "ITC.NS", "LT.NS", "SBIN.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "MARUTI.NS",
    "M&M.NS", "SUNPHARMA.NS", "TATAMOTORS.NS", "KOTAKBANK.NS", "ULTRACEMCO.NS", "TITAN.NS",
    "AXISBANK.NS", "NTPC.NS", "ADANIENT.NS", "POWERGRID.NS", "ASIANPAINT.NS", "COALINDIA.NS",
    "BAJAJFINSV.NS", "NESTLEIND.NS", "TATASTEEL.NS", "HCLTECH.NS", "JSWSTEEL.NS", "WIPRO.NS",
    "GRASIM.NS", "TECHM.NS", "INDUSINDBK.NS", "CIPLA.NS", "SBILIFE.NS", "HDFCLIFE.NS",
    "DRREDDY.NS", "APOLLOHOSP.NS", "BRITANNIA.NS", "EICHERMOT.NS", "DIVISLAB.NS", "HINDALCO.NS",
    "BPCL.NS", "TATACONSUM.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "SHRIRAMFIN.NS", "ADANIPORTS.NS",
    "TRENT.NS", "ONGC.NS",
    # Banks, NBFCs & financials
    "DLF.NS", "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS",
    "AUBANK.NS", "PFC.NS", "RECLTD.NS", "IRFC.NS", "MFSL.NS", "CHOLAFIN.NS",
    "ICICIGI.NS", "ICICIPRULI.NS", "LICHSGFIN.NS", "BANDHANBNK.NS", "PEL.NS", "MUTHOOTFIN.NS",
    "SBICARD.NS", "M&MFIN.NS", "IDBI.NS", "IEX.NS", "CDSL.NS", "BSE.NS", "ANGELONE.NS",
    "IIFL.NS", "POONAWALLA.NS", "PNBHOUSING.NS",
    # IT & tech
    "LTIM.NS", "MPHASIS.NS", "PERSISTENT.NS", "COFORGE.NS", "LTTS.NS", "OFSS.NS", "TATAELXSI.NS",
    # Auto & auto ancillary
    "TVSMOTOR.NS", "ASHOKLEY.NS", "BOSCHLTD.NS", "MOTHERSON.NS", "BALKRISIND.NS", "MRF.NS",
    "EXIDEIND.NS", "BHARATFORG.NS", "TIINDIA.NS", "APOLLOTYRE.NS",
    # Metals, mining, materials & energy
    "VEDL.NS", "NMDC.NS", "SAIL.NS", "JINDALSTEL.NS", "NATIONALUM.NS", "HINDCOPPER.NS",
    "GAIL.NS", "IOC.NS", "PETRONET.NS", "IGL.NS", "ATGL.NS", "ADANIENSOL.NS", "ADANIGREEN.NS",
    "ADANIPOWER.NS", "TATAPOWER.NS", "NHPC.NS", "SJVN.NS",
    # Cement & construction
    "AMBUJACEM.NS", "SHREECEM.NS", "ACC.NS", "JKCEMENT.NS", "DALBHARAT.NS", "IRCTC.NS",
    "RVNL.NS", "HAL.NS", "BEL.NS", "BHEL.NS", "CUMMINSIND.NS", "SIEMENS.NS", "ABB.NS",
    "POLYCAB.NS", "HAVELLS.NS",
    # Pharma & healthcare
    "AUROPHARMA.NS", "LUPIN.NS", "TORNTPHARM.NS", "ALKEM.NS", "BIOCON.NS", "ZYDUSLIFE.NS",
    "GLENMARK.NS", "LAURUSLABS.NS", "IPCALAB.NS", "MANKIND.NS",
    # Consumer, FMCG & retail
    "GODREJCP.NS", "DABUR.NS", "MARICO.NS", "COLPAL.NS", "UBL.NS", "MCDOWELL-N.NS",
    "PIDILITIND.NS", "PAGEIND.NS", "VBL.NS", "JUBLFOOD.NS", "DMART.NS", "NYKAA.NS",
    # Realty
    "GODREJPROP.NS", "OBEROIRLTY.NS", "LODHA.NS", "PHOENIXLTD.NS", "PRESTIGE.NS",
    # New-age / digital
    "ZOMATO.NS", "PAYTM.NS", "POLICYBZR.NS", "NAUKRI.NS", "DELHIVERY.NS",
    # Others frequently in F&O
    "PIIND.NS", "SRF.NS", "UPL.NS", "GNFC.NS", "DEEPAKNTR.NS", "AARTIIND.NS",
    "VOLTAS.NS", "CONCOR.NS", "GMRAIRPORT.NS", "INDIGO.NS", "TRIDENT.NS", "SUNTV.NS",
    "PVRINOX.NS", "ESCORTS.NS", "SYNGENE.NS", "ABFRL.NS", "IDEA.NS", "GRANULES.NS",
    "CANFINHOME.NS", "MANAPPURAM.NS", "L&TFH.NS", "INDUSTOWER.NS", "COROMANDEL.NS",
    "BALRAMCHIN.NS", "NAVINFLUOR.NS", "TATACOMM.NS", "ASTRAL.NS", "SUPREMEIND.NS",
    "APLAPOLLO.NS", "HINDPETRO.NS", "RAMCOCEM.NS", "METROPOLIS.NS", "LALPATHLAB.NS",
]
# Static ticker -> sector fallback, used only when yfinance's .info genuinely omits
# 'sector' (common for many NSE mid/small-caps). Uses the same sector taxonomy as
# SECTOR_MAP above (Financial Services, Technology, etc.) so display stays consistent.
# Not exhaustive — a "best effort" reference table to reduce "Unknown" sightings,
# built from the same groupings used for FALLBACK_FO_STOCKS above.
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

# ----------------------------------------------------------------------------------
# Safe Supabase Helper & Persistence Engine

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

def is_admin(user) -> bool:
    """Dynamic Role Check via Supabase Profiles Table"""
    if not user:
        return False
    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
    if not user_id:
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        # Fallback for local development mode
        email = user.get("email") if isinstance(user, dict) else getattr(user, "email", "")
        return email.lower() == "vkiyer@hotmail.com"
    try:
        session = st.session_state.get("supabase_session")
        if session and hasattr(session, "access_token"):
            supabase.postgrest.auth(session.access_token)
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0].get("role") == "admin"
    except Exception:
        pass
    return False

def init_session_defaults():
    if "w_fund" not in st.session_state:
        st.session_state["w_fund"] = 4
    if "w_tech" not in st.session_state:
        st.session_state["w_tech"] = 4
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
            data = response.data[0]
            st.session_state["w_fund"] = int(data.get("w_fund", 4))
            st.session_state["w_tech"] = int(data.get("w_tech", 4))
            
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
        "w_fund": st.session_state.get("w_fund", 4),
        "w_tech": st.session_state.get("w_tech", 4),
        "fund_rules": fund_dict,
        "tech_rules": tech_dict,
        "digest_opt_in": bool(st.session_state.get("digest_opt_in", False)),
        "digest_top_n": int(st.session_state.get("digest_top_n", 10)),
        "updated_at": "now()"
    }
    try:
        supabase.table("user_settings").upsert(payload).execute()
    except Exception:
        payload.pop("digest_opt_in", None)
        payload.pop("digest_top_n", None)
        try:
            supabase.table("user_settings").upsert(payload).execute()
        except Exception as e:
            st.error(f"Failed to save settings: {e}")

# ----------------------------------------------------------------------------------
# Score History & Watchlist (require the scan_history / watchlist tables — see
# supabase_migration.sql. Both degrade gracefully and silently if the tables
# haven't been created yet, so the rest of the app keeps working either way.

# ----------------------------------------------------------------------------------

def _current_user_id():
    user = st.session_state.get("user")
    if not user:
        return None
    return user.get("id") if isinstance(user, dict) else getattr(user, "id", None)

def save_scan_history(results_df: pd.DataFrame):
    """Persists one row per ticker for this scan, so score trends can be charted
    over time. Called automatically after every successful screener scan."""
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
        # Supabase/PostgREST caps request size; chunk large universes (e.g. Nifty 500).
        chunk_size = 200
        for i in range(0, len(rows), chunk_size):
            supabase.table("scan_history").insert(rows[i:i + chunk_size]).execute()
    except Exception:
        # Most likely cause: the scan_history table doesn't exist yet (migration
        # not run). Fail silently rather than breaking the scan the user just ran.
        pass
@st.cache_data(ttl=300, show_spinner=False)

def _load_scan_history_cached(user_id: str, ticker: str, _supabase_url: str) -> pd.DataFrame:
    # _supabase_url is only present to vary the cache key across environments;
    # the actual client is re-fetched fresh each call since it can't be cached.
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
    """Returns the current user's watchlist tickers, or [] if unavailable/empty."""
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

def init_auth_session():
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "supabase_session" not in st.session_state:
        st.session_state["supabase_session"] = None
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
        
        if st.button(
            "Bypass Login (Developer / Local Mode)",
            use_container_width=True,
            help="Open the screener without Supabase. Settings stay on this device only and are not saved to the cloud.",
        ):
            st.session_state["user"] = {"id": "local-dev-id", "email": "vkiyer@hotmail.com"}
            st.session_state["supabase_session"] = None
            st.rerun()
        return False
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Account Access")
        auth_mode = st.radio(
            "Choose Mode",
            ["Login", "Sign Up"],
            key="auth_mode",
            help="Login uses an existing account. Sign Up creates one; you may need to confirm email in Supabase before the first login.",
        )
        email = st.text_input(
            "Email",
            key="auth_email",
            help="The address used for this account and, if you opt in, weekday morning scores.",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="auth_pass",
            help="Supabase account password. This app never emails your password.",
        )
        if auth_mode == "Login":
            if st.button(
                "Log In",
                use_container_width=True,
                type="primary",
                help="Sign in and load your saved weights, rules, and morning-scores preference.",
            ):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state["user"] = res.user
                    st.session_state["supabase_session"] = res.session
                    
                    user_id = getattr(res.user, "id", None)
                    if user_id:
                        load_user_settings_from_db(user_id)
                    st.success("Login successful!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")
        else:
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
                    st.success("Account created! Check your email or log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")
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
@st.cache_resource

def _get_freshness_tracker() -> dict:
    """
    A dict that persists across reruns AND across user sessions (unlike
    st.session_state, which is per-session, or st.cache_data, which copies
    rather than shares). Used to record when data sources last actually
    fetched (not served from cache), for the sidebar freshness indicator.
    """
    return {}
@st.cache_data(ttl=86400, show_spinner=False)

def load_index_list(index_name: str) -> list:
    """
    Fetches the live, current constituent list for a given NSE index.
    Tries NSE's modern CDN first, then the legacy archive host, then falls
    back to a small curated list if both live sources are unreachable
    (e.g. NSE blocking a cloud-hosted IP).
    """
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
_FO_MIN_PLAUSIBLE_COUNT = 100  # NSE's real F&O universe is ~180-220; anything far
                                # below this signals a truncated/paginated response,
                                # not a genuine full list — treat it as a failure.

def _nse_session(referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    })
    # Cookie handshake: NSE's API rejects requests without valid session cookies.
    session.get(referer, timeout=6)
    return session

def _fo_tier1_stock_indices() -> list:
    """Primary source: NSE's equity-stockIndices JSON API. Tried twice (transient
    handshake failures are common). Rejected if suspiciously small (see
    _FO_MIN_PLAUSIBLE_COUNT) — a 200 response isn't proof of a complete list."""
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
                if len(tickers) >= _FO_MIN_PLAUSIBLE_COUNT:
                    return tickers
        except Exception:
            pass
        time.sleep(0.5)
    return []

def _fo_tier2_equity_master() -> list:
    """Secondary source: NSE's equity-master JSON, a dict of {category: [symbols]}
    used to populate their market-watch dropdowns. The exact key spelling for the
    F&O category isn't publicly documented and can vary, so this scans all keys
    defensively for anything that looks like an F&O category rather than assuming
    one exact string."""
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
                if len(tickers) >= _FO_MIN_PLAUSIBLE_COUNT:
                    return tickers
    except Exception:
        pass
    return []

def _parse_fo_mktlots_csv(text: str) -> list:
    """The fo_mktlots CSV has two stacked tables (index derivatives, then individual
    stock derivatives) sharing one file — a plain pd.read_csv would misread the
    second header row as data. This walks the raw text, finds the individual-
    securities section by its header line, then reads only that block."""
    lines = text.splitlines()
    start_idx = next(
        (i for i, ln in enumerate(lines) if "derivatives on individual securities" in ln.lower()),
        None,
    )
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
    """Tertiary source: NSE republishes a dated fo_mktlots_DDMMYYYY.csv file each
    derivatives cycle with no stable/predictable filename. This guesses a handful
    of recent likely dates (month-end, and a few days around it, for the current
    and prior month) — a best-effort attempt, not a reliable primary source."""
    today = date.today()
    candidate_dates = set()
    for months_back in range(2):
        year, month = today.year, today.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        # last day of that month
        if month == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        for offset in range(-3, 2):  # a few days either side of month-end
            candidate_dates.add(last_day + timedelta(days=offset))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for d in sorted(candidate_dates, reverse=True):
        url = f"https://nsearchives.nseindia.com/content/fo/fo_mktlots_{d.strftime('%d%m%Y')}.csv"
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200 and "symbol" in resp.text.lower():
                tickers = _parse_fo_mktlots_csv(resp.text)
                if len(tickers) >= _FO_MIN_PLAUSIBLE_COUNT:
                    return tickers
        except Exception:
            continue
    return []
@st.cache_data(ttl=86400, show_spinner=False)

def load_fo_stocks() -> list:
    """
    Fetches the current F&O (Futures & Options) eligible stock list, trying three
    independent live sources in sequence before giving up:
      1. NSE's equity-stockIndices JSON API (fast, usually works)
      2. NSE's equity-master JSON (different endpoint, different failure mode)
      3. The dated fo_mktlots CSV, guessing a handful of recent likely filenames
    Each is validated against a minimum plausible count so a "successful but
    truncated" response doesn't get mistaken for the real thing. If all three
    fail, falls back to a curated list of ~190 well-known liquid F&O names.
    """
    for tier_fn in (_fo_tier1_stock_indices, _fo_tier2_equity_master, _fo_tier3_dated_csv):
        tickers = tier_fn()
        if tickers:
            _get_freshness_tracker()["universe:F&O Stocks"] = (pd.Timestamp.now(), "live")
            return tickers
    _get_freshness_tracker()["universe:F&O Stocks"] = (pd.Timestamp.now(), "fallback")
    return FALLBACK_FO_STOCKS
UNIVERSE_SOURCE_OPTIONS = list(NSE_INDEX_FILES.keys()) + ["F&O Stocks"]
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
        "sector": None,  # bug fix: was "Unknown", which silently blocked yfinance's real value below
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
    # yfinance genuinely omits 'sector' for a meaningful chunk of NSE tickers (more
    # noticeable now that larger universes are being scanned). Fall back to a static
    # curated map before giving up and showing "Unknown".
    if not default_info.get("sector"):
        default_info["sector"] = SYMBOL_SECTOR_MAP.get(ticker, "Unknown")
    return default_info

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
    if col2.button("Apply & Save", key="apply_fund", help="Store these toggles for scans and the weekday morning scores email."):
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
    if col2.button("Apply & Save", key="apply_tech", help="Store these toggles for scans and the weekday morning scores email."):
        save_user_settings_to_db()
        st.rerun()

@st.dialog("FunTech daily morning scores", width="large")
def show_digest_preview_modal(preview: dict):
    st.caption(
        f"Scored {preview.get('ticker_count', 0)} unique tickers. "
        "This window is a one-time preview — it will not stay on the screener, portfolio, or other tabs."
    )
    st.components.v1.html(preview.get("html") or "", height=640, scrolling=True)
    if preview.get("outbox_path"):
        st.caption(f"Also saved to `{preview.get('outbox_path')}`.")
    if st.button("Done", type="primary", use_container_width=True, help="Close this preview. It will not appear again until you generate a new one."):
        st.session_state["digest_preview_open"] = False
        st.rerun()

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
    if SUPABASE_AVAILABLE:
        st.divider()
        st.markdown("**📈 Score History**")
        _user = st.session_state.get("user")
        _uid = _user.get("id") if isinstance(_user, dict) else getattr(_user, "id", None)
        history_df = load_scan_history(_uid, ticker) if _uid else pd.DataFrame()
        if history_df.empty:
            st.caption("No history yet for this ticker — it'll build up as you run scans over time.")
        else:
            st.line_chart(history_df.set_index("scan_time")[["total_score", "fundamental_score", "technical_score"]])
    st.divider()
    if st.button(
        "❌ Close Breakdown",
        use_container_width=True,
        type="primary",
        help="Close this panel and return to the table.",
    ):
        st.session_state["active_inspect_ticker"] = None
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
    """
    Wilder's RSI, matching the convention pandas_ta previously used.
    Self-contained (no pandas_ta dependency) — pandas_ta is a largely unmaintained
    library that was found to silently return None/empty results under pandas 3.0,
    which made every RSI/MACD-based technical rule (T5-T10) always evaluate False without raising any visible error.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)  # no losses at all -> RSI 100, not NaN/inf
    return rsi

def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    Standard MACD (self-contained, see compute_rsi docstring for why). Column order
    matches pandas_ta's old convention — [MACD, MACDh, MACDs] — so existing code
    indexing by position (.iloc[:, 0] for MACD line, .iloc[:, 2] for signal line)
    keeps working unchanged.
    Note: unlike SMA, EMA doesn't need a full `slow`-length window to produce a
    value — only a low floor is enforced here (not slow+signal), since monthly
    data (2y of daily -> ~24 bars) would otherwise always fall short and silently
    zero out the monthly MACD rule, the same failure mode this replaces.
    """
    if len(series.dropna()) < signal + 2:
        return pd.DataFrame(columns=["MACD", "MACDh", "MACDs"])
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"MACD": macd_line, "MACDh": hist, "MACDs": signal_line})

def _yoy_latest_vs_year_ago(df: pd.DataFrame | None, needles: list[str]) -> float | None:
    """(latest quarter − quarter ~1y ago) / |year-ago|, Yahoo columns newest-first."""
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
    """C2: quarterly YoY. Prefer diluted EPS; else net income. Ignore annual earningsGrowth."""
    for key in ("quarterly_eps_yoy", "quarterly_ni_yoy"):
        val = info.get(key)
        if val is not None and pd.notna(val):
            return float(val)
    return None


def canslim_a_growth(info: dict) -> float | None:
    """A2: quarterly Total Revenue YoY. Ignore Yahoo revenueGrowth."""
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
    """N4: max of Yahoo 52-week high (if present) and last ~252 daily highs."""
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
    """S3: last `sessions` bars, volume on up-close days vs down-close days."""
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
    if show_progress and _in_streamlit():
        progress = st.progress(0, text="Fetching stock data...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_stock, tkr): tkr for tkr in ticker_list}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if progress:
                progress.progress(completed / len(ticker_list), text=f"Processing universe... ({completed}/{len(ticker_list)})")
            elif show_progress:
                print(f"Digest scan {completed}/{len(ticker_list)}", flush=True)
            tkr, daily, info = future.result()
            if daily is not None:
                stock_data[tkr] = {"daily": daily, "info": info}
                if len(daily) >= 63:
                    ret = (daily["Close"].iloc[-1] / daily["Close"].iloc[-63] - 1) * 100
                    sec = info.get("sector", "Unknown")
                    # Don't group "Unknown" sector stocks together — they're not
                    # actually peers of each other, just tickers missing metadata.
                    # Grouping them created a meaningless synthetic sector average.
                    if sec and sec != "Unknown":
                        sector_returns.setdefault(sec, []).append(ret)
    if progress:
        progress.empty()
    if _in_streamlit():
        # Stash raw per-ticker price history for reuse by the Historical Validation
        # (backtest) tool below, so it doesn't need to re-fetch everything separately.
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

def _run_streamlit_ui():
    """Streamlit-only entry. Kept off the import path so daily_digest.py can reuse the engine."""
    _apply_page_chrome()
    if "user" not in st.session_state or st.session_state["user"] is None:
        render_login_screen()
        st.stop()
    init_session_defaults()
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
    st.sidebar.markdown(f"👤 **User:** `{user_email}`")
    if user_is_admin:
        st.sidebar.markdown("⭐ **Role:** `Administrator`")
    if st.sidebar.button(
        "🚪 Log Out",
        use_container_width=True,
        help="End this session. Unsaved on-screen results are cleared; cloud settings stay in Supabase.",
    ):
        supabase = get_supabase_client()
        if supabase:
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
        st.session_state.clear()
        st.rerun()
    st.sidebar.divider()
    st.title("📊 NSE Stock Screener & Portfolio Evaluator")
    st.caption("Two-pillar engine (CANSLIM fundamentals + technicals) for NSE traders and investors.")
    target_ticker = st.session_state.get("active_inspect_ticker")
    if target_ticker:
        found_row = None
        if "results_df" in st.session_state and not st.session_state["results_df"].empty:
            match = st.session_state["results_df"][st.session_state["results_df"]["Ticker"] == target_ticker]
            if not match.empty:
                found_row = match.iloc[0].to_dict()
        if not found_row and "p_results_df" in st.session_state and not st.session_state["p_results_df"].empty:
            match = st.session_state["p_results_df"][st.session_state["p_results_df"]["Ticker"] == target_ticker]
            if not match.empty:
                found_row = match.iloc[0].to_dict()
        st.session_state["active_inspect_ticker"] = None
        if found_row:
            show_pillar_details_modal(found_row)
        else:
            st.toast(f"No result data found for {target_ticker}. Please run analysis first.")

    # ----------------------------------------------------------------------------------
    # Sidebar Controls & Weight Auto-Saver

    # ----------------------------------------------------------------------------------
    st.sidebar.header("⚙️ Engine Controls")
    st.sidebar.subheader("1. Pillar Weights")
    def on_weight_change():
        save_user_settings_to_db()
        _persist_digest_pref()
    w_fund = st.sidebar.slider(
        "Fundamental Weight",
        0,
        10,
        key="w_fund",
        on_change=on_weight_change,
        help="How much the CANSLIM fundamental score counts in Total. Technical takes the rest of the mix; the two weights are scaled if they do not add to 10.",
    )
    w_tech = st.sidebar.slider(
        "Technical Weight",
        0,
        10,
        key="w_tech",
        on_change=on_weight_change,
        help="How much the 10-point technical score counts in Total. Leadership vs Nifty and sector is inside the fundamental score (L / Ls), not a third pillar.",
    )
    _wsum = max(1, int(w_fund) + int(w_tech))
    st.sidebar.caption(
        f"Mix: {100 * int(w_fund) / _wsum:.0f}% fundamental / {100 * int(w_tech) / _wsum:.0f}% technical"
        if int(w_fund) + int(w_tech) > 0
        else "Set at least one weight above 0."
    )
    st.sidebar.divider()
    st.sidebar.subheader("2. Pillar Customization")
    if st.sidebar.button(
        "⚙️ Fundamental Rules",
        use_container_width=True,
        help="Choose which CANSLIM checks count toward the fundamental score. Disabled rules are skipped for every ticker.",
    ):
        customize_fundamental_modal()
    if st.sidebar.button(
        "⚙️ Technical Rules",
        use_container_width=True,
        help="Choose which of the 10 technical checks count. Each enabled rule that passes adds to the technical score.",
    ):
        customize_technical_modal()

    st.sidebar.divider()
    st.sidebar.subheader("Daily morning scores")
    st.sidebar.caption(
        "Weekdays at 8:30 AM IST — score ranking for each index/group before the cash market opens at 9:15. "
        "Uses your pillar weights and which rules you have turned on. Not a stock pick or recommendation."
    )

    def _snapshot_engine():
        w_f = int(st.session_state.get("w_fund", 4))
        w_t = int(st.session_state.get("w_tech", 4))
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
            str(_id or ""),
            str(_email or ""),
            bool(st.session_state.get("digest_opt_in")),
            int(st.session_state.get("digest_top_n") or 10),
            settings=_snapshot_engine(),
        )

    def _on_digest_pref_change():
        _persist_digest_pref()

    st.sidebar.checkbox(
        "Email me weekday morning scores",
        key="digest_opt_in",
        on_change=_on_digest_pref_change,
        help="Emails the highest-scoring stocks from Nifty 50, Next 50, Midcap 150, Smallcap 250, Nifty 500, and F&O, ranked with your settings. Scores only — not picks.",
    )
    st.sidebar.number_input(
        "Number of stocks per group/index",
        min_value=3,
        max_value=25,
        step=1,
        key="digest_top_n",
        on_change=_on_digest_pref_change,
        help="How many highest-scoring tickers to list under each index or F&O group in the weekday email (3–25).",
    )
    digest_quick = st.sidebar.checkbox(
        "Quick preview (Nifty 50 + Next 50 fallback lists)",
        value=True,
        key="digest_quick_preview",
        help="Uncheck to score every live universe. That can take several minutes.",
    )
    if st.sidebar.button(
        "📬 Generate preview digest",
        use_container_width=True,
        help="Score the selected lists and open a one-time preview window. It will not stay on other tabs.",
    ):
        from digest import run_digest, is_smtp_configured
        with st.spinner("Scoring universes for the morning email..."):
            digest_result = run_digest(
                quick=bool(digest_quick),
                send=False,
                extra_recipients=[],
                top_n=int(st.session_state.get("digest_top_n") or 10),
                skip_weekends=False,
                settings=_snapshot_engine(),
            )
        st.session_state["digest_preview"] = digest_result
        st.session_state["digest_preview_open"] = digest_result.get("status") == "ok"
        if digest_result.get("status") == "ok":
            st.sidebar.success("Preview opened. Close it when you are done — it will not follow you to other tabs.")
        else:
            st.sidebar.warning(digest_result.get("status"))

    if st.session_state.get("digest_opt_in") and st.session_state.get("digest_preview"):
        from digest import is_smtp_configured
        if is_smtp_configured() and st.sidebar.button(
            "Send preview to my email",
            use_container_width=True,
            help="Send the last preview HTML to the address on this login. Uses SMTP from secrets, not GitHub Actions.",
        ):
            from digest import send_email
            html = st.session_state["digest_preview"].get("html") or ""
            status = send_email(user_email, "FunTech daily morning scores (preview)", html)
            if status == "sent":
                st.sidebar.success(f"Sent to {user_email}")
            else:
                st.sidebar.info(f"Not sent ({status}). HTML is in digest_outbox/.")

    # ----------------------------------------------------------------------------------
    # Dynamic Navigation Tabs

    # ----------------------------------------------------------------------------------
    # Preview is a one-shot dialog: show it, then drop the flag so a later tab
    # click or other widget rerun cannot paint the scores on the page again.
    if st.session_state.get("digest_preview_open") and st.session_state.get("digest_preview"):
        show_digest_preview_modal(st.session_state["digest_preview"])
        st.session_state["digest_preview_open"] = False

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
        universe_source = st.sidebar.selectbox(
            "Universe Source",
            options=UNIVERSE_SOURCE_OPTIONS,
            index=UNIVERSE_SOURCE_OPTIONS.index("Nifty 500"),
            key="scr_universe_source",
            help="Which NSE index or F&O list to load. Live constituents are cached 24 hours; if NSE is unreachable the app uses a small built-in list.",
        )
        with st.sidebar.status(f"Loading {universe_source}...", expanded=False) as _status:
            if universe_source == "F&O Stocks":
                base_list = load_fo_stocks()
            else:
                base_list = load_index_list(universe_source)
            _status.update(label=f"{universe_source}: {len(base_list)} tickers loaded", state="complete")
        # Data freshness indicator — surfaces staleness immediately instead of only
        # showing up as "weird results" after a scan.
        _tracker = _get_freshness_tracker()
        _univ_info = _tracker.get(f"universe:{universe_source}")
        _price_ts = _tracker.get("prices")
        _freshness_lines = []
        if _univ_info:
            _ts, _kind = _univ_info
            _age_min = (pd.Timestamp.now() - _ts).total_seconds() / 60
            _icon = "✅" if _kind == "live" else "⚠️"
            _freshness_lines.append(f"{_icon} {universe_source} list: {_kind}, {_age_min:.0f} min ago")
        else:
            _freshness_lines.append(f"ℹ️ {universe_source} list: served from cache this session")
        if _price_ts:
            _age_min = (pd.Timestamp.now() - _price_ts).total_seconds() / 60
            _freshness_lines.append(f"✅ Price data: last fetched {_age_min:.0f} min ago")
        _last_scan = st.session_state.get("last_scan_time")
        if _last_scan:
            _age_min = (pd.Timestamp.now() - _last_scan).total_seconds() / 60
            _freshness_lines.append(f"🕒 Last scan run: {_age_min:.0f} min ago")
        st.sidebar.caption("  \n".join(_freshness_lines))
        with st.sidebar.expander("📤 Upload Custom CSV/Excel List", expanded=False):
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
                    st.sidebar.success(f"Loaded {len(csv_tickers)} tickers from file.")
                else:
                    st.sidebar.error("Could not detect a symbol column in the uploaded file.")
            except Exception as e:
                st.sidebar.error(f"Error parsing universe file: {e}")
        full_options = list(dict.fromkeys(base_list + csv_tickers))
        # Default to the FULL list whenever the source (or uploaded file) changes, so
        # switching sources always starts with everything selected — no extra click needed.
        # The widget key changes with the source/CSV state, which resets the selection
        # to this new default; manual edits are preserved as long as source/CSV don't change.
        if csv_tickers:
            default_selection = csv_tickers
            universe_state_tag = f"csv:{len(csv_tickers)}"
        else:
            default_selection = base_list
            universe_state_tag = "idx"
        selected_universe = st.sidebar.multiselect(
            "Active Tickers",
            options=full_options,
            default=default_selection,
            key=f"scr_active_tickers::{universe_source}::{universe_state_tag}",
            help="Tickers that will be scored. Deselect names to skip them. Switching index or uploading a file resets this list.",
        )
        custom_raw = st.sidebar.text_input(
            "Add Custom Tickers",
            value="",
            help="Extra NSE symbols, comma-separated (e.g. TRENT, HDFCBANK). .NS is added if you omit it.",
        )
        custom_tickers = [t.strip().upper() if t.strip().upper().endswith(".NS") else f"{t.strip().upper()}.NS" for t in custom_raw.split(",") if t.strip()]
        watchlist_tickers = []
        # ==========================================================================
        # DISABLED (commented out by request, YYYY-MM-DD) — WATCHLIST SIDEBAR PANEL
        # To re-enable: uncomment this block. Backend functions (get_watchlist,
        # add_to_watchlist, remove_from_watchlist) are untouched and still defined.
        # ==========================================================================
        # if SUPABASE_AVAILABLE:
        #     with st.sidebar.expander("⭐ My Watchlist", expanded=False):
        #         _wl = st.session_state.get("watchlist_cache")
        #         if _wl is None:
        #             _wl = get_watchlist()
        #             st.session_state["watchlist_cache"] = _wl
        #         if not _wl:
        #             st.caption("No starred tickers yet. Star a ticker from the results table below after running a scan.")
        #         else:
        #             st.caption(f"{len(_wl)} starred ticker(s):")
        #             st.write(", ".join(_wl))
        #             include_watchlist = st.checkbox("Include watchlist in this scan", value=False, key="scr_include_watchlist")
        #             if include_watchlist:
        #                 watchlist_tickers = _wl
        #             if st.button("🗑️ Clear entire watchlist", key="scr_clear_watchlist"):
        #                 for t in _wl:
        #                     remove_from_watchlist(t)
        #                 st.session_state["watchlist_cache"] = None
        #                 st.rerun()
        # ==========================================================================
        # END DISABLED — WATCHLIST SIDEBAR PANEL
        # ==========================================================================
        universe = list(dict.fromkeys(selected_universe + custom_tickers + watchlist_tickers))
        if len(universe) > 150:
            st.sidebar.warning(f"{len(universe)} tickers selected — a full scan will take a while.")
        force_refresh = st.sidebar.checkbox(
            "Force fresh price data (ignore 30-min cache)",
            value=False,
            help="Normally price data is cached for 30 minutes so repeated scans are fast. "
                 "Check this to bypass that and re-fetch from yfinance — useful right after "
                 "market close, or if you suspect stale data. This does NOT re-fetch the "
                 "universe list (Nifty 500 etc.) — that's cached separately for 24h.",
        )
        run_scan = st.sidebar.button(
            "🔍 Run Screener Scan",
            use_container_width=True,
            help="Score every ticker in Active Tickers plus any custom symbols, using the weights and rules above. Large lists take several minutes.",
        )
        if run_scan:
            if not universe:
                st.warning("Select at least one ticker.")
            else:
                if force_refresh:
                    # Targeted clear — only price/info caches, NOT the universe-list caches
                    # (which are expensive 24h-cached NSE fetches and shouldn't be wiped
                    # just because the user wants fresh prices).
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
                # Sector-level summary — quickly see which sectors are showing strength
                # in this scan, without scrolling the full ticker-by-ticker table.
                # ==========================================================================
                # DISABLED (commented out by request) — SECTOR SUMMARY VIEW
                # To re-enable: uncomment this block.
                # ==========================================================================
                # with st.expander("📊 Sector Summary", expanded=False):
                    # sector_summary = (
                        # df.groupby("Sector")
                        # .agg(
                            # Tickers=("Ticker", "count"),
                            # **{
                                # "Avg Total": ("Total Score", "mean"),
                                # "Avg Fund": ("Fundamental Score", "mean"),
                                # "Avg Tech": ("Technical Score", "mean"),
                                # "Avg RS": ("Relative Strength Score", "mean"),
                            # },
                        # )
                        # .round(2)
                        # .sort_values("Avg Total", ascending=False)
                        # .reset_index()
                    # )
                    # st.dataframe(
                        # sector_summary,
                        # use_container_width=True,
                        # hide_index=True,
                        # column_config={
                            # "Avg Total": st.column_config.NumberColumn("Avg Total", format="%.2f"),
                            # "Avg Fund": st.column_config.NumberColumn("Avg Fund", format="%.2f"),
                            # "Avg Tech": st.column_config.NumberColumn("Avg Tech", format="%.2f"),
                            # "Avg RS": st.column_config.NumberColumn("Avg RS", format="%.2f"),
                        # },
                    # )
                    # if (df["Sector"] == "Unknown").any():
                        # _unk_count = int((df["Sector"] == "Unknown").sum())
                        # st.caption(f"ℹ️ {_unk_count} ticker(s) have no sector data and are grouped under 'Unknown'.")
                # ==========================================================================
                # END DISABLED — SECTOR SUMMARY VIEW
                # ==========================================================================
                st.divider()
                # Historical Validation (Backtest) — scoped honestly to the Technical
                # score only. yfinance only exposes CURRENT fundamentals (no
                # point-in-time history), so Fundamental/RS can't be reconstructed
                # for a past date without misleadingly mixing today's fundamentals
                # into a "historical" score. Technical score, by contrast, can be
                # correctly recomputed from price history alone at any past cutoff.
                # ==========================================================================
                # DISABLED (commented out by request) — HISTORICAL VALIDATION (BACKTEST)
                # To re-enable: uncomment this block. Also uncomment the line in
                # execute_scan() that populates st.session_state['scan_raw_daily'],
                # if that was also disabled.
                # ==========================================================================
                # with st.expander("🔬 Historical Validation (Technical Score Backtest)", expanded=False):
                    # st.caption(
                        # "Checks whether stocks with a higher **Technical Score** at some point in the past "
                        # "went on to perform better since then. Uses the price history already fetched in this "
                        # "session's scan — no extra API calls. Limited to the Technical score only: Fundamental "
                        # "and Relative Strength can't be reconstructed for a past date since yfinance only "
                        # "exposes current-day fundamentals, not historical point-in-time data."
                    # )
                    # _raw_daily = st.session_state.get("scan_raw_daily", {})
                    # if not _raw_daily:
                        # st.info("Run a scan above first — this reuses that scan's price data.")
                    # else:
                        # _lookback_options = {"1 Month Ago": 21, "3 Months Ago": 63, "6 Months Ago": 126}
                        # _lb_label = st.selectbox("Look back to:", options=list(_lookback_options.keys()), index=1, key="bt_lookback")
                        # _lb_days = _lookback_options[_lb_label]
                        # if st.button("▶️ Run Historical Validation", key="bt_run_btn"):
                            # bt_rows = []
                            # for _tkr, _daily_full in _raw_daily.items():
                                # if _daily_full is None or len(_daily_full) < _lb_days + 60:
                                    # continue  # not enough history before AND after the cutoff
                                # _daily_hist = _daily_full.iloc[:-_lb_days]
                                # _tech_score_hist, _, _ = compute_technical_score(_daily_hist)
                                # _price_cutoff = _daily_hist["Close"].iloc[-1]
                                # _price_now = _daily_full["Close"].iloc[-1]
                                # _fwd_return = (_price_now / _price_cutoff - 1) * 100
                                # bt_rows.append({
                                    # "Ticker": _tkr,
                                    # "Tech Score (at cutoff)": _tech_score_hist,
                                    # "Forward Return %": round(_fwd_return, 2),
                                # })
                            # if len(bt_rows) < 5:
                                # st.warning(
                                    # f"Only {len(bt_rows)} ticker(s) had enough price history for this lookback "
                                    # f"period — try a shorter lookback or a larger universe for a meaningful sample."
                                # )
                            # else:
                                # bt_df = pd.DataFrame(bt_rows)
                                # bt_df["Score Bucket"] = pd.cut(
                                    # bt_df["Tech Score (at cutoff)"],
                                    # bins=[0, 2, 4, 6, 8, 10], include_lowest=True,
                                    # labels=["0-2", "2-4", "4-6", "6-8", "8-10"],
                                # )
                                # bucket_summary = (
                                    # bt_df.groupby("Score Bucket", observed=True)
                                    # .agg(Tickers=("Ticker", "count"), **{"Avg Forward Return %": ("Forward Return %", "mean")})
                                    # .round(2)
                                # )
                                # corr = bt_df["Tech Score (at cutoff)"].corr(bt_df["Forward Return %"])
                                # m1, m2 = st.columns(2)
                                # m1.metric("Sample Size", len(bt_df))
                                # m2.metric(
                                    # "Correlation (Score vs Forward Return)", f"{corr:.2f}",
                                    # help="Ranges -1 to +1. Positive means higher technical scores historically "
                                         # "preceded better forward returns in this sample. Close to 0 means little "
                                         # "or no relationship. This is a small, single-run sample — treat as a "
                                         # "rough directional signal, not statistical proof.",
                                # )
                                # st.write(f"**Average forward return by score bucket** ({_lb_label} → now):")
                                # st.bar_chart(bucket_summary["Avg Forward Return %"])
                                # st.dataframe(bucket_summary.reset_index(), use_container_width=True, hide_index=True)
                                # with st.popover("View raw per-ticker data"):
                                    # st.dataframe(
                                        # bt_df.sort_values("Tech Score (at cutoff)", ascending=False),
                                        # use_container_width=True, hide_index=True,
                                    # )
                                # st.caption(
                                    # "⚠️ This is a single historical sample from one universe/date, not a robust "
                                    # "walk-forward backtest — it doesn't account for survivorship bias (delisted "
                                    # "stocks aren't in yfinance), transaction costs, or multiple time periods. "
                                    # "Treat it as a sanity check, not a guarantee."
                                # )
                # ==========================================================================
                # END DISABLED — HISTORICAL VALIDATION (BACKTEST)
                # ==========================================================================
                st.divider()
                # TradingView Exporter
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
                # Screening Table
                st.subheader("📋 Screening Results Table")
                st.info("💡 Select a holding below or choose a symbol to inspect its detailed pillar breakdown.")
                display_table = df[[
                    "Ticker", "Total Score", "Fundamental Score",
                    "Technical Score", "Tech Passed", "CANSLIM Hits", "Sector"
                ]].copy()
                # ==========================================================================
                # DISABLED (commented out by request) — WATCHLIST STAR BUTTON
                # To re-enable: uncomment the 4-column layout below (and comment out the
                # plain 3-column line that currently replaces it), plus the c_ctrl4 block.
                # ==========================================================================
                # if SUPABASE_AVAILABLE:
                #     c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([2, 2, 1, 1])
                # else:
                #     c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])
                c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([2, 2, 1])
                # ==========================================================================
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
                        st.session_state["active_inspect_ticker"] = selected_ticker
                        st.rerun()
                # ==========================================================================
                # if SUPABASE_AVAILABLE:
                #     with c_ctrl4:
                #         _wl = st.session_state.get("watchlist_cache")
                #         if _wl is None:
                #             _wl = get_watchlist()
                #             st.session_state["watchlist_cache"] = _wl
                #         is_starred = selected_ticker in _wl
                #         if st.button("★ Unstar" if is_starred else "☆ Star", key="scr_star_btn", use_container_width=True):
                #             ok = remove_from_watchlist(selected_ticker) if is_starred else add_to_watchlist(selected_ticker)
                #             if ok:
                #                 st.session_state["watchlist_cache"] = None  # force refresh next render
                #                 st.rerun()
                #             else:
                #                 st.error("Couldn't update watchlist — has supabase_migration.sql been run?")
                # ==========================================================================
                # END DISABLED — WATCHLIST STAR BUTTON
                # ==========================================================================
                st.dataframe(
                    display_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                        "Total Score": st.column_config.NumberColumn(
                            "Total", format="%.2f", help="Weighted blend of Fund and Tech. Scaled if those two weights do not add to 10."
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
    # TAB 2: PORTFOLIO EVALUATOR

    # ==================================================================================
    with tab_portfolio:
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
                    st.session_state["active_inspect_ticker"] = p_selected_ticker
                    st.rerun()
            st.dataframe(
                p_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn("Symbol", pinned=True, width="medium"),
                    "Total Score": st.column_config.NumberColumn(
                        "Total", format="%.2f", help="Weighted blend of Fund and Tech. Scaled if those two weights do not add to 10."
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
    # TAB 3: USER GUIDE

    # ==================================================================================
    with tab_guide:
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
            * **Step A (Select Universe):** Pick a live source — **Nifty 50, Next 50, Midcap 150, Smallcap 250, Nifty 500, or F&O Stocks** — refreshed daily from NSE, or upload your own CSV/Excel file of stock symbols.
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
        st.markdown("#### **3. Pillar Settings & Weightage Adjustment**")
        st.markdown(
            """
            * **Adjust Weights:** Slide **Fundamental Weight** and **Technical Weight**. Total is a mix of those two scores (scaled if they do not add to 10). Leadership vs Nifty and sector is inside the fundamental score (L / Ls).
            * **Customize Rules:** Click **Fundamental Rules** or **Technical Rules** in the sidebar to toggle specific criteria on/off.
            * **Auto-Persistence:** Your customized weights and active rule parameters automatically save to Supabase and persist across future logins.
            * **Morning email:** Check **Email me weekday morning scores** in the sidebar. At 8:30 AM IST on weekdays the job emails (or writes) the highest-scoring stocks from each NSE index/group. Set **Number of stocks per group/index** for how many rows to include. Click **Generate preview digest** to try it now. This is a score ranking, not a stock pick.
            """
        )
        st.markdown("#### **4. Export to TradingView**")
        st.markdown(
            """
            * **Step A (Set Minimum Threshold):** Adjust the score slider (e.g., set to 7.0 or higher for top candidates).
            * **Step B (Copy Formatted Strings):** Click the copy icon in the formatted code snippet box (e.g., `NSE:TRENT,NSE:HAL,NSE:TATAMOTORS`).
            * **Step C (Import to TradingView):** Open TradingView -> Create New Watchlist -> Click **+ Add Symbol** -> Paste directly to add all stocks simultaneously.
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

                Total = (Fundamental × fund weight + Technical × tech weight) ÷ (fund + tech weights).
                """
            )

    # ==================================================================================
    # TAB 4: ADMIN PANEL (DYNAMIC ROLE-BASED)

    # ==================================================================================
    if user_is_admin and tab_admin is not None:
        with tab_admin:
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
                        # For F&O, identify which tier actually succeeded (bypassing the
                        # cache so this reflects the current live state, not yesterday's).
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
                user_list = []
            
                if supabase:
                    try:
                        # Retrieve all registered accounts directly from public.profiles table
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
