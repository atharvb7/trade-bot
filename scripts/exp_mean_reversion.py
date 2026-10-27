"""Experiment: mean-reversion / fade setups on 15-minute bars.

Protocol (pre-registered, docs/experiments/2026-10-27-mean-reversion.md):
  * 8 variants, in-sample 2025-10-17 .. 2026-04-30, validation 2026-05-01 .. 2026-07-31.
  * Only parquet months <= 2026-07 are read and rows after 2026-07-31 are dropped before
    any feature is computed. The holdout (2026-08-01 onward) is never loaded.
  * Choose ONE variant by in-sample mean net R (>= 100 candidates); it passes only if
    in-sample net R > 0, validation net R 90% CI lower bound > 0, validation backtest
    net Rs > 0 and validation net R with doubled costs > 0.
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
from bot.data.sessions import clean_1m
from bot.data.store import DEFAULT_DIR
from bot.detectors.base import Detector, Frame
from bot.detectors.fades import FailedORBFade, GapFade, RSI2Fade, VWAPFade
from bot.features.engine import bar_table
from bot.ml.dataset import build_dataset

BM = 15
CUTOFF = date(2026, 7, 31)  # last date this track may touch; holdout starts 2026-08-01
INSAMPLE = (date(2025, 10, 17), date(2026, 4, 30))
VALID = (date(2026, 5, 1), CUTOFF)
MIN_CANDIDATES = 100
OUT_DIR = ROOT / "data" / "experiments" / "mean-reversion"
VARIANTS: list[tuple[str, Detector]] = [
    ("V1_vwap_fade1.0", VWAPFade(1.0)),
    ("V2_vwap_fade1.5", VWAPFade(1.5)),
    ("V3_vwap_fade1.0_confirm", VWAPFade(1.0, confirm=True)),
    ("V4_failed_orb30_rr1", FailedORBFade(30, rr=1.0)),
    ("V5_failed_orb60_rr1", FailedORBFade(60, rr=1.0)),
    ("V6_gap_fade1.0", GapFade(1.0, bar_minutes=BM)),
    ("V7_rsi2_10_90_trend", RSI2Fade(10, 90, trend=True)),
    ("V8_rsi2_5_95_pure", RSI2Fade(5, 95, trend=False)),
]


def load_1m_until(symbol: str, cutoff: date) -> pd.DataFrame:
    """Read only monthly files up to ``cutoff``'s month, then drop rows after ``cutoff``."""
    last_month = f"{cutoff:%Y-%m}"
    folder = DEFAULT_DIR / symbol.replace(" ", "_").replace(":", "_")
    files = [f for f in sorted(folder.glob("*.parquet")) if f.stem <= last_month]
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    df = df[pd.DatetimeIndex(df.index).date <= cutoff]
    df = clean_1m(df)[0]
    assert pd.DatetimeIndex(df.index).max().date() <= cutoff
    return df


def window(tables: dict[str, pd.DataFrame], lo: date, hi: date) -> dict[str, Frame]:
    """Same as scripts/exp_wide_targets.py (that script runs on import, so it is copied)."""
    out = {}
    for s, t in tables.items():
        d = pd.DatetimeIndex(t.index).date
        out[s] = Frame.from_df(t[(d >= lo) & (d <= hi)])
    return out


def day_bootstrap(df: pd.DataFrame, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """90% CI of mean net R, resampling whole trading days (as in exp_wide_targets.py)."""
    if df.empty:
        return float("nan"), float("nan")
    g = df.groupby(df["decision_ts"].dt.normalize())["net_r"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def doubled(cfg: Config) -> Config:
    """Every percentage fee rate and the slippage x2 (GST stays 18% of the doubled base)."""
    c = cfg.model_copy(deep=True)
    k = c.costs
    k.brokerage_pct *= 2
    k.stt_sell_pct *= 2
    k.exchange_txn_pct *= 2
    k.sebi_pct *= 2
    k.stamp_buy_pct *= 2
    k.slippage_pct *= 2
    return c


def edge(cands: pd.DataFrame) -> dict[str, Any]:
    if cands.empty:
        return {"candidates": 0}
    risk = (cands["entry"] - cands["stop"]).abs()
    reward = (cands["target"] - cands["entry"]).abs()
    lo, hi = day_bootstrap(cands)
    month = cands["decision_ts"].dt.strftime("%Y-%m")
    by_month = cands.groupby(month)["net_r"].agg(["count", "mean"]).round(3)
    by_dir = cands.groupby("direction")["net_r"].agg(["count", "mean"]).round(3)
    return {
        "candidates": int(len(cands)),
        "median_stop_pct": float((risk / cands["entry"] * 100).median()),
        "median_target_pct": float((reward / cands["entry"] * 100).median()),
        "win_rate": float(cands["label"].mean() * 100),
        "breakeven_win_rate": float((1 / (1 + reward / risk)).mean() * 100),
        "outcomes_pct": (cands["outcome"].value_counts(normalize=True) * 100).round(1).to_dict(),
        "mean_gross_r": float(cands["gross_r"].mean()),
        "mean_fee_r": float((cands["gross_r"] - cands["net_r"]).mean()),
        "mean_net_r": float(cands["net_r"].mean()),
        "net_r_ci90": [lo, hi],
        "by_month": {m: [int(r["count"]), float(r["mean"])] for m, r in by_month.iterrows()},
        "by_direction": {d: [int(r["count"]), float(r["mean"])] for d, r in by_dir.iterrows()},
        "last_decision": str(cands["decision_ts"].max()),
    }


def bt(cfg: Config, frames: dict[str, Frame], det: Detector, run_id: str) -> dict[str, Any]:
    res = Backtester(cfg, frames, detectors=[det], bar_minutes=BM).run()
    _, m = save_run(res, frames, run_id, {"experiment": "mean_reversion", "bar_minutes": BM})
    return {k: m.get(k, 0.0) for k in ("trades", "win_rate", "net_pnl", "max_drawdown_pct")} | {
        "profit_factor": m.get("profit_factor", 0.0)
    }


def run(
    cfgs: dict[str, Config], frames: dict[str, Frame], vid: str, det: Detector, tag: str
) -> dict[str, Any]:
    out: dict[str, Any] = {"variant": vid, "window": tag}
    for ck, cfg in cfgs.items():
        cands = build_dataset(frames, cfg, BM, [det])
        if len(cands):
            assert cands["decision_ts"].max().date() <= CUTOFF
        out[f"edge_{ck}"] = edge(cands)
        out[f"bt_{ck}"] = bt(cfg, frames, det, f"{STAMP}_meanrev_{vid}_{tag}_{ck}")
    return out


def fmt_ci(e: dict[str, Any]) -> str:
    lo, hi = e.get("net_r_ci90", [float("nan")] * 2)
    return f"[{lo:+.3f}, {hi:+.3f}]"


def edge_row(r: dict[str, Any]) -> dict[str, Any]:
    e, e2 = r["edge_base"], r["edge_x2"]
    d = e.get("by_direction", {})
    return {
        "variant": r["variant"],
        "cand": e["candidates"],
        "stop%": e.get("median_stop_pct"),
        "win%": e.get("win_rate"),
        "BE%": e.get("breakeven_win_rate"),
        "gross R": e.get("mean_gross_r"),
        "fee R": e.get("mean_fee_r"),
        "net R": e.get("mean_net_r"),
        "net R 90% CI": fmt_ci(e),
        "net R x2": e2.get("mean_net_r"),
        "long n/R": "{}/{:+.3f}".format(*d.get("long", [0, float("nan")])),
        "short n/R": "{}/{:+.3f}".format(*d.get("short", [0, float("nan")])),
    }


def bt_row(r: dict[str, Any]) -> dict[str, Any]:
    b, b2 = r["bt_base"], r["bt_x2"]
    return {
        "variant": r["variant"],
        "trades": b["trades"],
        "win%": b["win_rate"],
        "net ₹": b["net_pnl"],
        "maxDD%": b["max_drawdown_pct"],
        "PF": b["profit_factor"],
        "x2 trades": b2["trades"],
        "x2 net ₹": b2["net_pnl"],
        "x2 maxDD%": b2["max_drawdown_pct"],
    }


def month_table(rs: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {r["variant"]: {m: v[1] for m, v in r["edge_base"].get("by_month", {}).items()} for r in rs}
    ).T


STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
base = load_config()
cfgs = {"base": base, "x2": doubled(base)}
nifty = load_1m_until(base.watchlist.index, CUTOFF)
tables = {s: bar_table(load_1m_until(s, CUTOFF), nifty, BM) for s in base.watchlist.symbols}
assert all(pd.DatetimeIndex(t.index).max().date() <= CUTOFF for t in tables.values())

results: dict[str, list[dict[str, Any]]] = {}
for tag, win in (("insample", INSAMPLE), ("validation", VALID)):
    frames = window(tables, *win)
    results[tag] = [run(cfgs, frames, vid, det, tag) for vid, det in VARIANTS]
    print(f"\n=== {tag.upper()} {win[0]} .. {win[1]} ({BM}m bars) — candidate edge ===")
    print(pd.DataFrame([edge_row(r) for r in results[tag]]).round(3).to_string(index=False))
    print(f"\n--- {tag}: full-rules backtest (₹1,000, spec risk) ---")
    print(pd.DataFrame([bt_row(r) for r in results[tag]]).round(2).to_string(index=False))
    print(f"\n--- {tag}: net R per month ---")
    print(month_table(results[tag]).round(3).to_string())
    for r in results[tag]:
        wr = r["edge_base"].get("win_rate", 0.0)
        if wr > 70:
            print(f"!! {r['variant']} {tag}: candidate win rate {wr:.1f}% > 70% — investigate")
        print(f"{r['variant']} {tag} outcomes %: {r['edge_base'].get('outcomes_pct')}")

ins, val = results["insample"], results["validation"]
eligible = [r for r in ins if r["edge_base"]["candidates"] >= MIN_CANDIDATES]
chosen = max(eligible, key=lambda r: r["edge_base"]["mean_net_r"])
cv = next(r for r in val if r["variant"] == chosen["variant"])
checks = {
    "a_insample_net_r_pos": chosen["edge_base"]["mean_net_r"] > 0,
    "b_validation_ci_lo_pos": cv["edge_base"].get("net_r_ci90", [-1])[0] > 0,
    "c_validation_bt_net_pos": cv["bt_base"]["net_pnl"] > 0,
    "d_validation_x2_net_r_pos": cv["edge_x2"].get("mean_net_r", -1) > 0,
}
print(f"\nChosen in-sample: {chosen['variant']}  checks: {checks}  PASS={all(checks.values())}")
others = [
    r["variant"]
    for r, v in zip(ins, val, strict=True)
    if r["edge_base"].get("mean_net_r", -1) > 0 and v["edge_base"].get("net_r_ci90", [-1])[0] > 0
]
print(f"Other variants meeting (a)+(b) (hypothesis-generating only): {others}")

OUT_DIR.mkdir(parents=True, exist_ok=True)
out = OUT_DIR / f"{STAMP}_results.json"
out.write_text(
    json.dumps(
        {"results": results, "chosen": chosen["variant"], "checks": checks, "others": others},
        indent=1,
        default=str,
    )
)
print(f"\nSaved: {out}")
