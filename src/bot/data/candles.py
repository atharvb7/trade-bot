"""Tick -> 1m candles, and closed-bar resampling for higher timeframes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from bot.data.provider import OHLCV


def resample_closed(df1m: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample 1m bars to N-minute bars, keeping ONLY bars fully closed in the data.

    Index = bar open time; ``available_at`` = open + N minutes. Bars are anchored to
    the 09:15 session open per day. A bar whose end is after the last 1m bar's close
    is dropped, so a truncated history never yields a partially formed bar.
    """
    if df1m.empty:
        return pd.DataFrame(columns=[*OHLCV, "available_at"])
    day = pd.DatetimeIndex(df1m.index).normalize()
    offset = df1m.index - day - pd.Timedelta(hours=9, minutes=15)
    bucket = (offset // pd.Timedelta(minutes=minutes)) * pd.Timedelta(minutes=minutes)
    key = day + pd.Timedelta(hours=9, minutes=15) + bucket
    g = df1m.groupby(key)
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    out.index.name = "ts"
    out["available_at"] = out.index + pd.Timedelta(minutes=minutes)
    last_close = df1m.index[-1] + pd.Timedelta(minutes=1)
    return pd.DataFrame(out[out["available_at"] <= last_close])


@dataclass
class CandleBuilder:
    """Builds 1-minute candles from ticks. Emits a candle once its minute has passed."""

    _cur_minute: datetime | None = None
    _o: float = 0.0
    _h: float = 0.0
    _l: float = 0.0
    _c: float = 0.0
    _v: float = 0.0
    _last_cum_vol: float | None = None
    closed: list[dict[str, float | datetime]] = field(default_factory=list)

    def on_tick(
        self, ts: datetime, price: float, cum_volume: float
    ) -> dict[str, float | datetime] | None:
        minute = ts.replace(second=0, microsecond=0)
        emitted = None
        if self._cur_minute is not None and minute > self._cur_minute:
            emitted = self._flush()
        if self._cur_minute is None or minute > self._cur_minute:
            self._cur_minute = minute
            self._o = self._h = self._l = self._c = price
            self._v = 0.0
        else:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
            self._c = price
        if self._last_cum_vol is not None and cum_volume >= self._last_cum_vol:
            self._v += cum_volume - self._last_cum_vol
        self._last_cum_vol = cum_volume
        return emitted

    def _flush(self) -> dict[str, float | datetime]:
        bar: dict[str, float | datetime] = {
            "ts": self._cur_minute,  # type: ignore[dict-item]
            "open": self._o,
            "high": self._h,
            "low": self._l,
            "close": self._c,
            "volume": self._v,
        }
        self.closed.append(bar)
        return bar
