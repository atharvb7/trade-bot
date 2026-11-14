"""Download NSE corporate announcements (all companies), one JSON file per month.

Public data, no credentials. Output: data/raw/announcements/YYYY-MM.json (gitignored);
existing files are skipped. Months after --end are never requested.
Usage: python scripts/download_announcements.py [--start 2019-10] [--end 2025-06]
"""

import argparse
import json

import pandas as pd

from bot.config import ROOT
from bot.data.announcements import AnnouncementClient

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2019-10")
ap.add_argument("--end", default="2025-06")
args = ap.parse_args()

out_dir = ROOT / "data" / "raw" / "announcements"
out_dir.mkdir(parents=True, exist_ok=True)
client = AnnouncementClient()
for month in pd.period_range(args.start, args.end, freq="M"):
    path = out_dir / f"{month}.json"
    if path.exists():
        continue
    items = client.fetch(month.start_time.date(), month.end_time.date())
    path.write_text(json.dumps(items))
    print(f"{month}: {len(items)} announcements", flush=True)
