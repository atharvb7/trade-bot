"""VWAP reclaim (long) / rejection (short) after a sustained stretch on the other side."""

from __future__ import annotations

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Frame, finite, make_candidate

LOOKBACK = 5
MIN_DEPTH_PCT = 0.10  # price must have been at least this far on the other side of VWAP
MIN_MINUTES_SINCE_OPEN = 20


class VWAPReclaim:
    name = "vwap_reclaim"

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < LOOKBACK or not finite(fr, i, "price_vs_vwap_pct", "atr_14", "minutes_since_open"):
            return None
        if fr["minutes_since_open"][i] < MIN_MINUTES_SINCE_OPEN:
            return None
        cur = fr["price_vs_vwap_pct"][i]
        # Lookback stays inside today's session: yesterday's distance to yesterday's VWAP
        # says nothing about today's (matters on 5m/15m bars soon after the open).
        day = fr.index[i].normalize()
        lo = i - LOOKBACK
        while lo < i and fr.index[lo].normalize() != day:
            lo += 1
        prev = fr["price_vs_vwap_pct"][lo:i]
        if prev.size == 0 or not finite(fr, i - 1, "price_vs_vwap_pct"):
            return None
        if cur > 0 and prev[-1] <= 0 and prev.min() <= -MIN_DEPTH_PCT:
            return make_candidate(symbol, self.name, "long", fr, i, cfg)
        if cur < 0 and prev[-1] >= 0 and prev.max() >= MIN_DEPTH_PCT:
            return make_candidate(symbol, self.name, "short", fr, i, cfg)
        return None
