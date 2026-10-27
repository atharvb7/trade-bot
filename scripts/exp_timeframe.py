"""Experiment: do detectors on 5-minute bars beat 1-minute bars after costs?

Protocol (fixed before looking at results):
  * Selection window 2025-10-17 .. 2026-07-31: run every variant, pick ONE by net
    expectancy per trade (min 30 trades) under the spec risk rules (min-edge 3x kept).
  * Holdout 2026-08-01 .. end: run the chosen variant and the 1m baseline ONCE.
  * Variants are a small fixed grid to limit overfitting.

Usage: python scripts/exp_timeframe.py
"""

import json
from datetime import date, datetime
from typing import Any

import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r, edge_summary
from bot.backtest.engine import Backtester
from bot.backtest.report import save_run
from bot.config import ROOT, Config, load_config
from bot.data.store import read_1m
from bot.detectors.base import Frame
from bot.features.engine import bar_table

SELECT = (date(2025, 10, 17), date(2026, 7, 31))
HOLDOUT = (date(2026, 8, 1), date(2026, 12, 31))
VARIANTS = [  # name, bar_minutes, atr_stop_mult, reward_risk
    ("1m_atr1.0_rr1.5", 1, 1.0, 1.5),  # spec baseline
    ("5m_atr1.0_rr1.5", 5, 1.0, 1.5),
    ("5m_atr1.0_rr2.0", 5, 1.0, 2.0),
    ("5m_atr1.5_rr1.5", 5, 1.5, 1.5),
    ("5m_atr1.5_rr2.0", 5, 1.5, 2.0),
]
MIN_TRADES = 30


def window(tables: dict[str, pd.DataFrame], lo: date, hi: date) -> dict[str, Frame]:
    out = {}
    for s, t in tables.items():
        d = pd.DatetimeIndex(t.index).date
        out[s] = Frame.from_df(t[(d >= lo) & (d <= hi)])
    return out


def run(
    base: Config,
    tables: dict[int, dict[str, pd.DataFrame]],
    v: tuple[Any, ...],
    win: tuple[Any, ...],
    tag: str,
) -> dict[str, Any]:
    name, bm, atr_mult, rr = v
    cfg = base.model_copy(deep=True)
    cfg.app.detectors.atr_stop_mult, cfg.app.detectors.reward_risk = atr_mult, rr
    frames = window(tables[bm], *win)
    res = Backtester(cfg, frames, bar_minutes=bm).run()
    run_id = f"{STAMP}_exp_{name}_{tag}"
    _, m = save_run(
        res,
        frames,
        run_id,
        {
            "experiment": "timeframe",
            "variant": name,
            "window": tag,
            "bar_minutes": bm,
            "mode": "rules_only",
        },
    )
    edge = candidate_r(res.decisions, CostModel(cfg.costs))
    by_setup = {s: edge_summary(g, rr) for s, g in edge.groupby("setup")} if len(edge) else {}
    return {
        "variant": name,
        "window": tag,
        "run_id": run_id,
        "metrics": m,
        "edge": edge_summary(edge, rr),
        "edge_by_setup": by_setup,
    }


def row(r: dict[str, Any]) -> dict[str, Any]:
    m, e = r["metrics"], r["edge"]
    return {
        "variant": r["variant"],
        "trades": m["trades"],
        "win%": m.get("win_rate", 0),
        "exp/trade ₹": m.get("expectancy", 0),
        "net ₹": m.get("net_pnl", 0),
        "maxDD%": m.get("max_drawdown_pct", 0),
        "cand": e.get("candidates", 0),
        "cand win%": e.get("win_rate", 0),
        "breakeven%": e.get("breakeven_win_rate", 0),
        "gross R": e.get("mean_gross_r", 0),
        "fee R": e.get("mean_fee_r", 0),
        "net R": e.get("mean_net_r", 0),
        "risk%": e.get("median_risk_pct", 0),
    }


STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
cfg = load_config()
nifty = read_1m(cfg.watchlist.index)
raw = {s: read_1m(s) for s in cfg.watchlist.symbols}
tables = {
    bm: {s: bar_table(df, nifty, bm) for s, df in raw.items()} for bm in {v[1] for v in VARIANTS}
}

sel = [run(cfg, tables, v, SELECT, "select") for v in VARIANTS]
print("\n=== SELECTION WINDOW", SELECT, "===")
print(pd.DataFrame([row(r) for r in sel]).round(3).to_string(index=False))

eligible = [r for r in sel if r["metrics"]["trades"] >= MIN_TRADES]
chosen = max(eligible or sel, key=lambda r: r["metrics"].get("expectancy", float("-inf")))
print(f"\nChosen on selection window: {chosen['variant']}")

vmap = {v[0]: v for v in VARIANTS}
hold_names = list(dict.fromkeys([VARIANTS[0][0], chosen["variant"]]))
hold = [run(cfg, tables, vmap[n], HOLDOUT, "holdout") for n in hold_names]
print("\n=== HOLDOUT", HOLDOUT[0], "onwards (run once) ===")
print(pd.DataFrame([row(r) for r in hold]).round(3).to_string(index=False))

print(f"\nEdge by setup, {chosen['variant']} (selection window):")
print(pd.DataFrame(chosen["edge_by_setup"]).T.round(3).to_string())

out = ROOT / "data" / "experiments" / f"{STAMP}_timeframe.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps({"select": sel, "holdout": hold, "chosen": chosen["variant"]}, indent=1, default=str)
)
print(f"\nSaved: {out}")
