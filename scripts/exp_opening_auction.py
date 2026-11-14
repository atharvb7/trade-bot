"""Fading the opening auction: enter at the official open, exit at the 09:20 bar open.

Protocol: docs/experiments/2026-11-14-opening-auction.md.
Usage: python scripts/exp_opening_auction.py [--holdout O1,O3]
Without --holdout, no bhavcopy file or 1m bar dated after 2026-08-31 is read.
"""

import argparse
import json
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.daily import (
    OPEN_VARIANTS,
    build_signals,
    candidates,
    load_bhavcopy,
    open_exit_prices,
    summarize,
    with_open_exit,
)
from bot.config import ROOT, load_config

SELECTION = ("2025-12-15", "2026-05-31")
VALIDATION = ("2026-06-01", "2026-08-31")
HOLDOUT = ("2026-09-01", "2099-12-31")
EXITS = {"09:20": time(9, 20), "09:16": time(9, 16), "09:30": time(9, 30)}  # first is primary

ap = argparse.ArgumentParser()
ap.add_argument("--holdout", default="", help="comma-separated ids of variants that passed")
args = ap.parse_args()
passed = [v for v in args.holdout.split(",") if v]

costs = CostModel(load_config().costs)
last = None if passed else date.fromisoformat(VALIDATION[1])
sig = build_signals(load_bhavcopy(ROOT / "data" / "raw" / "bhavcopy", last_day=last))
bars_dir = ROOT / "data" / ("open_bars_holdout" if passed else "open_bars")
windows = {"holdout": HOLDOUT} if passed else {"selection": SELECTION, "validation": VALIDATION}
variants = [v for v in OPEN_VARIANTS if v.id in passed] if passed else OPEN_VARIANTS

by_exit = {}
for label, at in EXITS.items():
    first, exits = open_exit_prices(bars_dir, at)
    by_exit[label] = with_open_exit(sig, first, exits)

results: list[dict[str, object]] = []
for name, (lo, hi) in windows.items():
    span = slice(pd.Timestamp(lo), pd.Timestamp(hi))
    uni = by_exit["09:20"]["intraday"].where(sig["universe"]).loc[span]
    bench = float(np.nanmean(uni.to_numpy()) * 100)
    in_universe = int(sig["universe"].loc[span].to_numpy().sum())
    covered = int(uni.notna().to_numpy().sum())
    print(f"\n## {name} {lo} .. {hi}: universe mean OPEN->09:20 {bench:+.3f}%, ")
    print(f"1m coverage {covered}/{in_universe} stock-days")
    print("| Id | Side | Cands | Dropped | Gross % | Net % | Net 90% CI | Win % | 09:16 | 09:30 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for v in variants:
        stats = {}
        for label, s in by_exit.items():
            c = candidates(s, v, costs, top=5)
            stats[label] = summarize(c[(c["date"] >= span.start) & (c["date"] <= span.stop)])
        picked = sig[v.signal].where(sig["universe"]).loc[span].notna().sum(axis=1).clip(upper=5)
        m = stats["09:20"]
        results.append({"window": name, "id": v.id, "picked": int(picked.sum()), **stats})
        if not m["n"]:
            print(f"| {v.id} | {v.side} | 0 | {int(picked.sum())} | – | – | – | – | – | – |")
            continue
        print(
            f"| {v.id} | {v.side} | {m['n']:.0f} | {picked.sum() - m['n']:.0f} | "
            f"{m['gross_pct']:+.3f} | {m['net_pct']:+.3f} | [{m['lo']:+.3f}, {m['hi']:+.3f}] | "
            f"{m['win_pct']:.1f} | {stats['09:16'].get('net_pct', float('nan')):+.3f} | "
            f"{stats['09:30'].get('net_pct', float('nan')):+.3f} |"
        )
    results.append({"window": name, "benchmark_open_0920_pct": bench})
dest = ROOT / "data" / "experiments" / "opening_auction"
dest.mkdir(parents=True, exist_ok=True)
path = dest / f"{datetime.now():%Y%m%d_%H%M%S}_{'holdout' if passed else 'selection'}.json"
path.write_text(json.dumps(results, indent=1))
print(f"\nsaved {path.relative_to(ROOT)}")
