"""Market data for the paper/live runner, behind one small interface so tests can fake it."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

from bot.backtest.daily import load_bhavcopy
from bot.backtest.events import classify_items
from bot.data.announcements import AnnouncementClient
from bot.data.bhavcopy import download_day
from bot.data.fyers_provider import FyersProvider


class MarketData(Protocol):
    def daily_rows(self, today: date) -> pd.DataFrame:
        """Bhavcopy rows of completed sessions before ``today`` (at least the last 20)."""

    def announcements(self, start: date, end: date) -> pd.DataFrame:
        """Classified announcements (symbol, ts, kind) broadcast from ``start`` to ``end``."""

    def quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        """symbol -> (today's open, previous close)."""

    def bars_1m(self, symbol: str, day: date) -> pd.DataFrame:
        """That day's 1m bars so far, indexed by bar open time; the last may be unfinished."""


class LiveMarketData:
    """NSE public files for daily data and announcements, Fyers for quotes and 1m bars."""

    def __init__(self, fyers: FyersProvider, bhavcopy_dir: Path) -> None:
        self._fyers = fyers
        self._dir = bhavcopy_dir
        self._news = AnnouncementClient()

    def daily_rows(self, today: date) -> pd.DataFrame:
        self._dir.mkdir(parents=True, exist_ok=True)
        first = today - timedelta(days=45)  # comfortably more than 20 sessions
        for offset in range(1, 46):
            day = today - timedelta(days=offset)
            if day.weekday() < 5 and not (self._dir / f"{day:%Y%m%d}.csv").exists():
                download_day(day, self._dir)
        rows = load_bhavcopy(self._dir, last_day=today - timedelta(days=1), first_day=first)
        return rows[rows["date"] < pd.Timestamp(today)]

    def announcements(self, start: date, end: date) -> pd.DataFrame:
        return classify_items(self._news.fetch(start, end))

    def quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        return self._fyers.quotes(symbols)

    def bars_1m(self, symbol: str, day: date) -> pd.DataFrame:
        return self._fyers.history_1m(symbol, day, day)
