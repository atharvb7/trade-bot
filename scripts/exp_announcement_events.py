"""Announcement events (order wins, results) traded open to close (pre-registered).

Protocol: docs/experiments/2026-11-14-announcement-events.md.
No bhavcopy file or announcement month after 2025-06 is read.
"""

import json
from datetime import date, datetime

import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.daily import Variant, build_signals, candidates, load_bhavcopy, summarize
from bot.backtest.events import event_flags, load_announcements
from bot.config import ROOT, load_config

WINDOWS = {"selection": ("2019-11-01", "2023-12-31"), "validation": ("2024-01-01", "2025-06-30")}

costs = CostModel(load_config().costs)
rows = load_bhavcopy(ROOT / "data" / "raw" / "bhavcopy", last_day=date(2025, 6, 30))
sig = build_signals(rows, universe_size=500)
ann = load_announcements(ROOT / "data" / "raw" / "announcements", last_month="2025-06")
flags = event_flags(ann, sig["gap"])
gap = sig["gap"]
one = gap * 0 + 1.0
sets = {
    "S1": one.where(flags["order"]),
    "S2": one.where(flags["order"] & (gap >= 0.02)),
    "S3": one.where(flags["results"] & (gap >= 0.02)),
    "S4": one.where(flags["results"] & (gap <= -0.02)),
}
bench_by_day = sig["intraday"].where(sig["universe"]).mean(axis=1)
print(f"classified announcements: {ann['kind'].value_counts().to_dict()}")

results: list[dict[str, object]] = []
for name, (lo, hi) in WINDOWS.items():
    print(f"\n## {name} {lo} .. {hi}")
    print("| Set | Side | Cands | Days | Gross % | Net % | Net 90% CI | Win % | Benchmark % |")
    print("|---|---|---|---|---|---|---|---|---|")
    for set_id, frame in sets.items():
        for side in ("long", "short"):
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
dest = ROOT / "data" / "experiments" / "events"
dest.mkdir(parents=True, exist_ok=True)
path = dest / f"{datetime.now():%Y%m%d_%H%M%S}_selection.json"
path.write_text(json.dumps(results, indent=1))
print(f"\nsaved {path.relative_to(ROOT)}")
