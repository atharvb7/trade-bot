"""NSE full bhavcopy download (public daily file for every listed security)."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{:%d%m%Y}.csv"


def download_day(day: date, out_dir: Path) -> str:
    """Save one day's file. Returns 'got', 'none' (no file: holiday) or 'bad' (odd body).

    On holidays the archive may serve the previous session's file again; readers must take
    the date from the DATE1 column (see ``bot.backtest.daily.load_bhavcopy``).
    """
    req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
    body = b""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
            break
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return "none"
            if attempt == 3:
                raise
        except OSError:  # timeouts and dropped connections: retry
            if attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))
    if not body.startswith(b"SYMBOL"):
        return "bad"
    (out_dir / f"{day:%Y%m%d}.csv").write_bytes(body)
    return "got"
