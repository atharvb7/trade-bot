"""Backtest audit: re-measure two existing setups on the SELECTION window only.

Setups (unchanged from the earlier experiments):
  * 5m bars, 3 detectors, atr 1.0, rr 1.5   (docs/experiments/2026-10-12-timeframe.md)
  * 15m bars, RangeORB(60), rr 3            (docs/experiments/2026-10-12-wide-targets.md, V6)

Raw 1m data is truncated BEFORE 2026-08-01 before any bar or feature is built, so no holdout
bar can influence anything here. Reports mean net R per candidate (every tradeable candidate,
via ``build_dataset``) with the day-block bootstrap 90% interval, the engine's candidate R
(``candidate_r`` on the backtester's decisions) and the account-level backtest metrics.

Usage: python scripts/exp_audit_rerun.py <tag>    (writes data/experiments/audit/<tag>.json)
"""

import json
import sys
from datetime import date
from typing import Any

import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r, day_bootstrap
from bot.backtest.engine import Backtester
from bot.backtest.metrics import compute_metrics
from bot.backtest.outcome import simulate_outcome
from bot.config import ROOT, Config, load_config
from bot.data.store import read_1m
from bot.detectors import ALL_DETECTORS
from bot.detectors.base import Candidate, Detector, Frame
from bot.detectors.orb_range import RangeORB
from bot.features.engine import bar_table
from bot.ml.dataset import build_dataset
from bot.risk.manager import parse_hhmm

SELECT = (date(2025, 10, 17), date(2026, 7, 31))
HOLDOUT_START = pd.Timestamp("2026-08-01")
SETUPS: list[tuple[str, int, list[Detector], float, float]] = [
    ("5m_3det_atr1.0_rr1.5", 5, ALL_DETECTORS, 1.0, 1.5),
    ("15m_orb60_range_rr3", 15, [RangeORB(60)], 1.0, 3.0),
]


def summarise(d: pd.DataFrame) -> dict[str, Any]:
    lo, hi = day_bootstrap(d)
    return {
        "candidates": int(len(d)),
        "win_rate": float(d["label"].mean() * 100),
        "mean_gross_r": float(d["gross_r"].mean()),
        "mean_fee_r": float((d["gross_r"] - d["net_r"]).mean()),
        "mean_net_r": float(d["net_r"].mean()),
        "net_r_ci90": [lo, hi],
        "outcomes": d["outcome"].value_counts().to_dict(),
        "by_setup": d.groupby("setup")["net_r"].agg(["count", "mean"]).round(4).to_dict("index"),
    }


def exits_on_1m(cands: pd.DataFrame, raw: dict[str, pd.DataFrame], c: Config) -> pd.DataFrame:
    """Diagnostic: replay each candidate's exit on 1m bars (same signal, stop, target and
    entry open), so square-off is exactly 15:10 and stop-vs-target inside one N-minute bar
    is resolved minute by minute. Measures the cost of evaluating exits on N-minute bars."""
    costs, slip = CostModel(c.costs), c.costs.slippage_pct
    sq_off = parse_hhmm(c.risk.square_off_time)
    m1 = {s: Frame.from_df(df) for s, df in raw.items()}
    pos = {s: {ts: k for k, ts in enumerate(fr.index)} for s, fr in m1.items()}
    rows = []
    for r in cands.itertuples():
        sym = str(r.symbol)
        i = pos[sym][pd.Timestamp(str(r.decision_ts))] - 1  # 1m bar before the entry open
        cand = Candidate(sym, str(r.setup), r.direction, r.ts, r.entry, r.stop, r.target, 0.0)  # type: ignore[arg-type]
        out = simulate_outcome(cand, m1[sym], i, slip, sq_off, 1)
        risk = abs(float(r.entry) - float(r.stop))  # type: ignore[arg-type]
        fee = costs.round_trip_fees(str(r.direction), out.entry_price, out.exit_price)
        rows.append(
            {
                "decision_ts": r.decision_ts,
                "setup": r.setup,
                "label": out.label,
                "outcome": out.reason,
                "nmin_outcome": r.outcome,
                "gross_r": out.pnl_per_share / risk,
                "net_r": (out.pnl_per_share - fee) / risk,
            }
        )
    return pd.DataFrame(rows)


def main(tag: str) -> None:
    cfg = load_config()

    def load(sym: str) -> pd.DataFrame:
        df = read_1m(sym)
        return df[df.index < HOLDOUT_START]  # never let a holdout bar in

    nifty = load(cfg.watchlist.index)
    raw = {s: load(s) for s in cfg.watchlist.symbols}
    results: dict[str, Any] = {}
    for name, bm, dets, atr_mult, rr in SETUPS:
        c = cfg.model_copy(deep=True)
        c.app.detectors.atr_stop_mult, c.app.detectors.reward_risk = atr_mult, rr
        frames: dict[str, Frame] = {}
        for s, df in raw.items():
            t = bar_table(df, nifty, bm)
            d = pd.DatetimeIndex(t.index).date
            frames[s] = Frame.from_df(t[(d >= SELECT[0]) & (d <= SELECT[1])])
        assert max(fr.index.max() for fr in frames.values()) < HOLDOUT_START
        cands = build_dataset(frames, c, bm, dets)
        res = Backtester(c, frames, detectors=dets, bar_minutes=bm).run()
        eng = candidate_r(res.decisions, CostModel(c.costs))
        eng = eng.assign(decision_ts=eng["ts"] + pd.Timedelta(minutes=bm))
        one = exits_on_1m(cands, raw, c)
        flips = pd.crosstab(one["nmin_outcome"], one["outcome"]).to_dict("index")
        results[name] = {
            "all_candidates": summarise(cands),
            "all_candidates_exits_on_1m": {**summarise(one), "nmin_vs_1m_outcome": flips},
            "engine_candidates": summarise(eng),
            "backtest": compute_metrics(res.trades, res.start_capital, res.n_days),
        }
        a, e = results[name]["all_candidates"], results[name]["engine_candidates"]
        bt = results[name]["backtest"]
        print(
            f"{name}: all-cand n={a['candidates']} net R {a['mean_net_r']:+.4f} "
            f"CI [{a['net_r_ci90'][0]:+.3f}, {a['net_r_ci90'][1]:+.3f}] | engine-cand "
            f"n={e['candidates']} net R {e['mean_net_r']:+.4f} | trades "
            f"{bt['trades']} net ₹ {bt.get('net_pnl', 0.0):+.1f}"
        )
        o = results[name]["all_candidates_exits_on_1m"]
        print(f"   exits on 1m bars: net R {o['mean_net_r']:+.4f}  outcome flips {flips}")
    out = ROOT / "data" / "experiments" / "audit" / f"{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, default=str))
    print(f"Saved: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "run")
