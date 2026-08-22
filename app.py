"""
NSE Stock Screener & Portfolio Evaluator
----------------------------------------
Features:
- Supabase Authentication (Sign In, Sign Up, Password Reset)
- Per-User Settings Persistence (Isolated weights & rule toggles in database)
- Conditional Administrator Access & Management Tab
- Multi-Pillar Scoring (Fundamental, Technical, Relative Strength)

Run locally: streamlit run app.py
"""

import numpy as np

# Compatibility patch for pandas_ta on newer numpy versions
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import os
import json
import pandas as pd
import streamlit as st
import yfinance as yf
from supabase import create_client, Client

# ----------------------------------------------------------------------------------
# Page Config & Custom Styling
# ----------------------------------------------------------------------------------
st.set_page_config(
    page_title="NSE Stock Screener & Portfolio Evaluator",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    div[data-testid="stMetricValue"] { font-weight: 600; }
    button[data-testid="stBaseButton-popover"] {
        padding-top: 0.15rem;
        padding-bottom: 0.15rem;
        font-weight: 600;
        width: 100% !important;
    }
    .stock-card {
        background-color: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------------
# Supabase Backend Setup
# ----------------------------------------------------------------------------------
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Missing Supabase credentials in Streamlit secrets (.streamlit/secrets.toml).")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ⚠️ UPDATE THIS LIST WITH YOUR ACTUAL EMAIL ADDRESS TO UNLOCK ADMIN CONTROLS
ADMIN_EMAILS = ["your_actual_email@domain.com"]

# ----------------------------------------------------------------------------------
# Default Criteria Rules Setup
# ----------------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------------
# Database Storage Functions (Per-User Persistence)
# ----------------------------------------------------------------------------------
def load_user_settings_from_db(user_id: str):
    """Loads settings specifically for the logged-in user from Supabase."""
    try:
        res = supabase.table("user_settings").select("settings").eq("user_id", user_id).execute()
        if res.data and len(res.data) > 0:
            saved_cfg = res.data[0].get("settings", {})
        else:
            saved_cfg = {}
    except Exception:
        saved_cfg = {}

    st.session_state["slider_fund"] = saved_cfg.get("slider_fund", 4)
    st.session_state["slider_tech"] = saved_cfg.get("slider_tech", 4)

    for p_key in DEFAULT_FUND_PARAMS:
        st.session_state[f"fund_{p_key}"] = saved_cfg.get(f"fund_{p_key}", True)

    for p_key in DEFAULT_TECH_PARAMS:
        st.session_state[f"tech_{p_key}"] = saved_cfg.get(f"tech_{p_key}", True)

    for p_key in DEFAULT_RS_PARAMS:
        st.session_state[f"rs_{p_key}"] = saved_cfg.get(f"rs_{p_key}", True)

def save_user_settings_to_db():
    """Saves active state into Supabase for the logged-in user."""
    user = st.session_state.get("user")
    if not user:
        return

    config_data = {
        "slider_fund": st.session_state.get("slider_fund", 4),
        "slider_tech": st.session_state.get("slider_tech", 4),
    }
    for k in DEFAULT_FUND_PARAMS:
        config_data[f"fund_{k}"] = st.session_state.get(f"fund_{k}", True)
    for k in DEFAULT_TECH_PARAMS:
        config_data[f"tech_{k}"] = st.session_state.get(f"tech_{k}", True)
    for k in DEFAULT_RS_PARAMS:
        config_data[f"rs_{k}"] = st.session_state.get(f"rs_{k}", True)

    try:
        supabase.table("user_settings").upsert({
            "user_id": user.id,
            "settings": config_data
        }).execute()
    except Exception as e:
        st.error(f"Error saving user settings to cloud: {e}")

# ----------------------------------------------------------------------------------
# Authentication Flow
# ----------------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state["user"] = None

def render_login_ui():
    st.title("🔐 NSE Stock Screener — User Portal")
    
    tab_login, tab_signup, tab_reset = st.tabs(["🔑 Sign In", "📝 Sign Up", "📩 Forgot Password"])
    
    with tab_login:
        with st.form("form_login"):
            email = st.text_input("Email Address")
            password = st.text_input("Password", type="password")
            btn_login = st.form_submit_button("Sign In", use_container_width=True)
            
            if btn_login:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state["user"] = res.user
                    load_user_settings_from_db(res.user.id)
                    st.success("Logged in successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_signup:
        with st.form("form_signup"):
            new_email = st.text_input("Email Address")
            new_pass = st.text_input("Choose Password", type="password")
            btn_signup = st.form_submit_button("Create Account", use_container_width=True)
            
            if btn_signup:
                try:
                    res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                    st.success("Account created successfully! You may now log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")

    with tab_reset:
        with st.form("form_reset"):
            reset_email = st.text_input("Registered Email Address")
            btn_reset = st.form_submit_button("Send Password Reset Link", use_container_width=True)
            
            if btn_reset:
                try:
                    supabase.auth.reset_password_for_email(reset_email)
                    st.success("Password reset instructions have been sent to your email.")
                except Exception as e:
                    st.error(f"Request failed: {e}")

if st.session_state["user"] is None:
    render_login_ui()
    st.stop()

# ----------------------------------------------------------------------------------
# Authenticated Main App Header
# ----------------------------------------------------------------------------------
current_user = st.session_state["user"]
user_email = current_user.email
is_admin = user_email in ADMIN_EMAILS

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("📊 NSE Stock Screener & Portfolio Evaluator")
    st.caption(f"Logged in as: **{user_email}** {'(Administrator)' if is_admin else ''}")
with col_h2:
    if st.button("🚪 Log Out", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state["user"] = None
        st.rerun()

# ----------------------------------------------------------------------------------
# Rule Configuration Modals
# ----------------------------------------------------------------------------------
@st.dialog("⚙️ Customize Fundamental Parameters")
def customize_fundamental_modal():
    st.write("Select criteria to include in Fundamental Score:")
    current_states = {}
    for k, label in DEFAULT_FUND_PARAMS.items():
        current_states[k] = st.checkbox(label, value=st.session_state.get(f"fund_{k}", True), key=f"modal_chk_fund_{k}")
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="btn_reset_fund", use_container_width=True):
        for k in DEFAULT_FUND_PARAMS:
            st.session_state[f"fund_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="btn_apply_fund", use_container_width=True):
        for k, v in current_states.items():
            st.session_state[f"fund_{k}"] = v
        save_user_settings_to_db()
        st.rerun()

@st.dialog("⚙️ Customize Technical Parameters")
def customize_technical_modal():
    st.write("Select rules to include in Technical Score:")
    current_states = {}
    for k, label in DEFAULT_TECH_PARAMS.items():
        current_states[k] = st.checkbox(label, value=st.session_state.get(f"tech_{k}", True), key=f"modal_chk_tech_{k}")
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="btn_reset_tech", use_container_width=True):
        for k in DEFAULT_TECH_PARAMS:
            st.session_state[f"tech_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="btn_apply_tech", use_container_width=True):
        for k, v in current_states.items():
            st.session_state[f"tech_{k}"] = v
        save_user_settings_to_db()
        st.rerun()

@st.dialog("⚙️ Customize Relative Strength Parameters")
def customize_rs_modal():
    st.write("Select relative strength benchmarks to include:")
    current_states = {}
    for k, label in DEFAULT_RS_PARAMS.items():
        current_states[k] = st.checkbox(label, value=st.session_state.get(f"rs_{k}", True), key=f"modal_chk_rs_{k}")
    col1, col2 = st.columns([1, 1])
    if col1.button("Restore Defaults", key="btn_reset_rs", use_container_width=True):
        for k in DEFAULT_RS_PARAMS:
            st.session_state[f"rs_{k}"] = True
        save_user_settings_to_db()
        st.rerun()
    if col2.button("Apply & Save", key="btn_apply_rs", use_container_width=True):
        for k, v in current_states.items():
            st.session_state[f"rs_{k}"] = v
        save_user_settings_to_db()
        st.rerun()

# ----------------------------------------------------------------------------------
# Sidebar Controls & Weight Adjustments
# ----------------------------------------------------------------------------------
st.sidebar.header("⚙️ Engine Controls")
st.sidebar.subheader("1. Pillar Weights (Sum to 10)")

def update_fund_weight():
    st.session_state["slider_fund"] = st.session_state["_fund_slider_input"]
    save_user_settings_to_db()

def update_tech_weight():
    st.session_state["slider_tech"] = st.session_state["_tech_slider_input"]
    save_user_settings_to_db()

w_fund = st.sidebar.slider(
    "Fundamental Weight", 0, 10, value=st.session_state.get("slider_fund", 4), 
    key="_fund_slider_input", on_change=update_fund_weight
)

w_tech = st.sidebar.slider(
    "Technical Weight", 0, 10, value=st.session_state.get("slider_tech", 4), 
    key="_tech_slider_input", on_change=update_tech_weight
)

w_rs = max(0, 10 - w_fund - w_tech)
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
# Main Navigation Tabs (Includes Conditional Admin Tab)
# ----------------------------------------------------------------------------------
tab_list = ["🔍 Stock Screener", "💼 Portfolio Evaluator", "ℹ️ How It Works & Guide"]
if is_admin:
    tab_list.append("🔒 Admin Panel")

tabs = st.tabs(tab_list)

with tabs[0]:
    st.subheader("Stock Screener Engine")
    st.info("Adjust pillar weights on the sidebar. Changes are saved automatically to your profile.")

with tabs[1]:
    st.subheader("Portfolio Evaluator")
    st.write("Upload broker CSV files to score existing holdings.")

with tabs[2]:
    st.subheader("Methodology & User Guide")
    st.write("Detailed explanation of CANSLIM scoring, RSI indicators, and Relative Strength calculation.")

if is_admin:
    with tabs[3]:
        st.subheader("🔒 Administrator Management Panel")
        st.success("Welcome, Administrator!")
        st.write("You have exclusive administrative rights to manage user configurations and platform access.")
        
        st.markdown("##### **Co-Administrator Management**")
        st.write("To designate additional administrators, update the `ADMIN_EMAILS` python list in `app.py`:")
        st.code(f"ADMIN_EMAILS = {json.dumps(ADMIN_EMAILS)}", language="python")