import plotly.express as px
import streamlit as st
from common import run_page

from bot.analytics.funnel import calibration_table
from bot.analytics.loaders import RunData


def render(rd: RunData, mode: str) -> None:
    st.title(f"Jev analytics · {mode}")
    d = rd.decisions
    if d.empty or "jev_confidence" not in d or d["jev_confidence"].isna().all():
        st.info(
            "No Jev data yet — the Jev layer is built in Phase 5. This page fills in automatically "
            "(calibration, agree-vs-veto outcomes, score distributions, latency, errors, model versions)."
        )
        return
    j = d.dropna(subset=["jev_confidence"])
    cal = calibration_table(j["jev_confidence"], j["label"])
    st.plotly_chart(
        px.line(
            cal,
            x="mean_prob",
            y="win_rate",
            markers=True,
            title="Jev confidence vs realised win rate",
        ),
        use_container_width=True,
    )
    if "jev_action" in j:
        j = j.assign(agreed=j["jev_action"] == j["direction"])
        st.dataframe(j.groupby("agreed")["label"].agg(["count", "mean"]), use_container_width=True)
    for col in ("jev_quality", "jev_trap", "jev_latency_ms"):
        if col in j:
            st.plotly_chart(px.histogram(j, x=col, title=col), use_container_width=True)
    if "jev_model_version" in j:
        st.write("Model versions seen:", sorted(j["jev_model_version"].dropna().unique()))
    if "jev_error" in j:
        st.write("Errors/timeouts:", int(j["jev_error"].notna().sum()))


run_page(render)
