"""Decision-funnel and calibration helpers (pure functions, unit-tested)."""

from __future__ import annotations

import pandas as pd


def funnel(dec: pd.DataFrame) -> pd.DataFrame:
    """candidates -> passed ML -> passed Jev -> passed risk -> filled."""
    if dec.empty:
        return pd.DataFrame({"stage": [], "count": []})
    st = dec["final_status"].astype(str)
    gate = (
        dec["gate_failed"].astype(str)
        if "gate_failed" in dec
        else pd.Series("None", index=dec.index)
    )
    n = len(dec)
    fail_ml = int(((gate == "ml_prob") | (st == "rejected_ml")).sum())
    fail_jev = int((gate.str.startswith("jev") | (st == "rejected_jev")).sum())
    fail_risk = int(st.str.startswith("rejected_risk").sum())
    filled = int((st == "filled").sum())
    after_ml = n - fail_ml
    after_jev = after_ml - fail_jev
    return pd.DataFrame(
        {
            "stage": ["Candidates", "Passed ML", "Passed Jev", "Passed risk", "Filled"],
            "count": [n, after_ml, after_jev, after_jev - fail_risk, filled],
        }
    )


def rejection_reasons(dec: pd.DataFrame) -> pd.DataFrame:
    if dec.empty:
        return pd.DataFrame({"reason": [], "count": []})
    rej = dec[dec["final_status"].astype(str).str.startswith("rejected")]
    vc = (
        rej["final_status"]
        .str.replace("rejected_risk_", "risk: ")
        .str.replace("rejected_", "gate: ")
    )
    return vc.value_counts().rename_axis("reason").reset_index(name="count")


def calibration_table(prob: pd.Series, label: pd.Series, bins: int = 10) -> pd.DataFrame:
    """Predicted-probability bucket vs realised win rate."""
    ok = prob.notna() & label.notna()
    if not ok.any():
        return pd.DataFrame({"bucket": [], "mean_prob": [], "win_rate": [], "n": []})
    df = pd.DataFrame({"p": prob[ok].astype(float), "y": label[ok].astype(float)})
    df["bucket"] = (df["p"] * bins).clip(upper=bins - 1e-9).astype(int)  # 0..bins-1
    g = df.groupby("bucket").agg(mean_prob=("p", "mean"), win_rate=("y", "mean"), n=("y", "size"))
    g.insert(0, "bucket", [f"{b / bins:.1f}-{(b + 1) / bins:.1f}" for b in g.index])
    return g.reset_index(drop=True)
