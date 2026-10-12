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
        prev = fr["price_vs_vwap_pct"][i - LOOKBACK : i]
        if not finite(fr, i - 1, "price_vs_vwap_pct") or prev.size < LOOKBACK:
            return None
        if cur > 0 and prev[-1] <= 0 and prev.min() <= -MIN_DEPTH_PCT:
            return make_candidate(symbol, self.name, "long", fr, i, cfg)
        if cur < 0 and prev[-1] >= 0 and prev.max() >= MIN_DEPTH_PCT:
            return make_candidate(symbol, self.name, "short", fr, i, cfg)
        return None
