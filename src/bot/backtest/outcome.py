"""Forward outcome of a candidate (used for rejected-candidate analysis and ML labels).

Entry = next bar open + slippage; exits per ``check_exit``; square-off at 15:10 counts as timeout.
Labels use FUTURE bars by design — they must never be used as features.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from bot.backtest.fills import adverse, check_exit
from bot.detectors.base import Candidate, Frame


@dataclass
class Outcome:
    label: int  # 1 target hit before stop; 0 stop or timeout
    reason: str  # target | stop | timeout | no_entry
    exit_price: float
    pnl_per_share: float  # gross, after slippage, before fees


def simulate_outcome(
    c: Candidate, fr: Frame, i: int, slippage_pct: float, square_off: time = time(15, 10)
) -> Outcome:
    n = len(fr)
    if i + 1 >= n or fr.index[i + 1].date() != fr.index[i].date():
        return Outcome(0, "no_entry", c.entry, 0.0)
    entry = adverse(float(fr["open"][i + 1]), c.direction, True, slippage_pct)
    sign = 1 if c.direction == "long" else -1
    day = fr.index[i].date()
    last = i + 1
    for j in range(i + 1, n):
        if fr.index[j].date() != day:
            break
        last = j
        if fr.index[j].time() >= square_off:
            px = adverse(float(fr["open"][j]), c.direction, False, slippage_pct)
            return Outcome(0, "timeout", px, sign * (px - entry))
        hit = check_exit(
            c.direction,
            c.stop,
            c.target,
            float(fr["open"][j]),
            float(fr["high"][j]),
            float(fr["low"][j]),
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
            )
    px = float(fr["close"][last])
    return Outcome(0, "timeout", px, sign * (px - entry))


def pd_ts(x: object) -> pd.Timestamp:
    return pd.Timestamp(str(x))
