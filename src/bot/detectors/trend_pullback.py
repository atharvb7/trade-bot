"""Pullback to EMA21 inside an established trend (EMA9>21>50 and on the right side of VWAP)."""

from __future__ import annotations

from bot.config import DetectorCfg
from bot.detectors.base import Candidate, Frame, finite, make_candidate

RSI_LONG = (40.0, 60.0)
RSI_SHORT = (40.0, 60.0)


class TrendPullback:
    name = "trend_pullback"

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None:
        need = ("ema9_gt_21", "ema21_gt_50", "ema_21", "rsi_14", "price_vs_vwap_pct", "atr_14")
        if not finite(fr, i, *need):
            return None
        e21, c, lo, hi = fr["ema_21"][i], fr["close"][i], fr["low"][i], fr["high"][i]
        rsi = fr["rsi_14"][i]
        up = fr["ema9_gt_21"][i] == 1 and fr["ema21_gt_50"][i] == 1
        down = fr["ema9_gt_21"][i] == 0 and fr["ema21_gt_50"][i] == 0
        if (
            up
            and fr["price_vs_vwap_pct"][i] > 0
            and lo <= e21 < c
            and RSI_LONG[0] <= rsi <= RSI_LONG[1]
        ):
            return make_candidate(symbol, self.name, "long", fr, i, cfg)
        if (
            down
            and fr["price_vs_vwap_pct"][i] < 0
            and hi >= e21 > c
            and RSI_SHORT[0] <= rsi <= RSI_SHORT[1]
        ):
            return make_candidate(symbol, self.name, "short", fr, i, cfg)
        return None
