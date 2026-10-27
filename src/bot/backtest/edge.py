"""Candidate-level edge: every tradeable candidate's forward outcome in R multiples.

Independent of the account-level caps (3 trades/day, losing streak), so it measures whether
the detector itself has an edge. 1R = distance from signal price to stop (the same distance
the risk manager sizes on, so net R x 1% of equity = the engine's rupee P&L for that trade).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.backtest.costs import CostModel

UNTRADEABLE = {"rejected_risk_outside_entry_window", "rejected_risk_kill_switch"}


def candidate_r(dec: pd.DataFrame, costs: CostModel) -> pd.DataFrame:
    """Adds gross_r (after slippage, before fees) and net_r (after fees) per candidate."""
    if dec.empty:
        return dec.assign(gross_r=[], net_r=[], fee_r=[])
    d = dec[~dec["final_status"].isin(UNTRADEABLE) & (dec["outcome"] != "no_entry")].copy()
    risk = (d["entry"] - d["stop"]).abs()
    if "hyp_entry_price" in d:  # fees on the simulated fill and exit, exactly as the engine
        entry_px, exit_px = d["hyp_entry_price"], d["hyp_exit_price"]
    else:  # older decision files: approximate both legs from the signal price
        sign = np.where(d["direction"] == "long", 1.0, -1.0)
        entry_px, exit_px = d["entry"], d["entry"] + sign * d["hyp_pnl_per_share"]
    fees = [
        costs.round_trip_fees(str(di), float(e), float(x))
        for di, e, x in zip(d["direction"], entry_px, exit_px, strict=True)
    ]
    d["fee_r"] = np.asarray(fees) / risk
    d["gross_r"] = d["hyp_pnl_per_share"] / risk
    d["net_r"] = d["gross_r"] - d["fee_r"]
    return d


def edge_summary(d: pd.DataFrame, reward_risk: float) -> dict[str, float]:
    if d.empty:
        return {"candidates": 0}
    return {
        "candidates": int(len(d)),
        "win_rate": float(d["label"].mean() * 100),
        "breakeven_win_rate": float(100 / (1 + reward_risk)),
        "mean_gross_r": float(d["gross_r"].mean()),
        "mean_fee_r": float(d["fee_r"].mean()),
        "mean_net_r": float(d["net_r"].mean()),
        "median_risk_pct": float(((d["entry"] - d["stop"]).abs() / d["entry"] * 100).median()),
    }


def day_bootstrap(df: pd.DataFrame, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """90% CI of mean net R, resampling whole trading days (needs decision_ts and net_r)."""
    if df.empty:
        return float("nan"), float("nan")
    g = df.groupby(df["decision_ts"].dt.normalize())["net_r"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))
