"""Download NSE full bhavcopy files (all listed securities, daily OHLC + delivery).

Public files, no credentials. Saved as-is to data/raw/bhavcopy/ (gitignored); existing
files are skipped. Usage: python scripts/download_bhavcopy.py [--start 2019-01-01]
"""

import argparse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from bot.config import ROOT

URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{:%d%m%Y}.csv"
OUT = ROOT / "data" / "raw" / "bhavcopy"

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2019-01-01")
ap.add_argument("--end", default=date.today().isoformat())
args = ap.parse_args()

OUT.mkdir(parents=True, exist_ok=True)


def fetch(day: date) -> str:
    """Return 'got', 'none' (404: holiday) or 'bad' (unexpected body)."""
    req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise
        return "none"
    if not body.startswith(b"SYMBOL"):
        return "bad"
    (OUT / f"{day:%Y%m%d}.csv").write_bytes(body)
    return "got"


first, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
days = [first + timedelta(days=i) for i in range((end - first).days + 1)]
todo = [d for d in days if d.weekday() < 5 and not (OUT / f"{d:%Y%m%d}.csv").exists()]
with ThreadPoolExecutor(max_workers=4) as pool:  # the archive is slow; 4 is still polite
    results = list(pool.map(fetch, todo))
print({k: results.count(k) for k in ("got", "none", "bad")})
