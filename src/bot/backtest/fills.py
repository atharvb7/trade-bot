"""Exit logic shared by the backtester and the outcome simulator (one code path)."""

from __future__ import annotations

from datetime import time

import pandas as pd


def must_square_off(bar_open: pd.Timestamp, bar_minutes: int, square_off: time) -> bool:
    """True if a position must be closed at this bar's OPEN.

    A bar is held only if it closes at or before the square-off time, so no position is
    ever exposed past square-off: with 1m/5m bars this exits at the 15:10 open; with 15m
    bars the 15:00-15:15 bar straddles 15:10, so the exit is at its 15:00 open.
    """
    return (bar_open + pd.Timedelta(minutes=bar_minutes)).time() > square_off


def check_exit(
    direction: str, stop: float, target: float, o: float, h: float, low: float
) -> tuple[float, str] | None:
    """Return (price, reason) if the bar hits stop/target, else None.

    Pessimistic: gaps through a level fill at the open; if both levels lie inside the bar
    the stop is assumed to hit first.
    """
    if direction == "long":
        if o <= stop:
            return o, "stop_gap"
        if low <= stop:
            return stop, "stop"
        if o >= target:
            return o, "target_gap"
        if h >= target:
            return target, "target"
    else:
        if o >= stop:
            return o, "stop_gap"
        if h >= stop:
            return stop, "stop"
        if o <= target:
            return o, "target_gap"
        if low <= target:
            return target, "target"
    return None


def adverse(price: float, direction: str, is_entry: bool, slippage_pct: float) -> float:
    """Apply slippage against us: buys pay more, sells receive less."""
    buying = (direction == "long") == is_entry
    return price * (1 + slippage_pct / 100) if buying else price * (1 - slippage_pct / 100)
