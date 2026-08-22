import streamlit as st
import pandas as pd
import numpy as np

# Set page configuration
st.set_page_config(
    page_title="Quantitative Multi-Pillar Engine",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS styling
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .stButton>button {
        width: 100%;
        border-radius: 6px;
    }
    .metric-card {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        padding: 12px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# APPLICATION HEADER
# -----------------------------------------------------------------------------
st.title("Quantitative Multi-Pillar Engine for Stock Market Traders and Investors")

# -----------------------------------------------------------------------------
# DIALOG FOR DETAILED PILLAR BREAKDOWN
# -----------------------------------------------------------------------------
@st.dialog("Detailed Multi-Pillar Score Breakdown")
def show_pillar_details(symbol: str, row_data: pd.Series):
    """
    Displays a comprehensive breakdown of the pillar metrics when a stock 
    symbol button is clicked in the screener results.
    """
    st.subheader(f"Pillar Breakdown: {symbol}")
    
    # Top-level score metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Overall Score", f"{row_data.get('Overall_Score', 0)}/100")
    with col2:
        st.metric("Momentum Score", f"{row_data.get('Momentum_Score', 0)}/100")
    with col3:
        st.metric("Quality Score", f"{row_data.get('Quality_Score', 0)}/100")
    with col4:
        st.metric("Valuation Score", f"{row_data.get('Valuation_Score', 0)}/100")
        
    st.divider()
    
    # Pillar Details Accordion
    with st.expander("⚡ Momentum & Technical Pillar", expanded=True):
        p_col1, p_col2 = st.columns(2)
        with p_col1:
            st.write(f"- **RSI (14-Period):** {row_data.get('RSI_14', 'N/A')}")
            st.write(f"- **EMA Trend Alignment:** {row_data.get('EMA_Status', 'Aligned')}")
        with p_col2:
            st.write(f"- **Relative Strength vs Nifty:** {row_data.get('RS_Score', 'N/A')}")
            st.write(f"- **Distance from 52W High:** {row_data.get('Dist_52W_High', 'N/A')}%")
            
    with st.expander("🛡️ Fundamental & Quality Pillar"):
        q_col1, q_col2 = st.columns(2)
        with q_col1:
            st.write(f"- **Return on Equity (ROE):** {row_data.get('ROE', 'N/A')}%")
            st.write(f"- **Return on Capital Employed (ROCE):** {row_data.get('ROCE', 'N/A')}%")
        with q_col2:
            st.write(f"- **Debt to Equity Ratio:** {row_data.get('Debt_Equity', 'N/A')}")
            st.write(f"- **Promoter Holding:** {row_data.get('Promoter_Hold', 'N/A')}%")
            
    with st.expander("🚀 Growth Pillar"):
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            st.write(f"- **Sales Growth (YoY):** {row_data.get('Sales_Growth', 'N/A')}%")
        with g_col2:
            st.write(f"- **Profit Growth (YoY):** {row_data.get('Profit_Growth', 'N/A')}%")

    with st.expander("💰 Valuation & Risk Pillar"):
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            st.write(f"- **Current P/E Ratio:** {row_data.get('PE_Ratio', 'N/A')}")
        with v_col2:
            st.write(f"- **5-Year Historical Median P/E:** {row_data.get('PE_Median', 'N/A')}")

# -----------------------------------------------------------------------------
# SAMPLE DATA GENERATOR
# -----------------------------------------------------------------------------
def get_sample_screener_data():
    return pd.DataFrame([
        {
            "Symbol": "TATASTEEL", "LTP": 154.20, "Overall_Score": 88, "Momentum_Score": 92, 
            "Quality_Score": 85, "Valuation_Score": 80, "RSI_14": 68.5, "EMA_Status": "Bullish Stack",
            "RS_Score": "+12.4%", "Dist_52W_High": "-2.1%", "ROE": 18.5, "ROCE": 21.2, 
            "Debt_Equity": 0.45, "Promoter_Hold": 33.9, "Sales_Growth": 14.2, "Profit_Growth": 18.6,
            "PE_Ratio": 14.5, "PE_Median": 16.2
        },
        {
            "Symbol": "RELIANCE", "LTP": 2890.50, "Overall_Score": 82, "Momentum_Score": 79, 
            "Quality_Score": 88, "Valuation_Score": 75, "RSI_14": 59.2, "EMA_Status": "Bullish Stack",
            "RS_Score": "+6.1%", "Dist_52W_High": "-4.8%", "ROE": 14.2, "ROCE": 12.8, 
            "Debt_Equity": 0.38, "Promoter_Hold": 50.4, "Sales_Growth": 11.5, "Profit_Growth": 12.1,
            "PE_Ratio": 26.1, "PE_Median": 25.0
        },
        {
            "Symbol": "INFY", "LTP": 1610.00, "Overall_Score": 74, "Momentum_Score": 65, 
            "Quality_Score": 91, "Valuation_Score": 68, "RSI_14": 48.0, "EMA_Status": "Neutral/Sideways",
            "RS_Score": "-1.2%", "Dist_52W_High": "-11.5%", "ROE": 29.1, "ROCE": 36.4, 
            "Debt_Equity": 0.08, "Promoter_Hold": 14.8, "Sales_Growth": 8.1, "Profit_Growth": 9.4,
            "PE_Ratio": 24.3, "PE_Median": 23.5
        },
        {
            "Symbol": "ICICIBANK", "LTP": 1245.80, "Overall_Score": 91, "Momentum_Score": 95, 
            "Quality_Score": 90, "Valuation_Score": 86, "RSI_14": 72.1, "EMA_Status": "Strong Bullish",
            "RS_Score": "+15.8%", "Dist_52W_High": "-0.5%", "ROE": 17.8, "ROCE": 18.1, 
            "Debt_Equity": 0.85, "Promoter_Hold": 0.0, "Sales_Growth": 19.5, "Profit_Growth": 22.3,
            "PE_Ratio": 17.2, "PE_Median": 19.0
        }
    ])

# -----------------------------------------------------------------------------
# TAB NAVIGATION
# -----------------------------------------------------------------------------
tab_screener, tab_portfolio, tab_guide = st.tabs([
    "🔍 Multi-Pillar Screener", 
    "💼 Portfolio Evaluator", 
    "📖 Application Overview & User Guide"
])

# -----------------------------------------------------------------------------
# TAB 1: MULTI-PILLAR SCREENER
# -----------------------------------------------------------------------------
with tab_screener:
    st.subheader("Stock Market Screener")
    
    # Filter Controls
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        selected_universe = st.selectbox("Select Stock Universe", ["Nifty 50", "Nifty 500", "F&O Stocks", "Custom List"])
    with col_f2:
        min_score = st.slider("Minimum Overall Score Threshold", 0, 100, 70)
    with col_f3:
        sort_by = st.selectbox("Sort Results By", ["Overall_Score", "Momentum_Score", "Quality_Score", "Valuation_Score"])

    df_screener = get_sample_screener_data()
    filtered_df = df_screener[df_screener["Overall_Score"] >= min_score].sort_values(by=sort_by, ascending=False)
    
    st.divider()
    st.write(f"**Screened Results ({len(filtered_df)} Matches)** — *Click on any stock symbol button to inspect detailed pillar breakdown.*")
    
    # Table Header Rendering
    header_cols = st.columns([2.5, 2, 2, 2, 2, 2.5])
    header_cols[0].write("**Symbol (Click to Inspect)**")
    header_cols[1].write("**LTP (₹)**")
    header_cols[2].write("**Overall Score**")
    header_cols[3].write("**Momentum**")
    header_cols[4].write("**Quality**")
    header_cols[5].write("**Action**")
    
    st.markdown("<hr style='margin: 0.5rem 0;'/>", unsafe_allow_html=True)
    
    # Interactive Table Rows
    for idx, row in filtered_df.iterrows():
        r_cols = st.columns([2.5, 2, 2, 2, 2, 2.5])
        
        # Clickable Symbol Button
        if r_cols[0].button(f"🔍 {row['Symbol']}", key=f"sym_btn_{row['Symbol']}_{idx}"):
            show_pillar_details(row["Symbol"], row)
            
        r_cols[1].write(f"₹{row['LTP']:,.2f}")
        r_cols[2].write(f"**{row['Overall_Score']}** / 100")
        r_cols[3].write(f"{row['Momentum_Score']}")
        r_cols[4].write(f"{row['Quality_Score']}")
        
        if r_cols[5].button("Inspect Pillars", key=f"action_btn_{row['Symbol']}_{idx}"):
            show_pillar_details(row["Symbol"], row)

# -----------------------------------------------------------------------------
# TAB 2: PORTFOLIO EVALUATOR
# -----------------------------------------------------------------------------
with tab_portfolio:
    st.subheader("Portfolio Health & Multi-Pillar Evaluator")
    
    st.info("Upload your existing holdings or input position metrics to assess portfolio momentum, sector risk, and weak-link score degradation.")
    
    # Portfolio Table Setup
    sample_portfolio = pd.DataFrame([
        {"Symbol": "RELIANCE", "Qty": 50, "Buy Price": 2750.00, "Current Price": 2890.50, "Overall Score": 82, "Status": "STRONG HOLD"},
        {"Symbol": "INFY", "Qty": 100, "Buy Price": 1680.00, "Current Price": 1610.00, "Overall Score": 74, "Status": "HOLD / NEUTRAL"},
        {"Symbol": "TATASTEEL", "Qty": 300, "Buy Price": 135.00, "Current Price": 154.20, "Overall Score": 88, "Status": "STRONG HOLD"}
    ])
    
    st.dataframe(sample_portfolio, use_container_width=True)
    
    st.markdown("### Portfolio Metrics & Health Checks")
    p_c1, p_c2, p_c3 = st.columns(3)
    p_c1.metric("Average Portfolio Pillar Score", "81.3 / 100", delta="+3.2 pts vs benchmark")
    p_c2.metric("Momentum Alignment", "85% Bullish", delta="2 Positions Aligned")
    p_c3.metric("Weak Link Risk", "0 Stocks Low Score", delta="Healthy")

# -----------------------------------------------------------------------------
# TAB 3: EXPANDED APPLICATION OVERVIEW & USER GUIDE
# -----------------------------------------------------------------------------
with tab_guide:
    st.header("📖 Application Overview & User Guide")
    
    st.markdown("""
    Welcome to the **Quantitative Multi-Pillar Engine for Stock Market Traders and Investors**. 
    This application combines quantitative multi-factor modeling with technical scanning to help market participants filter high-probability equity setups, eliminate cognitive bias, and perform comprehensive portfolio diagnostics.
    """)
    
    st.divider()
    
    with st.expander("🎯 1. Multi-Pillar Engine Core Scoring Framework", expanded=True):
        st.markdown("""
        The engine uses a quantitative screening model to evaluate every stock across five foundational pillars:
        
        * **1. Momentum & Relative Strength Pillar:**
          * Evaluates price trend momentum, multi-timeframe RSI (14-period daily and weekly), and relative performance compared to major indices (e.g., Nifty 50).
        * **2. Technical Trend Alignment Pillar:**
          * Validates moving average stacked configurations (20 EMA > 50 EMA > 200 EMA), proximity to 52-week highs, and structural breakouts.
        * **3. Fundamental Quality Pillar:**
          * Filters for business quality metrics including Return on Equity (ROE), Return on Capital Employed (ROCE), debt sustainability (Debt-to-Equity < 1.0), and promoter pledge risks.
        * **4. Earnings Growth Expansion Pillar:**
          * Evaluates sales and net profit growth trajectories across quarter-over-quarter (QoQ) and year-over-year (YoY) periods.
        * **5. Valuation & Margin of Safety Pillar:**
          * Measures current valuation multiples (Price-to-Earnings, Price-to-Book) relative to the stock's 5-year historical median valuation.
        """)

    with st.expander("🔍 2. How to Use the Stock Market Screener"):
        st.markdown("""
        Follow these steps to generate actionable trading and investment ideas:
        
        1. **Select Equity Universe:** Choose your universe (Nifty 50, Nifty 500, F&O list, or Custom Watchlist) in the sidebar or top filter menu.
        2. **Set Minimum Score Thresholds:** Adjust the overall score slider to eliminate weak or underperforming stocks (e.g., minimum score of 70/100).
        3. **Run Screener:** The model executes mathematical filters across technical and fundamental data feeds.
        4. **Drill Down into Pillar Scores:** Click directly on any **Stock Symbol Button** (e.g., `🔍 TATASTEEL`) or the **Inspect Pillars** button in the results table. This opens an interactive view revealing the complete parameter breakdowns for that specific stock.
        5. **Export & Track:** Export filtered candidates to CSV for order placement or chart visualization.
        """)

    with st.expander("💼 3. How to Use the Portfolio Evaluator"):
        st.markdown("""
        Keep your active holdings aligned with changing market dynamics:
        
        1. **Load Positions:** Import your holdings file or input your active portfolio positions.
        2. **Health Check Diagnostics:** Review the weighted portfolio score, sector concentration levels, and momentum status.
        3. **Identify Score Degradation (Weak Links):** The evaluator highlights stocks whose multi-pillar score has dropped below acceptable limits (e.g., overall score under 50).
        4. **Execute Rebalancing:** Utilize engine recommendations to prune laggards showing deteriorating momentum/fundamentals and reallocate capital into top-ranked breakout candidates.
        """)