import subprocess
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bot.analytics.loaders import list_runs, load_run
from bot.config import ROOT

st.title("Backtest lab")
runs = list_runs()
with st.expander("Launch a new backtest"):
    c = st.columns(3)
    synth = c[0].checkbox(
        "Synthetic data",
        value=not (ROOT / "data" / "parquet").exists()
        or not any((ROOT / "data" / "parquet").iterdir()),
    )
    mode = c[1].selectbox("Decision mode", ["rules_only", "rules_ml", "rules_ml_jev"])
    edge = c[2].number_input(
        "Min-edge multiple override (blank = config)", value=-1.0, help="-1 keeps the config value"
    )
    if st.button("Run"):
        cmd = [sys.executable, str(ROOT / "scripts" / "run_backtest.py"), "--mode", mode]
        if synth:
            cmd.append("--synthetic")
        if edge >= 0:
            cmd += ["--min-edge", str(edge)]
        with st.spinner("Running..."):
            out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        st.code(out.stdout[-3000:] or out.stderr[-3000:])
        st.rerun() if out.returncode == 0 else None

if not runs:
    st.info("No saved runs yet.")
    st.stop()
picked = st.multiselect("Compare runs", runs, default=runs[:1])
data = {r: load_run(r) for r in picked}
if data:
    fig = go.Figure()
    for r, rd in data.items():
        if len(rd.trades):
            s = rd.trades.sort_values("exit_ts")
            fig.add_scatter(x=s["exit_ts"], y=rd.start_capital + s["net_pnl"].cumsum(), name=r)
    fig.update_layout(title="Equity curves (net of costs)")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        pd.DataFrame({r: rd.metrics for r, rd in data.items()}).round(3), use_container_width=True
    )
    for r, rd in data.items():
        if rd.folds is not None:
            st.subheader(f"Walk-forward folds · {r}")
            st.dataframe(rd.folds, use_container_width=True)
