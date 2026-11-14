"""Download the first 30 minutes of 1m bars for every stock in the daily universe.

Protocol: docs/experiments/2026-11-14-opening-auction.md. Bars after --end are never
requested. Output: data/open_bars/<SYMBOL>.parquet (09:15-09:44 only); existing files are
skipped. Needs FYERS_APP_ID and FYERS_ACCESS_TOKEN in .env.
"""

import argparse
import time as time_mod
from datetime import date, time

from bot.backtest.daily import build_signals, load_bhavcopy
from bot.config import ROOT, Secrets
from bot.data.fyers_provider import FyersProvider

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2025-12-15")
ap.add_argument("--end", default="2026-08-31")
ap.add_argument("--shard", default="0/1", help="k/n: take every n-th symbol starting at k")
args = ap.parse_args()
shard_k, shard_n = (int(x) for x in args.shard.split("/"))
start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

out_dir = ROOT / "data" / "open_bars"
out_dir.mkdir(parents=True, exist_ok=True)
rows = load_bhavcopy(ROOT / "data" / "raw" / "bhavcopy", last_day=end)
universe = build_signals(rows)["universe"].loc[args.start : args.end]
symbols = sorted(universe.columns[universe.any()])[shard_k::shard_n]
print(f"{len(symbols)} symbols, {len(universe)} sessions", flush=True)

sec = Secrets()
prov = FyersProvider(
    sec.fyers_app_id, sec.fyers_access_token, pause_s=1.3
)  # 50 requests per minute cap
failed: list[str] = []
for i, sym in enumerate(symbols):
    path = out_dir / f"{sym}.parquet"
    if path.exists():
        continue
    path.touch()  # claim it so parallel shards do not repeat the work
    bars = None
    for attempt in range(4):  # "Bad request" is how Fyers answers when it is throttling
        try:
            bars = prov.history_1m(sym, start, end)
            break
        except RuntimeError as err:
            print(f"{sym}: {err} (attempt {attempt + 1})", flush=True)
            time_mod.sleep(30 * (attempt + 1))
    if bars is None:
        failed.append(sym)
        path.unlink()
        continue
    bars.between_time(time(9, 15), time(9, 44)).to_parquet(path)
    if i % 25 == 0:
        print(f"{i}/{len(symbols)} {sym} {len(bars)} bars", flush=True)
print(f"done; failed: {failed}")
