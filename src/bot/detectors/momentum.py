"""Time-of-day momentum and cross-sectional relative strength (docs/experiments/2026-10-27-*).

Both fire only on the bar whose CLOSE is ``decide_at`` (one signal per symbol per day) and use
a wide structural stop: the session extreme so far, but never closer than ``min_stop_pct`` of
price. Target = ``reward_risk`` x risk (set far, so most trades exit at the 15:10 square-off).
Ignores ``atr_stop_mult``.
"""

from __future__ import annotations

from datetime import time
from typing import Literal

import numpy as np
import pandas as pd

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Direction, Frame
from bot.detectors.cross_section import SESSION_OPEN, CrossSection


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def session_start(fr: Frame, i: int) -> int | None:
    """Index of today's first bar, or None if the session's 09:15 bar is missing."""
    day = fr.index[i].normalize()
    j = i
    while j > 0 and fr.index[j - 1].normalize() == day:
        j -= 1
    return j if fr.index[j].time() == SESSION_OPEN else None


def wide_candidate(
    symbol: str,
    setup: str,
    direction: Direction,
    fr: Frame,
    i: int,
    j: int,
    cfg: DetectorCfg,
    min_stop_pct: float,
) -> Candidate | None:
    """Entry = signal close; stop = session extreme over bars j..i, floored at min_stop_pct."""
    c = float(fr["close"][i])
    if not np.isfinite(c) or c <= 0:
        return None
    floor = c * min_stop_pct / 100
    if direction == "long":
        risk = max(c - float(np.min(fr["low"][j : i + 1])), floor)
    else:
        risk = max(float(np.max(fr["high"][j : i + 1])) - c, floor)
    sign = 1 if direction == "long" else -1
    atr = float(fr["atr_14"][i]) if "atr_14" in fr.cols else float("nan")
    return Candidate(
        symbol,
        setup,
        direction,
        fr.index[i],
        c,
        c - sign * risk,
        c + sign * cfg.reward_risk * risk,
        atr,
    )


class IntradayMomentum:
    """Trade in the direction of the morning move.

    The move is close at ``measure_at`` (default: the decision time) over the session open
    (``anchor="open"``) or the previous session's last close (``anchor="prev_close"``). Optional
    NIFTY regime filter from a CrossSection: ``"trend"`` needs NIFTY's move since open to have
    the same sign and |move| >= ``nifty_pct``; ``"range"`` needs |move| < ``nifty_pct``.
    """

    def __init__(
        self,
        name: str,
        decide_at: str = "10:15",
        min_move_pct: float = 0.5,
        anchor: Literal["open", "prev_close"] = "open",
        measure_at: str | None = None,
        nifty: Literal["trend", "range"] | None = None,
        nifty_pct: float = 0.3,
        panel: CrossSection | None = None,
        min_stop_pct: float = 0.6,
        bar_minutes: int = 5,
    ) -> None:
        if nifty is not None and panel is None:
            raise ValueError("the NIFTY filter needs a CrossSection panel")
        self.name = name
        self.decide_at, self.measure_at = _hhmm(decide_at), _hhmm(measure_at or decide_at)
        self.min_move_pct, self.anchor = min_move_pct, anchor
        self.nifty, self.nifty_pct, self.panel = nifty, nifty_pct, panel
        self.min_stop_pct = min_stop_pct
        self.bar = pd.Timedelta(minutes=bar_minutes)

    def _closes_at(self, fr: Frame, k: int) -> time:
        return (fr.index[k] + self.bar).time()

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if self._closes_at(fr, i) != self.decide_at:
            return None
        j = session_start(fr, i)
        if j is None:
            return None
        m = next(
            (k for k in range(i, j - 1, -1) if self._closes_at(fr, k) == self.measure_at), None
        )
        if m is None:
            return None  # the measurement bar is missing -> fail closed
        if self.anchor == "open":
            base = float(fr["open"][j])
        else:
            if j == 0:
                return None  # no previous session in the frame
            base = float(fr["close"][j - 1])
        move = (float(fr["close"][m]) / base - 1) * 100
        if not np.isfinite(move) or abs(move) < self.min_move_pct:
            return None
        direction: Direction = "long" if move > 0 else "short"
        if self.nifty is not None:
            assert self.panel is not None
            nr = self.panel.at(fr.index[i]).get(self.panel.index_name)
            if nr is None:
                return None
            if self.nifty == "trend" and not (
                np.sign(nr) == np.sign(move) and abs(nr) >= self.nifty_pct
            ):
                return None
            if self.nifty == "range" and not abs(nr) < self.nifty_pct:
                return None
        return wide_candidate(symbol, self.name, direction, fr, i, j, cfg, self.min_stop_pct)


class RelativeStrength:
    """At ``decide_at``, rank symbols by return since open minus NIFTY's (rel).

    NIFTY up >= ``nifty_pct``: long the max-rel symbol if rel > 0 and its own move > 0.
    NIFTY down <= -``nifty_pct``: short the min-rel symbol if rel < 0 and its own move < 0.
    Otherwise nothing. Ties break alphabetically. Only the chosen symbol gets a candidate.
    """

    def __init__(
        self,
        name: str,
        panel: CrossSection,
        decide_at: str = "10:15",
        nifty_pct: float = 0.2,
        min_stop_pct: float = 0.6,
        bar_minutes: int = 5,
    ) -> None:
        self.name, self.panel = name, panel
        self.decide_at, self.nifty_pct, self.min_stop_pct = (
            _hhmm(decide_at),
            nifty_pct,
            min_stop_pct,
        )
        self.bar = pd.Timedelta(minutes=bar_minutes)

    def pick(self, ts: pd.Timestamp) -> tuple[str, Direction] | None:
        row = self.panel.at(ts)
        nr = row.pop(self.panel.index_name, None)
        if nr is None or not row:
            return None
        names = sorted(row)
        rel = {s: row[s] - nr for s in names}
        if nr >= self.nifty_pct:
            best = max(names, key=lambda s: rel[s])  # max() keeps the first (alphabetical) tie
            return (best, "long") if rel[best] > 0 and row[best] > 0 else None
        if nr <= -self.nifty_pct:
            worst = min(names, key=lambda s: rel[s])
            return (worst, "short") if rel[worst] < 0 and row[worst] < 0 else None
        return None

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if (fr.index[i] + self.bar).time() != self.decide_at:
            return None
        j = session_start(fr, i)
        if j is None:
            return None
        chosen = self.pick(fr.index[i])
        if chosen is None or chosen[0] != symbol:
            return None
        return wide_candidate(symbol, self.name, chosen[1], fr, i, j, cfg, self.min_stop_pct)
