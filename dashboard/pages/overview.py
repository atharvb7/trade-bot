import json

import pandas as pd
import streamlit as st
from common import KILL_FLAG, empty, run_page

from bot.analytics.loaders import RunData
from bot.config import ROOT, load_config
from bot.risk.kill_switch import is_killed

STATUS_FILE = ROOT / "data" / "status.json"  # written by the runner (Phase 7)


def render(rd: RunData, mode: str) -> None:
    st.title(f"Overview · {mode}")
    if empty(rd):
        st.info(f"No {mode} data yet.")
    eq = rd.equity
    equity = float(eq["equity"].iloc[-1]) if len(eq) else rd.start_capital
    t = rd.trades
    today = pd.to_datetime(t["exit_ts"]).dt.date.max() if len(t) else None
    td = t[pd.to_datetime(t["exit_ts"]).dt.date == today] if today else t
    c = st.columns(4)
    c[0].metric("Equity (₹)", f"{equity:,.2f}", f"{equity - rd.start_capital:+,.2f}")
    c[1].metric("Last day gross P&L", f"{td['gross_pnl'].sum():+,.2f}" if len(td) else "–")
    c[2].metric(
        "Last day net P&L (after costs)", f"{td['net_pnl'].sum():+,.2f}" if len(td) else "–"
    )
    c[3].metric("Trades (range)", len(t))

    limit = load_config().risk.max_daily_loss_pct / 100 * rd.start_capital
    used = max(0.0, -float(td["net_pnl"].sum())) if len(td) else 0.0
    st.progress(
        min(used / limit, 1.0) if limit else 0.0,
        text=f"Daily loss used: ₹{used:.2f} of ₹{limit:.2f} limit",
    )

    st.subheader("Open position")
    st.caption(
        "Live P&L for open positions comes from broker/paper state (Phase 7). "
        "Backtests close all positions by 15:10."
    )
    st.subheader("Bot status")
    if STATUS_FILE.exists():
        s = json.loads(STATUS_FILE.read_text())
        st.json(s)
    else:
        st.write(
            "Runner not active (no `data/status.json`). Mode, feed health, last bar time and "
            "Jev/broker latency appear here when it runs."
        )

    st.subheader("Kill switch")
    st.write("Status: " + ("🛑 **ENGAGED**" if is_killed(KILL_FLAG) else "armed (not engaged)"))
    with st.form("kill"):
        sure = st.checkbox("I confirm: flatten all positions and stop the bot")
        if st.form_submit_button("ENGAGE KILL SWITCH") and sure:
            KILL_FLAG.write_text("kill")
            st.error("Kill flag written. The runner will flatten and stop.")
    if is_killed(KILL_FLAG) and st.button("Clear kill flag"):
        KILL_FLAG.unlink()
        st.rerun()


run_page(render)
