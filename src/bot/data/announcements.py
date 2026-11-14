"""NSE corporate announcements (public feed; needs the site's session cookies)."""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import time
import urllib.request
from datetime import date
from typing import Any

PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={}&to_date={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/html",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en",
    "Referer": PAGE,
}


class AnnouncementClient:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._has_cookies = False

    def _get(self, url: str) -> bytes:
        with self._opener.open(urllib.request.Request(url, headers=HEADERS), timeout=120) as resp:
            body: bytes = resp.read()
            gz = resp.headers.get("Content-Encoding") == "gzip"
            return gzip.decompress(body) if gz else body

    def fetch(self, start: date, end: date) -> list[dict[str, Any]]:
        """All announcements broadcast from ``start`` to ``end`` inclusive."""
        url = API.format(f"{start:%d-%m-%Y}", f"{end:%d-%m-%Y}")
        for attempt in range(4):
            try:
                if not self._has_cookies:
                    self._get(PAGE)
                    self._has_cookies = True
                items = json.loads(self._get(url))
                if not isinstance(items, list):
                    raise ValueError("unexpected announcements payload")
                return items
            except (OSError, ValueError):
                if attempt == 3:
                    raise
                self._has_cookies = False
                time.sleep(5 * (attempt + 1))
        return []
