"""Deterministic synthetic 1-minute data for tests and offline development."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.data.provider import OHLCV


def make_1m(
    days: int = 5, start: str = "2026-01-05", seed: int = 0, base: float = 100.0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx: list[pd.Timestamp] = []
    for d in pd.bdate_range(start, periods=days):
        idx.extend(pd.date_range(d + pd.Timedelta(hours=9, minutes=15), periods=375, freq="1min"))
    n = len(idx)
    ret = rng.normal(0, 0.0007, n)
    close = base * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[base], close[:-1]])
    spread = np.abs(rng.normal(0, 0.0004, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.integers(1_000, 50_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.DatetimeIndex(idx, name="ts"),
    )[OHLCV]
