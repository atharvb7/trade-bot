"""Daily cross-sectional signals traded open to close (pre-registered).

Protocol: docs/experiments/2026-11-14-daily-signals.md.
Usage: python scripts/exp_daily_signals.py [--holdout D1,D5]
Without --holdout, no file dated after 2025-06-30 is opened.
"""

import argparse
import json
from datetime import date, datetime

import numpy as np
import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.daily import VARIANTS, build_signals, candidates, load_bhavcopy, summarize
from bot.config import ROOT, load_config

SELECTION = ("2019-11-01", "2023-12-31")
VALIDATION = ("2024-01-01", "2025-06-30")
HOLDOUT = ("2025-07-01", "2099-12-31")

ap = argparse.ArgumentParser()
ap.add_argument("--holdout", default="", help="comma-separated ids of variants that passed")
args = ap.parse_args()
passed = [v for v in args.holdout.split(",") if v]

costs = CostModel(load_config().costs)
last = None if passed else date.fromisoformat(VALIDATION[1])
rows = load_bhavcopy(ROOT / "data" / "raw" / "bhavcopy", last_day=last)
sig = build_signals(rows)
windows = {"holdout": HOLDOUT} if passed else {"selection": SELECTION, "validation": VALIDATION}
variants = [v for v in VARIANTS if v.id in passed] if passed else VARIANTS

out: dict[str, object] = {
    "days": int(rows["date"].nunique()),
    "first": str(rows["date"].min().date()),
    "last": str(rows["date"].max().date()),
}
results: list[dict[str, object]] = []
for name, (lo, hi) in windows.items():
    uni = sig["intraday"].where(sig["universe"]).loc[lo:hi]
    bench = float(np.nanmean(uni.to_numpy()) * 100)
    print(f"\n## {name} {lo} .. {hi}: universe mean intraday return {bench:+.3f}%")
    print(
        "| Id | Side | Cands | Gross % | Net % | Net 90% CI | Win % | Top-1 net % | Top-20 net % |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for v in variants:
        c = candidates(sig, v, costs, top=20)
        c = c[(c["date"] >= pd.Timestamp(lo)) & (c["date"] <= pd.Timestamp(hi))]
        top5, top1, top20 = (summarize(c[c["rank"] <= k]) for k in (5, 1, 20))
        results.append({"window": name, "id": v.id, "top5": top5, "top1": top1, "top20": top20})
        if not top5["n"]:
            print(f"| {v.id} | {v.side} | 0 | – | – | – | – | – | – |")
            continue
        print(
            f"| {v.id} | {v.side} | {top5['n']:.0f} | {top5['gross_pct']:+.3f} | "
            f"{top5['net_pct']:+.3f} | [{top5['lo']:+.3f}, {top5['hi']:+.3f}] | "
            f"{top5['win_pct']:.1f} | {top1['net_pct']:+.3f} | {top20['net_pct']:+.3f} |"
        )
    results.append({"window": name, "benchmark_intraday_pct": bench})
out["results"] = results
dest = ROOT / "data" / "experiments" / "daily"
dest.mkdir(parents=True, exist_ok=True)
tag = "holdout" if passed else "selection"
path = dest / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.json"
path.write_text(json.dumps(out, indent=1))
print(f"\nsaved {path.relative_to(ROOT)}; {out['days']} days {out['first']} .. {out['last']}")
