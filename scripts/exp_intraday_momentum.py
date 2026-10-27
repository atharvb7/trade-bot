"""Experiment: time-of-day momentum and cross-sectional relative strength (5-minute bars).

Protocol (pre-registered before running; docs/experiments/2026-10-27-intraday-momentum.md):
  * 8 variants (M1..M8), common wide stop (session extreme, >= 0.6% of price), target 3R,
    exits mostly at the 15:10 square-off. Spec risk rules unchanged (min-edge 3x, Rs 1,000).
  * Only data <= 2026-07-31 is read: monthly parquet files after 2026-07 are never opened, and
    rows after 2026-07-31 are dropped before any feature is computed.
  * In-sample 2025-10-17 .. 2026-04-30, validation 2026-05-01 .. 2026-07-31; both reported.
  * Pass = in-sample net R > 0, validation 90% CI lower bound > 0, >= 30 validation candidates,
    validation backtest net Rs > 0.
Reuses window / day_bootstrap logic from scripts/exp_wide_targets.py (copied: that script runs
its experiment at import time, so it cannot be imported).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from bot.backtest.engine import Backtester
from bot.backtest.metrics import compute_metrics
from bot.backtest.report import save_run
from bot.config import ROOT, Config, load_config
from bot.data.sessions import clean_1m
from bot.data.store import DEFAULT_DIR
from bot.detectors.base import Detector, Frame
from bot.detectors.cross_section import CrossSection
from bot.detectors.momentum import IntradayMomentum, RelativeStrength
from bot.features.engine import bar_table, to_bars
from bot.ml.dataset import build_dataset

BM = 5
RR = 3.0
LAST_DAY = date(2026, 7, 31)  # holdout starts 2026-08-01: never loaded
LAST_MONTH = "2026-07"
WINDOWS = {
    "insample": (date(2025, 10, 17), date(2026, 4, 30)),
    "validation": (date(2026, 5, 1), LAST_DAY),
}
MIN_VAL_CANDIDATES = 30
OUT_DIR = ROOT / "data" / "experiments" / "intraday-momentum"

Factory = Callable[[CrossSection], Detector]
VARIANTS: dict[str, Factory] = {
    "M1_ts_open_1015": lambda p: IntradayMomentum("M1_ts_open_1015", "10:15", 0.50),
    "M2_ts_prevclose_1015": lambda p: IntradayMomentum(
        "M2_ts_prevclose_1015", "10:15", 0.75, anchor="prev_close"
    ),
    "M3_ts_open_1115": lambda p: IntradayMomentum("M3_ts_open_1115", "11:15", 0.75),
    "M4_ts_open_1015_trendday": lambda p: IntradayMomentum(
        "M4_ts_open_1015_trendday", "10:15", 0.50, nifty="trend", nifty_pct=0.30, panel=p
    ),
    "M5_ts_open_1015_rangeday": lambda p: IntradayMomentum(
        "M5_ts_open_1015_rangeday", "10:15", 0.50, nifty="range", nifty_pct=0.30, panel=p
    ),
    "M6_xs_rs_1015": lambda p: RelativeStrength("M6_xs_rs_1015", p, "10:15", 0.20),
    "M7_xs_rs_1115": lambda p: RelativeStrength("M7_xs_rs_1115", p, "11:15", 0.20),
    "M8_gao_first30_1430": lambda p: IntradayMomentum(
        "M8_gao_first30_1430", "14:30", 0.50, anchor="prev_close", measure_at="09:45"
    ),
}


def load_pre_holdout(symbol: str) -> pd.DataFrame:
    """1m candles up to LAST_DAY. Files for months after LAST_MONTH are never opened."""
    folder = DEFAULT_DIR / symbol.replace(" ", "_").replace(":", "_")
    files = sorted(f for f in folder.glob("*.parquet") if f.stem <= LAST_MONTH)
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[pd.DatetimeIndex(df.index).date <= LAST_DAY]
    df = clean_1m(df)[0]
    assert pd.DatetimeIndex(df.index).max().date() <= LAST_DAY, symbol
    return df


def window_df(t: pd.DataFrame, lo: date, hi: date) -> pd.DataFrame:
    d = pd.DatetimeIndex(t.index).date
    return t[(d >= lo) & (d <= hi)]


def day_bootstrap(
    df: pd.DataFrame, col: str = "net_r", n: int = 2000, seed: int = 0
) -> list[float]:
    """90% CI of mean R per candidate, resampling whole trading days."""
    if df.empty:
        return [float("nan"), float("nan")]
    g = df.groupby(df["decision_ts"].dt.normalize())[col].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n, len(g)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return [float(np.percentile(means, 5)), float(np.percentile(means, 95))]


def scaled(base: Config, cost_mult: float) -> Config:
    cfg = base.model_copy(deep=True)
    cfg.app.detectors.reward_risk = RR
    for f in type(cfg.costs).model_fields:
        setattr(cfg.costs, f, getattr(cfg.costs, f) * cost_mult)
    return cfg


def edge(c: pd.DataFrame) -> dict[str, Any]:
    if c.empty:
        return {"candidates": 0}
    wins, losses = c.loc[c["net_r"] > 0, "net_r"], c.loc[c["net_r"] <= 0, "net_r"]
    aw, al = (
        (float(wins.mean()) if len(wins) else 0.0),
        (float(losses.mean()) if len(losses) else 0.0),
    )
    month = c["decision_ts"].dt.to_period("M").astype(str)
    return {
        "candidates": int(len(c)),
        "days": int(c["decision_ts"].dt.normalize().nunique()),
        "median_stop_pct": float(c["stop_pct"].median()),
        "win_rate": float((c["net_r"] > 0).mean() * 100),
        "breakeven_win_rate": float(-al / (aw - al) * 100) if aw - al > 0 else float("nan"),
        "target_hit_rate": float(c["label"].mean() * 100),
        "exit_reasons": c["outcome"].value_counts().to_dict(),
        "mean_gross_r": float(c["gross_r"].mean()),
        "mean_fee_r": float((c["gross_r"] - c["net_r"]).mean()),
        "mean_net_r": float(c["net_r"].mean()),
        "net_r_ci90": day_bootstrap(c),
        "per_month_net_r": c.groupby(month)["net_r"]
        .agg(["count", "mean"])
        .round(3)
        .to_dict("index"),
        "by_direction": c.groupby("direction")["net_r"]
        .agg(["count", "mean"])
        .round(3)
        .to_dict("index"),
    }


def run(
    vid: str,
    tag: str,
    base: Config,
    tables: dict[str, pd.DataFrame],
    nifty_bars: pd.DataFrame,
) -> dict[str, Any]:
    lo, hi = WINDOWS[tag]
    frames = {s: Frame.from_df(window_df(t, lo, hi)) for s, t in tables.items()}
    panel = CrossSection.from_frames(frames, Frame.from_df(window_df(nifty_bars, lo, hi)))
    out: dict[str, Any] = {"variant": vid, "window": tag}
    for mult, key in ((1.0, "x1"), (2.0, "x2")):
        cfg = scaled(base, mult)
        det = VARIANTS[vid](panel)
        cands = build_dataset(frames, cfg, BM, [det])
        if len(cands):  # one code path check: no decision after the configured window
            assert (cands["decision_ts"] > cands["ts"]).all()
            assert cands["decision_ts"].dt.date.max() <= hi
        res = Backtester(cfg, frames, detectors=[det], bar_minutes=BM).run()
        if key == "x1":
            _, m = save_run(
                res,
                frames,
                f"{STAMP}_mom_{vid}_{tag}",
                {
                    "experiment": "intraday_momentum",
                    "variant": vid,
                    "window": tag,
                    "bar_minutes": BM,
                },
            )
            out["edge"] = edge(cands)
            out["backtest"] = m
            if len(res.trades):
                out["backtest_exit_reasons"] = res.trades["exit_reason"].value_counts().to_dict()
        else:
            out["edge_x2"] = {
                "mean_net_r": float(cands["net_r"].mean()) if len(cands) else float("nan"),
                "net_r_ci90": day_bootstrap(cands),
            }
            out["backtest_x2"] = compute_metrics(res.trades, res.start_capital, res.n_days)
    return out


def fmt_ci(ci: list[float]) -> str:
    return f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def row(r: dict[str, Any]) -> dict[str, Any]:
    e, m = r["edge"], r["backtest"]
    if e.get("candidates", 0) == 0:
        return {"variant": r["variant"], "cand": 0}
    return {
        "variant": r["variant"],
        "cand": e["candidates"],
        "stop%": e["median_stop_pct"],
        "win%": e["win_rate"],
        "BE win%": e["breakeven_win_rate"],
        "tgt%": e["target_hit_rate"],
        "gross R": e["mean_gross_r"],
        "fee R": e["mean_fee_r"],
        "net R": e["mean_net_r"],
        "net R 90% CI": fmt_ci(e["net_r_ci90"]),
        "net R x2": r["edge_x2"]["mean_net_r"],
        "trades": m["trades"],
        "bt win%": m.get("win_rate", 0.0),
        "net ₹": m.get("net_pnl", 0.0),
        "maxDD%": m.get("max_drawdown_pct", 0.0),
        "PF": m.get("profit_factor", 0.0),
        "net ₹ x2": r["backtest_x2"].get("net_pnl", 0.0),
    }


def passes(ins: dict[str, Any], val: dict[str, Any]) -> bool:
    ei, ev = ins["edge"], val["edge"]
    return bool(
        ei.get("candidates", 0) > 0
        and ei["mean_net_r"] > 0
        and ev.get("candidates", 0) >= MIN_VAL_CANDIDATES
        and ev["net_r_ci90"][0] > 0
        and val["backtest"].get("net_pnl", 0.0) > 0
    )


def main() -> None:
    cfg = load_config()
    nifty1m = load_pre_holdout(cfg.watchlist.index)
    tables = {s: bar_table(load_pre_holdout(s), nifty1m, BM) for s in cfg.watchlist.symbols}
    nifty_bars = to_bars(nifty1m, BM)
    last = max(pd.DatetimeIndex(t.index).max() for t in [*tables.values(), nifty_bars])
    assert last.date() <= LAST_DAY, last
    print(f"Data loaded up to {last} (holdout excluded)")

    results = {tag: [run(v, tag, cfg, tables, nifty_bars) for v in VARIANTS] for tag in WINDOWS}
    pd.set_option("display.width", 250)
    for tag, rs in results.items():
        lo, hi = WINDOWS[tag]
        print(f"\n=== {tag.upper()} {lo} .. {hi} ({BM}m bars, target {RR}R, stop >= 0.6%) ===")
        print(pd.DataFrame([row(r) for r in rs]).round(3).to_string(index=False))

    print("\n=== Long vs short (net R: count, mean) ===")
    for tag, rs in results.items():
        for r in rs:
            print(f"{tag:10s} {r['variant']:26s} {r['edge'].get('by_direction')}")
    print("\n=== Per-month net R (mean, candidates) ===")
    for tag, rs in results.items():
        for r in rs:
            pm = r["edge"].get("per_month_net_r", {})
            print(
                f"{tag:10s} {r['variant']:26s} "
                + "  ".join(f"{k}:{v['mean']:+.2f}({v['count']})" for k, v in pm.items())
            )
    print("\n=== Exit reasons (candidates) ===")
    for r in results["insample"] + results["validation"]:
        print(f"{r['window']:10s} {r['variant']:26s} {r['edge'].get('exit_reasons')}")

    flags = [
        r["variant"] + "/" + r["window"]
        for rs in results.values()
        for r in rs
        if r["edge"].get("win_rate", 0) > 70 or r["backtest"].get("win_rate", 0) > 70
    ]
    print("\nWin rate > 70% (investigate):", flags or "none")

    passed = [
        (v, results["validation"][k])
        for k, v in enumerate(VARIANTS)
        if passes(results["insample"][k], results["validation"][k])
    ]
    print("\nVariants passing the pre-registered rule:", [v for v, _ in passed] or "none")
    chosen = max(passed, key=lambda p: p[1]["edge"]["net_r_ci90"][0])[0] if passed else None
    print("Recommended for holdout:", chosen or "none (no holdout run for this track)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{STAMP}_results.json"
    out.write_text(
        json.dumps(
            {"results": results, "passed": [v for v, _ in passed], "chosen": chosen},
            indent=1,
            default=str,
        )
    )
    print(f"\nSaved: {out}")


STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
if __name__ == "__main__":
    main()
