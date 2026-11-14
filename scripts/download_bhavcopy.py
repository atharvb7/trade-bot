"""Download NSE full bhavcopy files (all listed securities, daily OHLC + delivery).

Public files, no credentials. Saved as-is to data/raw/bhavcopy/ (gitignored); existing
files are skipped. Usage: python scripts/download_bhavcopy.py [--start 2019-01-01]
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from bot.config import ROOT
from bot.data.bhavcopy import download_day

OUT = ROOT / "data" / "raw" / "bhavcopy"

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2019-01-01")
ap.add_argument("--end", default=date.today().isoformat())
args = ap.parse_args()

OUT.mkdir(parents=True, exist_ok=True)


def fetch(day: date) -> str:
    return download_day(day, OUT)


first, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
days = [first + timedelta(days=i) for i in range((end - first).days + 1)]
todo = [d for d in days if d.weekday() < 5 and not (OUT / f"{d:%Y%m%d}.csv").exists()]
with ThreadPoolExecutor(max_workers=4) as pool:  # the archive is slow; 4 is still polite
    results = list(pool.map(fetch, todo))
print({k: results.count(k) for k in ("got", "none", "bad")})
