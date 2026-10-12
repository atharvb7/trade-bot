"""Data-source interface. Strategy code depends on this, never on a vendor SDK."""

from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


class DataProvider(Protocol):
    def history_1m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """1-minute candles, index = open time (tz-naive IST), columns OHLCV."""
        ...
