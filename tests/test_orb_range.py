import numpy as np
import pandas as pd

from bot.config import DetectorCfg
from bot.detectors.base import Frame
from bot.detectors.orb_range import RangeORB

CFG = DetectorCfg(atr_stop_mult=1.0, reward_risk=2.0)


def bars15(rows: list[tuple[float, float, float, float]], start: str = "2026-01-05 09:15") -> Frame:
    idx = pd.date_range(start, periods=len(rows), freq="15min")
    o, h, lo, c = (np.array(x, dtype=float) for x in zip(*rows, strict=True))
    return Frame(
        {"open": o, "high": h, "low": lo, "close": c, "atr_14": np.full(len(rows), 0.5)}, idx
    )


# 09:15 and 09:30 bars form the 30-minute range: high 101, low 99
RANGE = [(100, 101, 99.5, 100.5), (100.5, 100.8, 99, 100)]


def test_long_break_stop_at_range_low_target_2r() -> None:
    fr = bars15([*RANGE, (100, 101.5, 99.9, 101.4)])
    c = RangeORB(30).detect("X", fr, 2, CFG)
    assert c and c.direction == "long" and c.setup == "orb30_range"
    assert c.stop == 99 and c.entry == 101.4
    assert c.target == 101.4 + 2 * (101.4 - 99)


def test_short_break_stop_at_range_high() -> None:
    fr = bars15([*RANGE, (100, 100.2, 98.5, 98.6)])
    c = RangeORB(30).detect("X", fr, 2, CFG)
    assert c and c.direction == "short" and c.stop == 101
    assert c.target == 98.6 - 2 * (101 - 98.6)


def test_no_signal_inside_range_window_or_without_close_beyond() -> None:
    fr = bars15([(100, 101, 99.5, 100.5), (100.5, 102, 99, 101.8)])  # breaks while range forming
    assert RangeORB(30).detect("X", fr, 1, CFG) is None
    wick = bars15([*RANGE, (100, 101.6, 99.9, 100.9)])  # wick above, close inside
    assert RangeORB(30).detect("X", wick, 2, CFG) is None


def test_only_fresh_breaks() -> None:
    fr = bars15([*RANGE, (100, 101.5, 99.9, 101.4), (101.4, 101.9, 101.2, 101.8)])
    assert RangeORB(30).detect("X", fr, 3, CFG) is None  # previous close already beyond


def test_60_minute_range_uses_four_bars() -> None:
    rows = [
        (100, 101, 99.5, 100.5),
        (100.5, 100.8, 99, 100),
        (100, 102, 99.8, 101.5),
        (101.5, 101.7, 100.9, 101.2),
        (101.2, 102.4, 101.1, 102.3),
    ]
    fr = bars15(rows)
    assert RangeORB(60).detect("X", fr, 3, CFG) is None  # 10:00 bar is still inside the window
    c = RangeORB(60).detect("X", fr, 4, CFG)
    assert c and c.direction == "long" and c.stop == 99  # range low across all four bars


def test_missing_session_open_returns_none() -> None:
    fr = bars15([*RANGE, (100, 101.5, 99.9, 101.4)], start="2026-01-05 09:30")
    assert RangeORB(30).detect("X", fr, 2, CFG) is None
