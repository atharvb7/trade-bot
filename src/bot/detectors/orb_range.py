"""Opening range breakout with a structural stop: the opposite side of the opening range.

Range = high/low of the first ``or_minutes`` of the session. Signal = first bar CLOSE beyond
the range after it has closed. Stop = other side of the range, target = reward_risk x risk.
Wider than the ATR-based ORB, so fees and slippage are a smaller fraction of risk.
Ignores ``atr_stop_mult``; the range itself sets the risk.
"""

from __future__ import annotations

import numpy as np

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Direction, Frame


class RangeORB:
    def __init__(self, or_minutes: int = 30) -> None:
        self.or_minutes = or_minutes
        self.name = f"orb{or_minutes}_range"

    def _range(self, fr: Frame, i: int) -> tuple[float, float, int] | None:
        """(high, low, bars_in_range) of today's opening range, or None if not yet complete."""
        day = fr.index[i].normalize()
        or_end = day + np.timedelta64(9 * 60 + 15 + self.or_minutes, "m")
        j = i
        while j > 0 and fr.index[j - 1].normalize() == day:
            j -= 1
        if fr.index[j] != day + np.timedelta64(9 * 60 + 15, "m"):
            return None  # session start missing -> cannot trust the range
        k = j
        while k <= i and fr.index[k] < or_end:
            k += 1
        bar_minutes = (fr.index[j + 1] - fr.index[j]).seconds // 60 if j + 1 < len(fr) else 1
        if fr.index[i] + np.timedelta64(bar_minutes, "m") <= or_end or k == j:
            return None  # signal bar must close after the range has closed
        return float(fr["high"][j:k].max()), float(fr["low"][j:k].min()), k - j

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < 1 or fr.index[i - 1].normalize() != fr.index[i].normalize():
            return None
        rng = self._range(fr, i)
        if rng is None:
            return None
        hi, lo, _ = rng
        c, pc = float(fr["close"][i]), float(fr["close"][i - 1])
        direction: Direction
        if c > hi and pc <= hi:
            direction, stop = "long", lo
        elif c < lo and pc >= lo:
            direction, stop = "short", hi
        else:
            return None
        risk = abs(c - stop)
        if risk <= 0:
            return None
        sign = 1 if direction == "long" else -1
        atr = float(fr["atr_14"][i]) if "atr_14" in fr.cols else float("nan")
        return Candidate(
            symbol,
            self.name,
            direction,
            fr.index[i],
            c,
            stop,
            c + sign * cfg.reward_risk * risk,
            atr,
        )
