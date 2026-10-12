"""NSE cash session constants. All timestamps in this project are tz-naive IST.

Convention: a candle is indexed by its OPEN time. It is closed (usable) at
``open + period``. ``available_at`` columns carry that close time.
"""

from __future__ import annotations

from datetime import time

import pandas as pd

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
BARS_PER_DAY_1M = 375  # 09:15 .. 15:29 inclusive


def clean_1m(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Keep regular-session bars only; drop special-session days (e.g. Muhurat, <375 bars).

    Returns (clean_df, notes) where notes lists what was removed, so the quality report can
    show every gap as explained.
    """
    idx = pd.DatetimeIndex(df.index)
    mins = idx.hour * 60 + idx.minute
    in_session = (mins >= 9 * 60 + 15) & (mins <= 15 * 60 + 29)
    out_days = sorted({str(pd.Timestamp(str(t)).date()) for t in idx[~in_session].normalize()})
    d = df[in_session]
    didx = pd.DatetimeIndex(d.index).normalize()
    per_day = d.groupby(didx).size()
    short = per_day[per_day < BARS_PER_DAY_1M]
    d = d[~didx.isin(short.index)]
    return d, {
        "out_of_session_days": out_days,
        "dropped_partial_days": [f"{pd.Timestamp(str(i)).date()}:{n}" for i, n in short.items()],
    }
