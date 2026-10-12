"""Data-quality checks and per-symbol report."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from bot.data.sessions import BARS_PER_DAY_1M, clean_1m


@dataclass
class QualityReport:
    symbol: str
    days: int
    total_bars: int
    missing_bars: int
    partial_days: list[str]  # days with fewer than 375 bars (half days / gaps)
    duplicate_bars: int
    bad_ohlc_bars: int  # high<low, or open/close outside [low, high]
    zero_volume_bars: int
    outlier_bars: int  # |1m return| > 5%
    out_of_session_bars: int = 0  # outside 09:15-15:29 (pre-open etc.); dropped by clean_1m
    explained: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def check(df: pd.DataFrame, symbol: str) -> QualityReport:
    dups = int(df.index.duplicated().sum())
    d = df[~df.index.duplicated(keep="last")].sort_index()
    per_day = d.groupby(pd.DatetimeIndex(d.index).normalize()).size()
    partial = per_day[per_day < BARS_PER_DAY_1M]
    bad = (
        (d["high"] < d["low"])
        | (d["open"] > d["high"])
        | (d["open"] < d["low"])
        | (d["close"] > d["high"])
        | (d["close"] < d["low"])
    )
    ret = d["close"].pct_change().abs()
    return QualityReport(
        symbol=symbol,
        days=len(per_day),
        total_bars=len(d),
        missing_bars=int((BARS_PER_DAY_1M - partial).sum()),
        partial_days=[f"{pd.Timestamp(str(i)).date()}:{n}" for i, n in partial.items()],
        duplicate_bars=dups,
        bad_ohlc_bars=int(bad.sum()),
        zero_volume_bars=int((d["volume"] == 0).sum()),
        outlier_bars=int((ret > 0.05).sum()),
        out_of_session_bars=int(len(d) - len(clean_1m(d)[0]) - int(partial.sum())),
        explained=(
            "partial days are special sessions (e.g. Muhurat trading) and are excluded by clean_1m"
            if len(partial)
            else ""
        ),
    )
