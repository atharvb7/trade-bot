"""Exit and entry fill logic shared by the backtester and the outcome simulator (one code path)."""

from __future__ import annotations

import math
from datetime import time

import pandas as pd


def must_square_off(bar_open: pd.Timestamp, bar_minutes: int, square_off: time) -> bool:
    """True if a position must be closed at this bar's OPEN.

    A bar is held only if it closes at or before the square-off time, so no position is
    ever exposed past square-off: with 1m/5m bars this exits at the 15:10 open; with 15m
    bars the 15:00-15:15 bar straddles 15:10, so the exit is at its 15:00 open.
    """
    return (bar_open + pd.Timedelta(minutes=bar_minutes)).time() > square_off


def tick_size(price: float) -> float:
    """NSE cash-equity tick size by price band (revised schedule in force through 2025-26).

    The ₹0.01 (< ₹250) and ₹0.05 (₹250-1,000) bands are confirmed on our 1-minute data (every
    price of a stock above ₹250 is a multiple of ₹0.05; stocks below ₹250 print in paise).
    The higher bands follow the exchange circular and are not verified here; the band is
    strictly set from the previous close, which we approximate with the current price.
    """
    if price < 250:
        return 0.01
    if price < 1000:
        return 0.05
    if price < 5000:
        return 0.10
    if price < 10000:
        return 0.50
    if price < 20000:
        return 1.00
    return 5.00


def check_exit(
    direction: str,
    stop: float,
    target: float,
    o: float,
    h: float,
    low: float,
    target_through: bool = False,
) -> tuple[float, str] | None:
    """Return (price, reason) if the bar hits stop/target, else None.

    Pessimistic: gaps through a level fill at the open; if both levels lie inside the bar
    the stop is assumed to hit first. Stops trigger on a touch (exchange stop orders trigger
    on the last traded price). With ``target_through`` the resting target limit fills only
    when the bar trades at least one tick beyond it, since a mere touch may leave a resting
    order unfilled in the queue.
    """
    tt = tick_size(target) if target_through and math.isfinite(target) else 0.0
    if direction == "long":
        if o <= stop:
            return o, "stop_gap"
        if low <= stop:
            return stop, "stop"
        if o >= target + tt:
            return o, "target_gap"
        if h >= target + tt:
            return target, "target"
    else:
        if o >= stop:
            return o, "stop_gap"
        if h >= stop:
            return stop, "stop"
        if o <= target - tt:
            return o, "target_gap"
        if low <= target - tt:
            return target, "target"
    return None


def adverse(price: float, direction: str, is_entry: bool, slippage_pct: float) -> float:
    """Apply slippage against us: buys pay more, sells receive less."""
    buying = (direction == "long") == is_entry
    return price * (1 + slippage_pct / 100) if buying else price * (1 - slippage_pct / 100)


def limit_price(direction: str, signal_px: float, offset_ticks: int) -> float:
    """Passive entry limit: the signal price moved ``offset_ticks`` away from the market."""
    tick = tick_size(signal_px)
    sign = 1 if direction == "long" else -1
    return round((signal_px - sign * offset_ticks * tick) / tick) * tick


def limit_filled(direction: str, limit: float, h: float, low: float) -> bool:
    """A resting entry limit is certain to have filled only if the bar trades THROUGH it.

    A trade one tick beyond the limit means every order at the limit (ours included) was
    executed first under price-time priority; a touch alone proves nothing about our place in
    the queue. Fill price is the limit itself, never better (conservative).
    """
    tick = tick_size(limit)
    eps = 1e-9
    if direction == "long":
        return low <= limit - tick + eps
    return h >= limit + tick - eps
