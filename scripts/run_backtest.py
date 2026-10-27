"""Run a rules_only backtest and write a report to data/backtests/<run_id>/.

Usage: python scripts/run_backtest.py [--synthetic] [--mode rules_only] [--bar-minutes 5]
"""

import argparse
import json
from datetime import datetime

from bot.backtest.engine import Backtester
from bot.backtest.metrics import breakdowns
from bot.backtest.report import save_run
from bot.config import load_config
from bot.data.store import read_1m
from bot.data.synthetic import make_1m
from bot.detectors.base import Frame
from bot.features.engine import bar_table

ap = argparse.ArgumentParser()
ap.add_argument(
    "--synthetic", action="store_true", help="random-walk data (expect losses after costs)"
)
ap.add_argument("--mode", default="rules_only")
ap.add_argument("--bar-minutes", type=int, default=1, help="detector timeframe (1 or 5)")
ap.add_argument("--min-edge", type=float, default=None, help="override min-edge (research only)")
args = ap.parse_args()

cfg = load_config()
cfg.app.decision.mode = args.mode
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
    frames[s] = Frame.from_df(bar_table(df, nifty, args.bar_minutes))

res = Backtester(cfg, frames, bar_minutes=args.bar_minutes).run()
run_id = (
    datetime.now().strftime("%Y%m%d_%H%M%S")
    + f"_{args.mode}_{args.bar_minutes}m"
    + ("_synth" if args.synthetic else "")
)
_, m = save_run(
    res,
    frames,
    run_id,
    {"mode": args.mode, "bar_minutes": args.bar_minutes, "synthetic": args.synthetic},
)
print(f"run: {run_id}  days: {res.n_days}  candidates: {len(res.decisions)}")
print(json.dumps(m, indent=1))
if not res.decisions.empty:
    print(res.decisions["final_status"].value_counts().to_string())
for k, df in breakdowns(res.trades).items():
    print(f"\nby {k}\n{df.round(2).to_string()}")
if m.get("win_rate", 0) > 70:
    print("WARNING: win rate > 70% - probable bug (leakage / missing costs). Investigate.")
