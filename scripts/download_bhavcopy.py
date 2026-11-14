"""Download NSE full bhavcopy files (all listed securities, daily OHLC + delivery).

Public files, no credentials. Saved as-is to data/raw/bhavcopy/ (gitignored); existing
files are skipped. Usage: python scripts/download_bhavcopy.py [--start 2019-01-01]
"""

import argparse
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

from bot.config import ROOT

URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{:%d%m%Y}.csv"
OUT = ROOT / "data" / "raw" / "bhavcopy"

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2019-01-01")
ap.add_argument("--end", default=date.today().isoformat())
args = ap.parse_args()

OUT.mkdir(parents=True, exist_ok=True)
day, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
got = missing = 0
while day <= end:
    path = OUT / f"{day:%Y%m%d}.csv"
    if day.weekday() < 5 and not path.exists():
        req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
            if body.startswith(b"SYMBOL"):
                path.write_bytes(body)
                got += 1
        except urllib.error.HTTPError as err:
            if err.code != 404:  # 404 = holiday
                raise
            missing += 1
        time.sleep(0.25)  # polite pace
    day += timedelta(days=1)
print(f"downloaded {got}, no file for {missing} weekdays")
