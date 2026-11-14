"""Announcement events (order wins, results) traded open to close (pre-registered).

Protocol: docs/experiments/2026-11-14-announcement-events.md.
Usage: python scripts/exp_announcement_events.py [--holdout]
Without --holdout, no bhavcopy file or announcement month after 2025-06 is read.
"""

import argparse
import json
from datetime import date, datetime

import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.daily import Variant, build_signals, candidates, load_bhavcopy, summarize
from bot.backtest.events import event_flags, load_announcements
from bot.config import ROOT, load_config

WINDOWS = {"selection": ("2019-11-01", "2023-12-31"), "validation": ("2024-01-01", "2025-06-30")}

HOLDOUT = {"holdout": ("2025-07-01", "2026-11-13")}
PASSED = {("S2", "short"), ("S3", "short")}

ap = argparse.ArgumentParser()
ap.add_argument("--holdout", action="store_true")
holdout = ap.parse_args().holdout
if holdout:
    WINDOWS = HOLDOUT

cfg = load_config().costs
costs = CostModel(cfg)
double = {k: v * 2 for k, v in cfg.model_dump().items() if k.endswith("_pct") and k != "gst_pct"}
costs_x2 = CostModel(cfg.model_copy(update=double))
last_day = date(2026, 11, 13) if holdout else date(2025, 6, 30)
rows = load_bhavcopy(ROOT / "data" / "raw" / "bhavcopy", last_day=last_day)
sig = build_signals(rows, universe_size=500)
ann = load_announcements(
    ROOT / "data" / "raw" / "announcements", last_month="2026-11" if holdout else "2025-06"
)
flags = event_flags(ann, sig["gap"])
gap = sig["gap"]
one = gap * 0 + 1.0
sets = {
    "S1": one.where(flags["order"]),
    "S2": one.where(flags["order"] & (gap >= 0.02)),
    "S3": one.where(flags["results"] & (gap >= 0.02)),
    "S4": one.where(flags["results"] & (gap <= -0.02)),
}
top200 = build_signals(rows, universe_size=200)["universe"]
wide_high = rows.pivot(index="date", columns="symbol", values="high")
wide_close = rows.pivot(index="date", columns="symbol", values="close")


def diagnostics(set_id: str, v: Variant, c: pd.DataFrame) -> None:
    """The four pre-registered holdout diagnostics for one passing test."""
    keys = list(zip(c["date"], c["symbol"], strict=True))
    high = pd.Series([wide_high.at[k] for k in keys], index=c.index)
    close = pd.Series([wide_close.at[k] for k in keys], index=c.index)
    locked = close >= high * 0.999
    liquid = pd.Series([bool(top200.at[k]) for k in keys], index=c.index)
    tail = c["net"].where(c["net"] > c["net"].quantile(0.05), c["net"] * 2)
    x2 = candidates({**sig, set_id: sets[set_id]}, v, costs_x2, top=10**6)
    x2 = x2[x2["date"].isin(c["date"])]
    liq = summarize(c[liquid])
    print(f"  {set_id} close at day high: {locked.mean() * 100:.1f}% of candidates, ")
    print(f"     their mean net {c.loc[locked, 'net'].mean() * 100:+.3f}%")
    print(
        f"  {set_id} top-200 only: n {liq['n']:.0f}, net {liq.get('net_pct', float('nan')):+.3f}% "
    )
    print(f"     CI [{liq.get('lo', float('nan')):+.3f}, {liq.get('hi', float('nan')):+.3f}]")
    print(f"  {set_id} worst 5% losses doubled: net {tail.mean() * 100:+.3f}%")
    print(f"  {set_id} costs doubled: net {x2['net'].mean() * 100:+.3f}%")


bench_by_day = sig["intraday"].where(sig["universe"]).mean(axis=1)
print(f"classified announcements: {ann['kind'].value_counts().to_dict()}")

results: list[dict[str, object]] = []
for name, (lo, hi) in WINDOWS.items():
    print(f"\n## {name} {lo} .. {hi}")
    print("| Set | Side | Cands | Days | Gross % | Net % | Net 90% CI | Win % | Benchmark % |")
    print("|---|---|---|---|---|---|---|---|---|")
    for set_id, frame in sets.items():
        for side in ("long", "short"):
            if holdout and (set_id, side) not in PASSED:
                continue
            v = Variant(set_id, set_id, "high", side)
            c = candidates({**sig, set_id: frame}, v, costs, top=10**6)
            c = c[(c["date"] >= pd.Timestamp(lo)) & (c["date"] <= pd.Timestamp(hi))]
            m = summarize(c)
            bench = float(c["date"].map(bench_by_day).mean() * 100) if len(c) else float("nan")
            results.append({"window": name, "set": set_id, "side": side, "bench": bench, **m})
            if not m["n"]:
                continue
            print(
                f"| {set_id} | {side} | {m['n']:.0f} | {m['days']:.0f} | {m['gross_pct']:+.3f} | "
                f"{m['net_pct']:+.3f} | [{m['lo']:+.3f}, {m['hi']:+.3f}] | {m['win_pct']:.1f} | "
                f"{bench:+.3f} |"
            )
            if holdout:
                diagnostics(set_id, v, c)
dest = ROOT / "data" / "experiments" / "events"
dest.mkdir(parents=True, exist_ok=True)
path = dest / f"{datetime.now():%Y%m%d_%H%M%S}_{'holdout' if holdout else 'selection'}.json"
path.write_text(json.dumps(results, indent=1))
print(f"\nsaved {path.relative_to(ROOT)}")
