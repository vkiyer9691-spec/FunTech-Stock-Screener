import streamlit as st
import pandas as pd
import pandas_ta as ta
import yfinance as yf

# ==========================================
# 1. AUTHENTICATION & ACCESS CONTROL
# ==========================================
def is_stocks_setting_up_authorized():
    """
    Replace this with your actual Supabase auth check. 
    For now, it defaults to True so you can test the UI immediately.
    """
    return True

# ==========================================
# 2. DATA FETCHING & UNIVERSE BUILDER
# ==========================================
@st.cache_data(ttl=3600)
def fetch_stock_data(ticker, period="1y"):
    """Fetches daily stock data from Yahoo Finance."""
    try:
        # Adding .NS for Indian stocks (NSE) if missing
        if not ticker.endswith('.NS') and not ticker.endswith('.BO'):
            ticker = ticker + '.NS'
            
        df = yf.download(ticker, period=period, progress=False)
        if df.empty:
            return None
        
        # Flatten multi-index columns if they exist
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        return df
    except Exception:
        return None

def get_universe_tickers(n_nifty, n_next50, n_smallcap):
    """
    This is where your ranking engine provides the strong baseline stocks.
    Using a sample list of strong Indian stocks for this working version.
    """
    sample_nifty = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS'][:n_nifty]
    sample_next50 = ['ZOMATO.NS', 'TRENT.NS', 'BEL.NS', 'HAL.NS', 'JINDALSTEL.NS'][:n_next50]
    sample_smallcap = ['BSE.NS', 'CDSL.NS', 'ANGELONE.NS', 'KALYANKJIL.NS', 'SUZLON.NS'][:n_smallcap]
    
    # Combine and remove duplicates
    universe = list(set(sample_nifty + sample_next50 + sample_smallcap))
    return universe

# ==========================================
# 3. THE 5-SETUP TECHNICAL ENGINE
# ==========================================
def check_setups(df):
    """
    Evaluates a single stock's dataframe against the 5 setups.
    Returns a list of tags for the setups that triggered.
    """
    # Need enough data to calculate 50-day moving averages and 40-day lookbacks
    if df is None or len(df) < 60:
        return []
        
    # -- PRE-CALCULATE INDICATORS --
    try:
        # Stochastic (14, 3, 3)
        stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=14, d=3, smooth_k=3)
        df['STOCH_K'] = stoch['STOCHk_14_3_3']
        df['STOCH_D'] = stoch['STOCHd_14_3_3']
        
        # MACD (12, 26, 9)
        macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
        df['MACD_Line'] = macd['MACD_12_26_9']
        
        # RSI (14)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        # Moving Averages & Volume
        df['EMA_20'] = ta.ema(df['Close'], length=20)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['Vol_20_SMA'] = ta.sma(df['Volume'], length=20)
    except:
        return [] # Skip if indicator calculation fails due to missing data
        
    # Get the latest row (today) and recent history
    today = df.iloc[-1]
    yest = df.iloc[-2]
    tags = []
    
    # ==========================================
    # SETUP 1: Multi-Timeframe Pullback
    # ==========================================
    macd_sloping_up = today['MACD_Line'] > yest['MACD_Line']
    recent_cross_below_60 = False
    
    for i in range(1, 4):
        curr_k = df['STOCH_K'].iloc[-i]
        curr_d = df['STOCH_D'].iloc[-i]
        prev_k = df['STOCH_K'].iloc[-(i+1)]
        prev_d = df['STOCH_D'].iloc[-(i+1)]
        
        if (prev_k < prev_d) and (curr_k > curr_d) and (curr_k < 60) and (curr_d < 60):
            recent_cross_below_60 = True
            break
            
    if macd_sloping_up and recent_cross_below_60:
        tags.append("✔️ Pullback")

    # ==========================================
    # SETUP 2: Breakout Retest (40-day Medium Term)
    # ==========================================
    lookback = 40
    resistance = df['High'].iloc[-lookback-5:-5].max() 
    recent_breakout = df.iloc[-5:]['Close'].max() > resistance
    
    resting_near_res = (resistance * 0.97) <= today['Close'] <= (resistance * 1.03)
    quiet_volume = today['Volume'] < today['Vol_20_SMA']
    
    if recent_breakout and resting_near_res and quiet_volume:
        tags.append("✔️ Breakout Retest")

    # ==========================================
    # SETUP 3: RSI Momentum Resumption
    # ==========================================
    rsi_hit_high = df['RSI'].iloc[-20:-5].max() >= 60
    rsi_cooled = df['RSI'].iloc[-5:-1].min() < 55
    rsi_curling_up = yest['RSI'] < 55 and today['RSI'] >= 55
    price_confirming = today['Close'] > yest['Close']
    
    if rsi_hit_high and rsi_cooled and rsi_curling_up and price_confirming:
        tags.append("✔️ RSI Resumption")

    # ==========================================
    # SETUP 4: Volatility Squeeze
    # ==========================================
    inside_day_1 = (yest['High'] < df.iloc[-3]['High']) and (yest['Low'] > df.iloc[-3]['Low'])
    inside_day_2 = (today['High'] < yest['High']) and (today['Low'] > yest['Low'])
    vol_dry_up = today['Volume'] < (today['Vol_20_SMA'] * 0.6)
    
    if inside_day_1 and inside_day_2 and vol_dry_up:
        tags.append("✔️ Vol Squeeze")

    # ==========================================
    # SETUP 5: 20-EMA Trend Bounce
    # ==========================================
    strong_trend = today['EMA_20'] > today['SMA_50']
    touched_ema = today['Low'] <= today['EMA_20'] and today['Close'] > today['EMA_20']
    
    daily_range = today['High'] - today['Low']
    closed_strong = today['Close'] > (today['Low'] + (daily_range * 0.5))
    
    if strong_trend and touched_ema and closed_strong:
        tags.append("✔️ 20-EMA Bounce")

    return tags

# ==========================================
# 4. STREAMLIT USER INTERFACE
# ==========================================
def stocks_setting_up_ui():
    if not is_stocks_setting_up_authorized():
        st.error("You are not authorized to view the Stocks Setting Up module.")
        return

    st.title("📈 Stocks Setting Up")
    st.markdown("Specify the Top 'N' stocks from your scoring engine to build the scan universe.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        n_nifty = st.number_input("Top Nifty 50", min_value=0, max_value=50, value=10)
    with col2:
        n_next50 = st.number_input("Top Next 50", min_value=0, max_value=50, value=15)
    with col3:
        n_smallcap = st.number_input("Top Smallcap 250", min_value=0, max_value=250, value=25)
        
    st.divider()

    if st.button("Run Setup Scan", type="primary"):
        universe_tickers = get_universe_tickers(n_nifty, n_next50, n_smallcap)
        
        if not universe_tickers:
            st.warning("No tickers selected for the universe.")
            return
            
        st.write(f"Scanning **{len(universe_tickers)}** top-ranked stocks for technical setups...")
        
        progress_bar = st.progress(0)
        results = []
        
        for i, ticker in enumerate(universe_tickers):
            df = fetch_stock_data(ticker)
            triggered_tags = check_setups(df)
            
            if triggered_tags:
                results.append({
                    "Ticker": ticker.replace('.NS', ''),
                    "LTP": round(df['Close'].iloc[-1], 2),
                    "Setups Triggered": " | ".join(triggered_tags)
                })
                
            progress_bar.progress((i + 1) / len(universe_tickers))
            
        st.success("Scan Complete!")
        
        if results:
            results_df = pd.DataFrame(results)
            st.dataframe(results_df, use_container_width=True, hide_index=True)
        else:
            st.info("No stocks in the selected universe triggered a setup today.")

# ==========================================
# 5. MAIN APPLICATION LAUNCHER
# ==========================================
def main():
    st.set_page_config(page_title="Market Dashboard", layout="wide")
    
    # Example of a multi-tab layout where your old features could live alongside the new one
    tab1, tab2 = st.tabs(["Dashboard", "Stocks Setting Up"])
    
    with tab1:
        st.header("Welcome to the Trading Dashboard")
        st.write("Your original app content can go here in the future.")
        
    with tab2:
        stocks_setting_up_ui()

if __name__ == "__main__":
    main()