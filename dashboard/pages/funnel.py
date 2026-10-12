import plotly.graph_objects as go
import streamlit as st
from common import run_page

from bot.analytics.funnel import funnel, rejection_reasons
from bot.analytics.loaders import RunData


def render(rd: RunData, mode: str) -> None:
    st.title(f"Decision funnel · {mode}")
    d = rd.decisions
    if d.empty:
        st.info("No decisions in this range.")
        return
    f = funnel(d)
    st.plotly_chart(go.Figure(go.Funnel(y=f["stage"], x=f["count"])), use_container_width=True)
    st.subheader("Top rejection reasons")
    st.dataframe(rejection_reasons(d), use_container_width=True)
    st.subheader("Rejected candidates and what would have happened")
    rej = d[d["final_status"].astype(str).str.startswith("rejected")]
    cols = [
        c
        for c in [
            "ts",
            "symbol",
            "setup",
            "direction",
            "final_status",
            "outcome",
            "label",
            "hyp_pnl_per_share",
        ]
        if c in rej
    ]
    st.dataframe(rej[cols].round(3), use_container_width=True)
    if "label" in rej and len(rej):
        st.caption(
            f"Rejected candidates that would have hit target: {rej['label'].mean() * 100:.1f}% (before fees)."
        )


run_page(render)
