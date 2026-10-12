"""Run a rules_only backtest and write a report to data/backtests/<run_id>/.

Usage: python scripts/run_backtest.py [--synthetic] [--mode rules_only]
"""

import argparse
import json
from datetime import datetime

import pandas as pd

from bot.backtest.engine import Backtester
from bot.backtest.metrics import breakdowns, compute_metrics
from bot.config import ROOT, load_config
from bot.data.store import read_1m
from bot.data.synthetic import make_1m
from bot.detectors.base import Frame
from bot.features.engine import compute_features

ap = argparse.ArgumentParser()
ap.add_argument(
    "--synthetic", action="store_true", help="random-walk data (expect losses after costs)"
)
ap.add_argument("--mode", default="rules_only")
ap.add_argument("--min-edge", type=float, default=None, help="override min-edge (research only)")
args = ap.parse_args()

cfg = load_config()
cfg.app.decision.mode = args.mode  # type: ignore[assignment]
if args.min_edge is not None:
    cfg.risk.min_edge_cost_multiple = args.min_edge
frames: dict[str, Frame] = {}
if args.synthetic:
    nifty = make_1m(days=60, seed=99, base=20000)
    syms = {
        s: make_1m(days=60, seed=i, base=100 + 40 * i) for i, s in enumerate(cfg.watchlist.symbols)
    }
else:
    nifty = read_1m(cfg.watchlist.index)
    syms = {s: read_1m(s) for s in cfg.watchlist.symbols}
for s, df in syms.items():
    feats = compute_features(df, nifty)
    frames[s] = Frame.from_df(pd.concat([df, feats.drop(columns="available_at")], axis=1))

res = Backtester(cfg, frames).run()
m = compute_metrics(res.trades, res.start_capital, res.n_days)
run_id = (
    datetime.now().strftime("%Y%m%d_%H%M%S")
    + f"_{args.mode}"
    + ("_synth" if args.synthetic else "")
)
out = ROOT / "data" / "backtests" / run_id
out.mkdir(parents=True, exist_ok=True)
res.trades.to_parquet(out / "trades.parquet")
res.decisions.to_parquet(out / "decisions.parquet")
res.equity.to_parquet(out / "equity.parquet")
bars = []
for s_, fr in frames.items():
    cols = ("open", "high", "low", "close", "volume", "vwap", "ema_21")
    b = pd.DataFrame({k: fr[k] for k in cols}, index=fr.index)
    b["symbol"] = s_
    bars.append(b)
pd.concat(bars).to_parquet(out / "bars.parquet")
(out / "metrics.json").write_text(
    json.dumps(
        {
            "metrics": m,
            "config": res.config,
            "n_days": res.n_days,
            "start_capital": res.start_capital,
            "mode": args.mode,
            "synthetic": args.synthetic,
        },
        indent=1,
        default=str,
    )
)
print(f"run: {run_id}  days: {res.n_days}  candidates: {len(res.decisions)}")
print(json.dumps(m, indent=1))
if not res.decisions.empty:
    print(res.decisions["final_status"].value_counts().to_string())
for k, df in breakdowns(res.trades).items():
    print(f"\nby {k}\n{df.round(2).to_string()}")
if m.get("win_rate", 0) > 70:
    print("WARNING: win rate > 70% - probable bug (leakage / missing costs). Investigate.")
