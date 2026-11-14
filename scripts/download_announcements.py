"""Download NSE corporate announcements (all companies), one JSON file per month.

Public data, no credentials. Output: data/raw/announcements/YYYY-MM.json (gitignored);
existing files are skipped. Months after --end are never requested.
Usage: python scripts/download_announcements.py [--start 2019-10] [--end 2025-06]
"""

import argparse
import gzip
import http.cookiejar
import json
import time
import urllib.request

import pandas as pd

from bot.config import ROOT

PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={}&to_date={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/html",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en",
    "Referer": PAGE,
}

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2019-10")
ap.add_argument("--end", default="2025-06")
args = ap.parse_args()

out_dir = ROOT / "data" / "raw" / "announcements"
out_dir.mkdir(parents=True, exist_ok=True)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url: str) -> bytes:
    with opener.open(urllib.request.Request(url, headers=HEADERS), timeout=120) as resp:
        body: bytes = resp.read()
        return gzip.decompress(body) if resp.headers.get("Content-Encoding") == "gzip" else body


get(PAGE)  # sets the session cookies the API needs
for month in pd.period_range(args.start, args.end, freq="M"):
    path = out_dir / f"{month}.json"
    if path.exists():
        continue
    url = API.format(f"{month.start_time:%d-%m-%Y}", f"{month.end_time:%d-%m-%Y}")
    for attempt in range(4):
        try:
            items = json.loads(get(url))
            break
        except (OSError, ValueError):
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            get(PAGE)
    path.write_text(json.dumps(items))
    print(f"{month}: {len(items)} announcements", flush=True)
    time.sleep(1.0)
