"""Feature engine. Row t = the bar OPENING at t, which closes at ``available_at``.

Inputs are always 1m candles; ``bar_minutes`` > 1 resamples them to closed N-minute bars
first, so detectors can run on 5m bars with the same code. Every feature uses only bars
closed at or before ``available_at``. Higher-timeframe (Nifty 5m/15m) values are joined on
close time, never open time. Bar-count indicators (RSI/EMA/ATR) are in bars; time-based
lookbacks (VWAP slope, relative strength) are in minutes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.data.candles import resample_closed
from bot.features.indicators import atr, ema, rsi, session_vwap

OR_MINUTES = 15
AUX_COLUMNS = [
    "vwap",
    "ema_21",
    "or_high",
    "or_low",
]  # price levels: used by detectors, NOT ML features
FEATURE_COLUMNS = [
    "price_vs_vwap_pct",
    "vwap_slope_pct",
    "rsi_14",
    "rsi_slope_3",
    "ema9_vs_21_pct",
    "ema21_vs_50_pct",
    "ema9_gt_21",
    "ema21_gt_50",
    "atr_14",
    "atr_pct",
    "realised_vol_20",
    "volume_vs_avg20",
    "volume_surge",
    "dist_or_high_pct",
    "dist_or_low_pct",
    "nifty_trend_5m",
    "nifty_trend_15m",
    "rel_strength_vs_nifty",
    "minutes_since_open",
    "minutes_to_close",
    "tod_bucket",
    "dist_prev_high_pct",
    "dist_prev_low_pct",
    "dist_prev_close_pct",
    "gap_pct",
]


def _htf_trend(nifty1m: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Trend sign (+1/-1/0) of Nifty on closed N-min bars: EMA9 vs EMA21, keyed by close time."""
    bars = resample_closed(nifty1m, minutes)
    e9, e21 = ema(bars["close"], 9), ema(bars["close"], 21)
    trend = pd.Series(np.sign(e9 - e21), index=e9.index).where(e21.notna())
    return pd.DataFrame({"available_at": bars["available_at"], f"nifty_trend_{minutes}m": trend})


def to_bars(df1m: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    """Closed N-minute OHLCV bars from 1m candles (identity for N=1)."""
    if bar_minutes == 1:
        return df1m
    return resample_closed(df1m, bar_minutes).drop(columns="available_at")


def compute_features(df: pd.DataFrame, nifty: pd.DataFrame, bar_minutes: int = 1) -> pd.DataFrame:
    """df, nifty: 1m OHLCV indexed by open time (tz-naive IST). Returns features + available_at."""
    nifty1m = nifty
    df, nifty = to_bars(df, bar_minutes), to_bars(nifty, bar_minutes)
    f = pd.DataFrame(index=df.index)
    f["available_at"] = df.index + pd.Timedelta(minutes=bar_minutes)
    close, vol = df["close"], df["volume"]
    day = pd.DatetimeIndex(df.index).normalize()

    vwap = session_vwap(df)
    f["price_vs_vwap_pct"] = (close / vwap - 1) * 100
    slope_bars = max(1, 5 // bar_minutes)  # ~5 minutes
    f["vwap_slope_pct"] = (vwap / vwap.groupby(day).shift(slope_bars) - 1) * 100

    r = rsi(close, 14)
    f["rsi_14"] = r
    f["rsi_slope_3"] = r - r.shift(3)

    e9, e21, e50 = ema(close, 9), ema(close, 21), ema(close, 50)
    f["ema9_vs_21_pct"] = (e9 / e21 - 1) * 100
    f["ema21_vs_50_pct"] = (e21 / e50 - 1) * 100
    f["ema9_gt_21"] = (e9 > e21).astype(float).where(e21.notna())
    f["ema21_gt_50"] = (e21 > e50).astype(float).where(e50.notna())

    a = atr(df, 14)
    f["atr_14"] = a
    f["atr_pct"] = a / close * 100
    f["realised_vol_20"] = np.log(close).diff().rolling(20).std() * 100

    avg_vol = vol.rolling(20).mean().shift(1)  # prior 20 bars, excludes current
    f["volume_vs_avg20"] = vol / avg_vol
    f["volume_surge"] = (f["volume_vs_avg20"] > 2.0).astype(float).where(avg_vol.notna())

    # Opening range = first 15 minutes; defined only once that window has closed.
    mins_open = pd.Series(
        np.asarray(
            (df.index - day - pd.Timedelta(hours=9, minutes=15)) / pd.Timedelta(minutes=1),
            dtype=float,
        ),
        index=df.index,
    )
    in_or = mins_open < OR_MINUTES
    or_hi = df["high"].where(in_or).groupby(day).cummax()
    or_lo = df["low"].where(in_or).groupby(day).cummin()
    or_hi = or_hi.groupby(day).ffill().where(~in_or)
    or_lo = or_lo.groupby(day).ffill().where(~in_or)
    f["dist_or_high_pct"] = (close / or_hi - 1) * 100
    f["dist_or_low_pct"] = (close / or_lo - 1) * 100

    # Higher-timeframe Nifty trend joined on CLOSE time.
    left = f[["available_at"]].reset_index()
    for m in (5, 15):
        right = _htf_trend(nifty1m, m).sort_values("available_at")
        merged = pd.merge_asof(left, right, on="available_at", direction="backward")
        f[f"nifty_trend_{m}m"] = merged[f"nifty_trend_{m}m"].to_numpy()

    # Relative strength: stock vs Nifty return over the last ~30 minutes (aligned on bar time).
    rs_bars = max(1, 30 // bar_minutes)
    n_close = nifty["close"].reindex(df.index)
    f["rel_strength_vs_nifty"] = (close.pct_change(rs_bars) - n_close.pct_change(rs_bars)) * 100

    f["minutes_since_open"] = mins_open
    f["minutes_to_close"] = 375 - mins_open - bar_minutes
    f["tod_bucket"] = (mins_open // 60).astype(float)  # hour of session, 0..6

    # Previous-day levels: only fully completed earlier days.
    daily = df.groupby(day).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev = daily.shift(1).reindex(day)
    prev.index = df.index
    f["dist_prev_high_pct"] = (close / prev["high"] - 1) * 100
    f["dist_prev_low_pct"] = (close / prev["low"] - 1) * 100
    f["dist_prev_close_pct"] = (close / prev["close"] - 1) * 100
    day_open = df["open"].groupby(day).transform("first")
    f["gap_pct"] = (day_open / prev["close"] - 1) * 100
    f["vwap"] = vwap
    f["ema_21"] = e21
    f["or_high"] = or_hi
    f["or_low"] = or_lo
    return f[["available_at", *FEATURE_COLUMNS, *AUX_COLUMNS]]


def bar_table(df1m: pd.DataFrame, nifty1m: pd.DataFrame, bar_minutes: int = 1) -> pd.DataFrame:
    """OHLCV bars joined with their features: the input for detectors and the backtester."""
    feats = compute_features(df1m, nifty1m, bar_minutes)
    return pd.concat([to_bars(df1m, bar_minutes), feats.drop(columns="available_at")], axis=1)
