"""Mean-reversion (fade) detectors. docs/experiments/2026-10-27-mean-reversion.md.

Each detector looks only at bars ``<= i`` (the signal bar has closed). Stops are wide by
design (>= ~0.6% of price) so fees and slippage are a small fraction of risk. They take their
parameters in the constructor and ignore ``DetectorCfg``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Direction, Frame, finite
from bot.detectors.orb_range import RangeORB

SESSION_OPEN_MIN = 9 * 60 + 15


def session_start(fr: Frame, i: int) -> int | None:
    """Index of today's first bar, or None if the 09:15 bar is missing."""
    day = fr.index[i].normalize()
    j = i
    while j > 0 and fr.index[j - 1].normalize() == day:
        j -= 1
    if fr.index[j] != day + pd.Timedelta(minutes=SESSION_OPEN_MIN):
        return None
    return j


def _same_day(fr: Frame, a: int, b: int) -> bool:
    return bool(fr.index[a].normalize() == fr.index[b].normalize())


def _atr(fr: Frame, i: int) -> float:
    return float(fr["atr_14"][i]) if "atr_14" in fr.cols else float("nan")


def _fade(
    symbol: str,
    setup: str,
    direction: Direction,
    fr: Frame,
    i: int,
    stop: float,
    target: float,
) -> Candidate | None:
    entry = float(fr["close"][i])
    sign = 1 if direction == "long" else -1
    if sign * (target - entry) <= 0 or sign * (entry - stop) <= 0:
        return None
    return Candidate(symbol, setup, direction, fr.index[i], entry, stop, target, _atr(fr, i))


class VWAPFade:
    """Fade a stretch from session VWAP; target = VWAP at the signal bar.

    confirm=False: the close crosses ``min_dev_pct`` away from VWAP (previous bar was inside);
        stop is 1:1 (entry +/- distance to VWAP).
    confirm=True: the close was ``min_dev_pct`` away earlier today and this bar reverses
        (short: close < previous low; long: close > previous high) while still ``min_room_pct``
        from VWAP. First such signal per side per day. Stop = session extreme on the stretched
        side, risk floored at ``min_risk_pct`` of entry.
    """

    def __init__(
        self,
        min_dev_pct: float = 1.0,
        confirm: bool = False,
        min_room_pct: float = 0.6,
        min_risk_pct: float = 0.6,
    ) -> None:
        self.min_dev, self.confirm = min_dev_pct, confirm
        self.min_room, self.min_risk = min_room_pct, min_risk_pct
        self.name = f"vwap_fade{min_dev_pct:g}" + ("_confirm" if confirm else "")

    def _reversal(self, fr: Frame, j: int, k: int, side: Direction) -> bool:
        """Confirmed-reversal condition at bar k (session starts at j), using bars <= k only."""
        if k <= j:
            return False
        dev = fr["price_vs_vwap_pct"]
        before = dev[j:k]
        if not np.isfinite(dev[k]) or not np.isfinite(before).any():
            return False
        c = fr["close"][k]
        if side == "short":
            stretched = np.nanmax(before) >= self.min_dev
            return bool(stretched and c < fr["low"][k - 1] and dev[k] >= self.min_room)
        stretched = np.nanmin(before) <= -self.min_dev
        return bool(stretched and c > fr["high"][k - 1] and dev[k] <= -self.min_room)

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < 1 or not _same_day(fr, i - 1, i) or not finite(fr, i, "price_vs_vwap_pct", "vwap"):
            return None
        c, vwap = float(fr["close"][i]), float(fr["vwap"][i])
        dev = float(fr["price_vs_vwap_pct"][i])
        if not self.confirm:
            prev = float(fr["price_vs_vwap_pct"][i - 1])
            if not np.isfinite(prev):
                return None
            if dev >= self.min_dev and prev < self.min_dev:
                return _fade(symbol, self.name, "short", fr, i, c + (c - vwap), vwap)
            if dev <= -self.min_dev and prev > -self.min_dev:
                return _fade(symbol, self.name, "long", fr, i, c - (vwap - c), vwap)
            return None
        j = session_start(fr, i)
        if j is None:
            return None
        for side in ("short", "long"):
            side_d: Direction = "short" if side == "short" else "long"
            if not self._reversal(fr, j, i, side_d):
                continue
            if any(self._reversal(fr, j, k, side_d) for k in range(j + 1, i)):
                return None  # not the first confirmed reversal on this side today
            floor = self.min_risk / 100 * c
            if side_d == "short":
                risk = max(float(np.max(fr["high"][j : i + 1])) - c, floor)
                return _fade(symbol, self.name, "short", fr, i, c + risk, vwap)
            risk = max(c - float(np.min(fr["low"][j : i + 1])), floor)
            return _fade(symbol, self.name, "long", fr, i, c - risk, vwap)
        return None


class FailedORBFade:
    """Fade a failed opening-range breakout.

    The previous bar closed outside the ``or_minutes`` opening range and this bar closes back
    inside it. First failure per side per day. Stop = session extreme on the failed side, risk
    floored at ``min_risk_pct`` of entry. Target = ``rr`` x risk.
    """

    def __init__(self, or_minutes: int = 30, rr: float = 1.0, min_risk_pct: float = 0.6) -> None:
        self.rng = RangeORB(or_minutes)
        self.rr, self.min_risk = rr, min_risk_pct
        self.name = f"failed_orb{or_minutes}"

    @staticmethod
    def _failure(fr: Frame, k: int, hi: float, lo: float) -> Direction | None:
        pc, c = fr["close"][k - 1], fr["close"][k]
        if pc > hi and lo <= c <= hi:
            return "short"
        if pc < lo and lo <= c <= hi:
            return "long"
        return None

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < 1 or not _same_day(fr, i - 1, i):
            return None
        r = self.rng._range(fr, i)
        j = session_start(fr, i)
        if r is None or j is None:
            return None
        hi, lo, n = r
        side = self._failure(fr, i, hi, lo)
        if side is None:
            return None
        if any(self._failure(fr, k, hi, lo) == side for k in range(j + n + 1, i)):
            return None
        c = float(fr["close"][i])
        floor = self.min_risk / 100 * c
        if side == "short":
            risk = max(float(np.max(fr["high"][j : i + 1])) - c, floor)
            return _fade(symbol, self.name, "short", fr, i, c + risk, c - self.rr * risk)
        risk = max(c - float(np.min(fr["low"][j : i + 1])), floor)
        return _fade(symbol, self.name, "long", fr, i, c - risk, c + self.rr * risk)


class GapFade:
    """Fade an opening gap toward the previous close, on the first bar closing at 09:30.

    Needs |gap| >= ``min_gap_pct`` and the close still ``min_room_pct`` beyond the previous
    close on the gap side. Target = previous close; stop 1:1.
    """

    def __init__(
        self, min_gap_pct: float = 1.0, bar_minutes: int = 15, min_room_pct: float = 0.6
    ) -> None:
        self.min_gap, self.bar_minutes, self.min_room = min_gap_pct, bar_minutes, min_room_pct
        self.name = f"gap_fade{min_gap_pct:g}"

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        t0 = fr.index[i]
        first_entry = t0.normalize() + pd.Timedelta(hours=9, minutes=30)
        if not (t0 < first_entry <= t0 + pd.Timedelta(minutes=self.bar_minutes)):
            return None
        if session_start(fr, i) is None or not finite(fr, i, "gap_pct", "dist_prev_close_pct"):
            return None
        gap = float(fr["gap_pct"][i])
        room = float(fr["dist_prev_close_pct"][i])
        c = float(fr["close"][i])
        pc = c / (1 + room / 100)
        if gap >= self.min_gap and room >= self.min_room:
            return _fade(symbol, self.name, "short", fr, i, c + (c - pc), pc)
        if gap <= -self.min_gap and room <= -self.min_room:
            return _fade(symbol, self.name, "long", fr, i, c - (pc - c), pc)
        return None


def rsi2_last(close: np.ndarray) -> tuple[float, float]:
    """Wilder RSI(2) at the last two points of ``close`` (seeded at the window start).

    Same recursion as ``indicators.rsi`` (ewm alpha=1/2, adjust=False). With alpha = 1/2 the
    seed's weight after 40 bars is ~1e-12, so a 40-bar window matches the full-history value.
    """
    d = np.diff(close.astype(float))
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = up[0], dn[0]
    out = []
    for k in range(len(d)):
        if k:
            au += 0.5 * (up[k] - au)
            ad += 0.5 * (dn[k] - ad)
        out.append(100.0 if ad == 0 else 100 - 100 / (1 + au / ad))
    return out[-2], out[-1]


class RSI2Fade:
    """Short-term oversold/overbought fade on RSI(2) crossing an extreme.

    trend=True: longs only when EMA21 > EMA50, shorts only when EMA21 < EMA50 (same bars).
    Stop = ``atr_mult`` x ATR(14), target = ``rr`` x risk.
    """

    LOOKBACK = 40

    def __init__(
        self,
        lo: float = 10,
        hi: float = 90,
        trend: bool = True,
        atr_mult: float = 2.0,
        rr: float = 1.0,
    ) -> None:
        self.lo, self.hi, self.trend, self.atr_mult, self.rr = lo, hi, trend, atr_mult, rr
        self.name = "rsi2_trend" if trend else "rsi2_pure"

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < self.LOOKBACK or not finite(fr, i, "atr_14"):
            return None
        closes = fr["close"][i - self.LOOKBACK : i + 1]
        if not np.isfinite(closes).all():
            return None
        prev, now = rsi2_last(closes)
        up = fr["ema21_gt_50"][i] if "ema21_gt_50" in fr.cols else np.nan
        risk = self.atr_mult * float(fr["atr_14"][i])
        c = float(fr["close"][i])
        if now <= self.lo < prev and (not self.trend or up == 1.0):
            return _fade(symbol, self.name, "long", fr, i, c - risk, c + self.rr * risk)
        if now >= self.hi > prev and (not self.trend or up == 0.0):
            return _fade(symbol, self.name, "short", fr, i, c + risk, c - self.rr * risk)
        return None
