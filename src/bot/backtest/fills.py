"""Exit logic shared by the backtester and the outcome simulator (one code path)."""

from __future__ import annotations


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
