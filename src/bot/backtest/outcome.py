"""Forward outcome of a candidate (used for rejected-candidate analysis and ML labels).

Market entry (default) = next bar open + slippage. Limit entry (``ExecutionCfg``) = a passive
limit that fills at its price only when a later bar trades through it, cancelled after
``limit_cancel_bars`` bars. Exits per ``check_exit``; square-off at 15:10 counts as timeout
(``must_square_off``), as does the end of a day whose data stops before square-off.
Labels use FUTURE bars by design — they must never be used as features.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time

import pandas as pd

from bot.backtest.fills import adverse, check_exit, limit_filled, limit_price, must_square_off
from bot.config import ExecutionCfg
from bot.detectors.base import Candidate, Frame

_MARKET = ExecutionCfg()


@dataclass
class Outcome:
    label: int  # 1 target hit before stop; 0 stop or timeout
    reason: str  # target | stop | timeout | no_entry | no_fill
    exit_price: float  # after slippage (stop / timeout); target fills are limit orders
    pnl_per_share: float  # gross, after slippage, before fees
    entry_price: float  # fill price after slippage (the signal close if never entered)
    exit_ts: pd.Timestamp | None = None


def find_limit_fill(
    c: Candidate, fr: Frame, i: int, ex: ExecutionCfg, square_off: time, bar_minutes: int = 1
) -> tuple[int, float] | None:
    """(bar index, price) where the passive entry limit fills, or None if it is cancelled."""
    lim = limit_price(c.direction, c.entry, ex.limit_offset_ticks)
    day = fr.index[i].date()
    for j in range(i + 1, min(i + 1 + ex.limit_cancel_bars, len(fr))):
        if fr.index[j].date() != day or must_square_off(fr.index[j], bar_minutes, square_off):
            return None
        if limit_filled(c.direction, lim, float(fr["high"][j]), float(fr["low"][j])):
            return j, lim
    return None


def simulate_outcome(
    c: Candidate,
    fr: Frame,
    i: int,
    slippage_pct: float,
    square_off: time = time(15, 10),
    bar_minutes: int = 1,
    execution: ExecutionCfg | None = None,
) -> Outcome:
    ex = execution or _MARKET
    n = len(fr)
    if i + 1 >= n or fr.index[i + 1].date() != fr.index[i].date():
        return Outcome(0, "no_entry", c.entry, 0.0, c.entry)
    if ex.entry_order == "limit":
        fill = find_limit_fill(c, fr, i, ex, square_off, bar_minutes)
        if fill is None:
            return Outcome(0, "no_fill", c.entry, 0.0, c.entry)
        start, entry = fill
    else:
        start, entry = i + 1, adverse(float(fr["open"][i + 1]), c.direction, True, slippage_pct)
    through = ex.target_fill == "through"
    sign = 1 if c.direction == "long" else -1
    day = fr.index[i].date()
    last = start
    for j in range(start, n):
        if fr.index[j].date() != day:
            break
        last = j
        if must_square_off(fr.index[j], bar_minutes, square_off):
            px = adverse(float(fr["open"][j]), c.direction, False, slippage_pct)
            return Outcome(0, "timeout", px, sign * (px - entry), entry, fr.index[j])
        # On a limit's fill bar the order of prices is unknown: allow the stop, never the target.
        target = c.target if (j > start or ex.entry_order == "market") else sign * math.inf
        hit = check_exit(
            c.direction,
            c.stop,
            target,
            float(fr["open"][j]),
            float(fr["high"][j]),
            float(fr["low"][j]),
            through,
        )
        if hit:
            px, why = hit
            if why.startswith("stop"):
                px = adverse(px, c.direction, False, slippage_pct)
            return Outcome(
                1 if why.startswith("target") else 0,
                "target" if why.startswith("target") else "stop",
                px,
                sign * (px - entry),
                entry,
                fr.index[j],
            )
    # Day (or data) ended before square-off: market exit at the last close, like the engine.
    px = adverse(float(fr["close"][last]), c.direction, False, slippage_pct)
    return Outcome(0, "timeout", px, sign * (px - entry), entry, fr.index[last])


def pd_ts(x: object) -> pd.Timestamp:
    return pd.Timestamp(str(x))
