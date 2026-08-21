import streamlit as st
import pandas as pd
import yfinance as yf

# --- PAGE SETUP ---
st.set_page_config(page_title="Multi-Factor Equity Analyzer", layout="wide")

# --- 1. DEFAULT NSE 500 TICKER LOADING ---
@st.cache_data(ttl=86400)
def get_nse500_tickers():
    """Fetches official Nifty 500 symbol list from NSE archive."""
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        # User-Agent header helps avoid 403 request blocks from NSE server
        headers = {'User-Agent': 'Mozilla/5.0'}
        df = pd.read_csv(url, storage_options=headers)
        tickers = [f"{sym}.NS" for sym in df['Symbol'].dropna().unique()]
        return tickers
    except Exception:
        # Fallback list if network issue prevents downloading full CSV
        fallback = [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
            "INFY.NS", "ITC.NS", "SBIN.NS", "LTIM.NS", "LT.NS", "HINDUNILVR.NS",
            "AXISBANK.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "M&M.NS", "MARUTI.NS"
        ]
        return fallback

default_tickers = get_nse500_tickers()

# --- SIDEBAR & WEIGHT CONFIGURATION ---
st.sidebar.header("Configuration")

# Default weights: 4 (Fundamental), 4 (Technical), 2 (Relative Strength)
w_fund = st.sidebar.slider("Fundamental Weight", min_value=0.0, max_value=10.0, value=4.0, step=0.5)
w_tech = st.sidebar.slider("Technical Weight", min_value=0.0, max_value=10.0, value=4.0, step=0.5)
w_rs = st.sidebar.slider("Relative Strength Weight", min_value=0.0, max_value=10.0, value=2.0, step=0.5)

# Active Tickers selection (Defaults to full NSE500 list)
selected_tickers = st.sidebar.multiselect(
    "Active Tickers Universe",
    options=default_tickers,
    default=default_tickers
)

# --- ANALYSIS ENGINE ---
def analyze_ticker(ticker_symbol):
    """
    Fetches raw market data and calculates objective quantitative metrics.
    Returns (data_dict, error_message).
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="1y")
        
        # Check for missing feed or insufficient trading history
        if hist.empty or len(hist) < 50:
            return None, f"Insufficient price history/feed data for {ticker_symbol}"
        
        info = ticker.info
        if not info:
            return None, f"Fundamental info feed unavailable for {ticker_symbol}"

        # Objective Fundamental Metrics
        pe = info.get('forwardPE') or info.get('trailingPE') or 0
        roe = info.get('returnOnEquity') or 0
        profit_margins = info.get('profitMargins') or 0
        
        # Objective Technical Metrics
        current_price = hist['Close'].iloc[-1]
        sma_50 = hist['Close'].rolling(50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(200).mean().iloc[-1] if len(hist) >= 200 else sma_50
        
        # Objective Relative Strength Metric (1-Year Trailing Return)
        yr_return = (current_price - hist['Close'].iloc[0]) / hist['Close'].iloc[0]

        # Normalized scoring (0 to 10 scale)
        fund_score = min(10, max(0, (roe * 20) + (profit_margins * 20)))
        tech_score = 10 if (current_price > sma_50 > sma_200) else (5 if current_price > sma_50 else 2)
        rs_score = min(10, max(0, yr_return * 20))

        total_weight = w_fund + w_tech + w_rs
        composite_score = (
            (fund_score * w_fund) + 
            (tech_score * w_tech) + 
            (rs_score * w_rs)
        ) / total_weight if total_weight > 0 else 0

        details = {
            "Symbol": ticker_symbol,
            "Composite Score": round(composite_score, 2),
            "Price": round(current_price, 2),
            "Fundamental Score": round(fund_score, 2),
            "Technical Score": round(tech_score, 2),
            "RS Score": round(rs_score, 2),
            "P/E Ratio": round(pe, 2),
            "ROE": f"{round(roe * 100, 2)}%",
            "Profit Margin": f"{round(profit_margins * 100, 2)}%",
            "50-Day SMA": round(sma_50, 2),
            "200-Day SMA": round(sma_200, 2),
            "1-Yr Return": f"{round(yr_return * 100, 2)}%"
        }
        return details, None

    except Exception as e:
        return None, f"Data fetch failure for {ticker_symbol}: {str(e)}"

# --- MAIN EXECUTION ---
st.title("Multi-Factor Equity Analysis")

if st.button("Run Multi-Factor Analysis"):
    results = []
    skipped_errors = []
    
    progress_bar = st.progress(0)
    for idx, sym in enumerate(selected_tickers):
        res, error = analyze_ticker(sym)
        if res:
            results.append(res)
        if error:
            # Explicitly capture skipped tickers
            skipped_errors.append(error)
        progress_bar.progress((idx + 1) / len(selected_tickers))
    
    progress_bar.empty()

    # Display skipped symbols due to feed unavailability
    if skipped_errors:
        with st.expander(f"⚠️ Skipped {len(skipped_errors)} ticker(s) due to missing data feeds"):
            for err in skipped_errors:
                st.warning(err)

    if results:
        df_res = pd.DataFrame(results).sort_values(by="Composite Score", ascending=False)
        st.session_state['analysis_data'] = df_res

# --- RESULTS & POPUP BREAKDOWN ---
if 'analysis_data' in st.session_state and not st.session_state['analysis_data'].empty:
    df_results = st.session_state['analysis_data']

    # User Instruction Header
    st.markdown("### **Click on symbol to know more**")

    # Table Layout Headers
    cols = st.columns([2, 2, 2, 2, 3])
    cols[0].markdown("**Symbol**")
    cols[1].markdown("**Composite Score**")
    cols[2].markdown("**Price (₹)**")
    cols[3].markdown("**1-Yr Return**")
    cols[4].markdown("**Detailed Breakdown**")
    st.divider()

    # Table Rows
    for idx, row in df_results.iterrows():
        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 3])
        c1.write(row['Symbol'])
        c2.write(f"**{row['Composite Score']}** / 10")
        c3.write(str(row['Price']))
        c4.write(row['1-Yr Return'])
        
        # Interactive Popover Modal with Objective Data & Rule-Based Commentary
        with c5:
            with st.popover(f"Details: {row['Symbol']}"):
                st.subheader(f"Analysis Breakdown — {row['Symbol']}")
                
                # --- SECTION 1: QUALITATIVE COMMENTARY ---
                st.markdown("##### **Qualitative Assessment**")
                
                commentary = []
                # Fundamentals
                if row['Fundamental Score'] >= 7:
                    commentary.append("• **Fundamentals:** Strong profitability and capital efficiency based on current ROE and profit margins.")
                elif row['Fundamental Score'] >= 4:
                    commentary.append("• **Fundamentals:** Moderate fundamental metrics, reflecting steady operational performance.")
                else:
                    commentary.append("• **Fundamentals:** Subdued performance; return metrics or margins indicate underlying operational pressure.")
                    
                # Technicals
                if row['Technical Score'] >= 8:
                    commentary.append("• **Technicals:** Robust bullish momentum with price trading above key 50-day and 200-day moving averages.")
                elif row['Technical Score'] >= 5:
                    commentary.append("• **Technicals:** Neutral to mild bullish bias; price consolidating near medium-term moving averages.")
                else:
                    commentary.append("• **Technicals:** Weak momentum; price trading below major moving averages, suggesting short-term overhead pressure.")
                    
                # Relative Strength
                if row['RS Score'] >= 6:
                    commentary.append("• **Relative Strength:** Outperforming market benchmarks over the trailing 12-month period.")
                else:
                    commentary.append("• **Relative Strength:** Lagging broad market price action over a 1-year horizon.")
                
                for line in commentary:
                    st.write(line)
                
                # Statutory Disclaimer
                st.caption(
                    "⚠️ **Disclaimer:** This assessment is an automated, rule-based output generated strictly from public historical data and financial ratios. "
                    "It is provided exclusively for educational and informational purposes and does **not** constitute financial or investment advice."
                )
                
                st.divider()

                # --- SECTION 2: OBJECTIVE NUMERIC DATA ---
                st.markdown("##### **Quantitative Score Allocation**")
                st.json({
                    "Fundamental Score": row['Fundamental Score'],
                    "Technical Score": row['Technical Score'],
                    "Relative Strength Score": row['RS Score'],
                    "Composite Score": row['Composite Score']
                })
                
                st.markdown("##### **Raw Quantitative Metrics**")
                metric_df = pd.DataFrame({
                    "Metric": ["P/E Ratio", "ROE", "Profit Margin", "50-Day SMA", "200-Day SMA", "1-Yr Return"],
                    "Value": [row['P/E Ratio'], row['ROE'], row['Profit Margin'], row['50-Day SMA'], row['200-Day SMA'], row['1-Yr Return']]
                })
                st.dataframe(metric_df, hide_index=True, use_container_width=True)