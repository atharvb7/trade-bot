"""Trading bot dashboard. Run:  .venv/bin/streamlit run dashboard/app.py  (binds to localhost)."""

import streamlit as st

st.set_page_config(page_title="Trading Bot", layout="wide")
pages = [
    st.Page("pages/overview.py", title="Overview", default=True),
    st.Page("pages/trades.py", title="Trades"),
    st.Page("pages/funnel.py", title="Decision funnel"),
    st.Page("pages/jev.py", title="Jev analytics"),
    st.Page("pages/ml.py", title="ML analytics"),
    st.Page("pages/performance.py", title="Performance"),
    st.Page("pages/backtest_lab.py", title="Backtest lab"),
    st.Page("pages/logs.py", title="Logs and settings"),
]
st.navigation(pages).run()
