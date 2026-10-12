"""Detector plumbing: a numpy-backed Frame and the Candidate record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np
import pandas as pd

from bot.config import DetectorCfg

Direction = Literal["long", "short"]


class Frame:
    """Column-name -> numpy array view of a symbol's bars (OHLCV + features). Index = open time."""

    def __init__(self, cols: dict[str, np.ndarray], index: pd.DatetimeIndex) -> None:
        self.cols = cols
        self.index = index

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> Frame:
        cols = {c: df[c].to_numpy() for c in df.columns}
        return cls(cols, pd.DatetimeIndex(df.index))

    def __getitem__(self, name: str) -> np.ndarray:
        return self.cols[name]

    def __len__(self) -> int:
        return len(self.index)


@dataclass
class Candidate:
    symbol: str
    setup: str
    direction: Direction
    ts: pd.Timestamp  # open time of the signal bar (bar closes at ts + 1 min)
    entry: float  # signal-bar close; the actual fill is next-bar open + slippage
    stop: float
    target: float
    atr: float
    features: dict[str, float] = field(default_factory=dict)


class Detector(Protocol):
    name: str

    def detect(self, symbol: str, fr: Frame, i: int, cfg: DetectorCfg) -> Candidate | None: ...


def make_candidate(
    symbol: str, setup: str, direction: Direction, fr: Frame, i: int, cfg: DetectorCfg
) -> Candidate | None:
    atr = float(fr["atr_14"][i])
    entry = float(fr["close"][i])
    if not np.isfinite(atr) or atr <= 0:
        return None
    risk = cfg.atr_stop_mult * atr
    sign = 1 if direction == "long" else -1
    return Candidate(
        symbol=symbol,
        setup=setup,
        direction=direction,
        ts=fr.index[i],
        entry=entry,
        stop=entry - sign * risk,
        target=entry + sign * cfg.reward_risk * risk,
        atr=atr,
    )


def finite(fr: Frame, i: int, *names: str) -> bool:
    return all(np.isfinite(fr[n][i]) for n in names)
