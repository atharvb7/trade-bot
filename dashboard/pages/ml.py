import json

import plotly.express as px
import streamlit as st
from common import run_page

from bot.analytics.funnel import calibration_table
from bot.analytics.loaders import RunData
from bot.config import ROOT


def render(rd: RunData, mode: str) -> None:
    st.title(f"ML analytics · {mode}")
    d = rd.decisions
    if d.empty or "ml_prob" not in d or d["ml_prob"].isna().all():
        st.info(
            "No ML scores yet — the ML model is built in Phase 4. Calibration, AUC/Brier over time, "
            "feature importance and drift will appear here."
        )
        return
    m = d.dropna(subset=["ml_prob"])
    cal = calibration_table(m["ml_prob"], m["label"])
    fig = px.line(
        cal, x="mean_prob", y="win_rate", markers=True, title="Calibration (ideal = diagonal)"
    )
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1, line_dash="dot")
    st.plotly_chart(fig, use_container_width=True)
    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score

        st.metric("AUC", f"{roc_auc_score(m['label'], m['ml_prob']):.3f}")
        st.metric("Brier", f"{brier_score_loss(m['label'], m['ml_prob']):.3f}")
    except Exception:
        st.caption("scikit-learn not installed yet.")
    for p in sorted((ROOT / "models").glob("*/meta.json"), reverse=True)[:1]:
        meta = json.loads(p.read_text())
        if "feature_importance" in meta:
            st.plotly_chart(
                px.bar(
                    x=list(meta["feature_importance"]),
                    y=list(meta["feature_importance"].values()),
                    title="Feature importance",
                ),
                use_container_width=True,
            )


run_page(render)
