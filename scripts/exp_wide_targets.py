"""Experiment: setups with wider stops (~0.7-1%) so costs are a small fraction of risk.

Protocol (fixed before running; docs/experiments/2026-10-12-wide-targets.md):
  * 6 pre-registered variants on 15-minute bars, spec risk rules unchanged.
  * Selection window 2025-10-17 .. 2026-07-31: choose by mean net R per candidate
    (>= 100 candidates), confirmed by the backtest.
  * Holdout 2026-08-01 .. end: chosen variant + V1 baseline, run once.
Candidate-level edge uses every tradeable candidate (independent of account caps), with a
day-block bootstrap 90% interval because candidates on the same day are correlated.
"""

import json
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from bot.backtest.engine import Backtester
from bot.backtest.report import save_run
from bot.config import ROOT, Config, load_config
from bot.data.store import read_1m
from bot.detectors import ALL_DETECTORS
from bot.detectors.base import Detector, Frame
from bot.detectors.orb_range import RangeORB
from bot.features.engine import bar_table
from bot.ml.dataset import build_dataset

BM = 15
SELECT = (date(2025, 10, 17), date(2026, 7, 31))
HOLDOUT = (date(2026, 8, 1), date(2026, 12, 31))
MIN_CANDIDATES = 100
VARIANTS: list[tuple[str, list[Detector], float, float]] = [  # name, detectors, atr_mult, rr
    ("V1_15m_3det_atr1_rr1.5", ALL_DETECTORS, 1.0, 1.5),
    ("V2_15m_3det_atr2_rr2", ALL_DETECTORS, 2.0, 2.0),
    ("V3_orb30_range_rr2", [RangeORB(30)], 1.0, 2.0),
    ("V4_orb30_range_rr3", [RangeORB(30)], 1.0, 3.0),
    ("V5_orb60_range_rr2", [RangeORB(60)], 1.0, 2.0),
    ("V6_orb60_range_rr3", [RangeORB(60)], 1.0, 3.0),
]


def window(tables: dict[str, pd.DataFrame], lo: date, hi: date) -> dict[str, Frame]:
    out = {}
    for s, t in tables.items():
        d = pd.DatetimeIndex(t.index).date
        out[s] = Frame.from_df(t[(d >= lo) & (d <= hi)])
    return out


def day_bootstrap(df: pd.DataFrame, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """90% CI of mean net R, resampling whole trading days."""
    if df.empty:
        return float("nan"), float("nan")
    g = df.groupby(df["decision_ts"].dt.normalize())["net_r"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def run(
    base: Config,
    tables: dict[str, pd.DataFrame],
    v: tuple[Any, ...],
    win: tuple[Any, ...],
    tag: str,
) -> dict[str, Any]:
    name, dets, atr_mult, rr = v
    cfg = base.model_copy(deep=True)
    cfg.app.detectors.atr_stop_mult, cfg.app.detectors.reward_risk = atr_mult, rr
    frames = window(tables, *win)
    cands = build_dataset(frames, cfg, BM, dets)
    res = Backtester(cfg, frames, detectors=dets, bar_minutes=BM).run()
    _, m = save_run(
        res,
        frames,
        f"{STAMP}_exp_{name}_{tag}",
        {
            "experiment": "wide_targets",
            "variant": name,
            "window": tag,
            "bar_minutes": BM,
            "mode": "rules_only",
        },
    )
    lo, hi = day_bootstrap(cands)
    edge = {
        "candidates": len(cands),
        "win_rate": float(cands["label"].mean() * 100) if len(cands) else 0.0,
        "breakeven": 100 / (1 + rr),
        "mean_gross_r": float(cands["gross_r"].mean()) if len(cands) else 0.0,
        "mean_net_r": float(cands["net_r"].mean()) if len(cands) else 0.0,
        "net_r_ci90": [lo, hi],
        "median_stop_pct": float(cands["stop_pct"].median()) if len(cands) else 0.0,
        "by_direction": cands.groupby("direction")["net_r"]
        .agg(["count", "mean"])
        .round(3)
        .to_dict()
        if len(cands)
        else {},
    }
    return {"variant": name, "window": tag, "metrics": m, "edge": edge}


def row(r: dict[str, Any]) -> dict[str, Any]:
    m, e = r["metrics"], r["edge"]
    return {
        "variant": r["variant"],
        "cand": e["candidates"],
        "cand win%": e["win_rate"],
        "breakeven%": e["breakeven"],
        "stop%": e["median_stop_pct"],
        "gross R": e["mean_gross_r"],
        "net R": e["mean_net_r"],
        "net R 90% CI": f"[{e['net_r_ci90'][0]:+.2f}, {e['net_r_ci90'][1]:+.2f}]",
        "trades": m["trades"],
        "win%": m.get("win_rate", 0),
        "₹/trade": m.get("expectancy", 0),
        "net ₹": m.get("net_pnl", 0),
        "maxDD%": m.get("max_drawdown_pct", 0),
    }


STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
cfg = load_config()
nifty = read_1m(cfg.watchlist.index)
tables = {s: bar_table(read_1m(s), nifty, BM) for s in cfg.watchlist.symbols}

sel = [run(cfg, tables, v, SELECT, "select") for v in VARIANTS]
print(f"\n=== SELECTION WINDOW {SELECT[0]} .. {SELECT[1]} ({BM}m bars) ===")
print(pd.DataFrame([row(r) for r in sel]).round(3).to_string(index=False))

eligible = [r for r in sel if r["edge"]["candidates"] >= MIN_CANDIDATES]
chosen = max(eligible or sel, key=lambda r: r["edge"]["mean_net_r"])
print(f"\nChosen on selection window: {chosen['variant']}")
vmap = {v[0]: v for v in VARIANTS}
names = list(dict.fromkeys([VARIANTS[0][0], chosen["variant"]]))
hold = [run(cfg, tables, vmap[n], HOLDOUT, "holdout") for n in names]
print(f"\n=== HOLDOUT {HOLDOUT[0]} onwards (run once) ===")
print(pd.DataFrame([row(r) for r in hold]).round(3).to_string(index=False))
print("\nChosen variant by direction (selection):", chosen["edge"]["by_direction"])

out = ROOT / "data" / "experiments" / f"{STAMP}_wide_targets.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps({"select": sel, "holdout": hold, "chosen": chosen["variant"]}, indent=1, default=str)
)
print(f"\nSaved: {out}")
