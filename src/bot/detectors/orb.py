"""Opening range breakout: first close beyond the 15-min range, after it closed, on volume."""

from __future__ import annotations

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Frame, finite, make_candidate

MIN_VOLUME_RATIO = 1.5


class ORB:
    name = "opening_range_breakout"

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        if i < 1 or not finite(fr, i, "or_high", "or_low", "volume_vs_avg20", "atr_14"):
            return None
        if fr["volume_vs_avg20"][i] < MIN_VOLUME_RATIO:
            return None
        c, pc = fr["close"][i], fr["close"][i - 1]
        hi, lo = fr["or_high"][i], fr["or_low"][i]
        if c > hi and pc <= hi:
            return make_candidate(symbol, self.name, "long", fr, i, cfg)
        if c < lo and pc >= lo:
            return make_candidate(symbol, self.name, "short", fr, i, cfg)
        return None
