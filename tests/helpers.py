from __future__ import annotations

import numpy as np
import pandas as pd

from bot.detectors.base import Frame


def frame(n: int, start: str = "2026-01-05 09:15", **cols: list[float] | float) -> Frame:
    idx = pd.date_range(start, periods=n, freq="1min")
    data: dict[str, np.ndarray] = {}
    for k, v in cols.items():
        arr = np.full(n, v, dtype=float) if np.isscalar(v) else np.asarray(v, dtype=float)
        assert len(arr) == n, k
        data[k] = arr
    return Frame(data, idx)


def ohlc_frame(
    rows: list[tuple[float, float, float, float]], start: str = "2026-01-05 09:15"
) -> Frame:
    o, h, lo, c = (list(x) for x in zip(*rows, strict=True))
    return frame(len(rows), start, open=o, high=h, low=lo, close=c, volume=1000.0, atr_14=1.0)
