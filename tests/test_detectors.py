import numpy as np
import pandas as pd

from bot.config import DetectorCfg
from bot.detectors import ORB, TrendPullback, VWAPReclaim
from bot.detectors.base import Frame
from tests.helpers import frame

CFG = DetectorCfg(atr_stop_mult=1.0, reward_risk=1.5)
NAN = np.nan


def test_orb_long_breakout_with_volume() -> None:
    close = [100, 100.5, 100.8, 101.5]
    fr = frame(4, close=close, or_high=101.0, or_low=99.0, volume_vs_avg20=2.0, atr_14=0.5)
    c = ORB().detect("X", fr, 3, CFG)
    assert c and c.direction == "long" and c.setup == "opening_range_breakout"
    assert c.entry == 101.5 and c.stop == 101.0 and c.target == 101.5 + 1.5 * 0.5


def test_orb_short_breakdown() -> None:
    fr = frame(
        3, close=[100, 99.5, 98.5], or_high=101.0, or_low=99.0, volume_vs_avg20=2.0, atr_14=0.5
    )
    c = ORB().detect("X", fr, 2, CFG)
    assert c and c.direction == "short" and c.stop == 99.0 and c.target == 98.5 - 0.75


def test_orb_needs_volume_and_fresh_break() -> None:
    low_vol = frame(
        2, close=[100, 101.5], or_high=101.0, or_low=99.0, volume_vs_avg20=1.0, atr_14=0.5
    )
    assert ORB().detect("X", low_vol, 1, CFG) is None
    already = frame(
        2, close=[101.4, 101.5], or_high=101.0, or_low=99.0, volume_vs_avg20=3.0, atr_14=0.5
    )
    assert ORB().detect("X", already, 1, CFG) is None  # not the first close beyond the range


def test_orb_ignores_inside_opening_window() -> None:
    fr = frame(2, close=[100, 105], or_high=NAN, or_low=NAN, volume_vs_avg20=3.0, atr_14=0.5)
    assert ORB().detect("X", fr, 1, CFG) is None


def test_vwap_reclaim_long_and_rejection_short() -> None:
    pv = [-0.2, -0.15, -0.1, -0.12, -0.05, 0.1]
    fr = frame(6, close=100.0, price_vs_vwap_pct=pv, atr_14=0.3, minutes_since_open=30.0)
    c = VWAPReclaim().detect("X", fr, 5, CFG)
    assert c and c.direction == "long"
    pv_s = [0.2, 0.15, 0.1, 0.12, 0.05, -0.1]
    fr = frame(6, close=100.0, price_vs_vwap_pct=pv_s, atr_14=0.3, minutes_since_open=30.0)
    c = VWAPReclaim().detect("X", fr, 5, CFG)
    assert c and c.direction == "short"


def test_vwap_reclaim_requires_depth_and_time() -> None:
    shallow = frame(
        6, close=100.0, price_vs_vwap_pct=[-0.02] * 5 + [0.05], atr_14=0.3, minutes_since_open=30.0
    )
    assert VWAPReclaim().detect("X", shallow, 5, CFG) is None
    early = frame(
        6, close=100.0, price_vs_vwap_pct=[-0.3] * 5 + [0.1], atr_14=0.3, minutes_since_open=10.0
    )
    assert VWAPReclaim().detect("X", early, 5, CFG) is None


def test_trend_pullback_long_and_short() -> None:
    base = dict(atr_14=0.4, rsi_14=50.0)
    up = frame(
        1,
        close=100.5,
        low=99.9,
        high=100.6,
        ema_21=100.0,
        ema9_gt_21=1.0,
        ema21_gt_50=1.0,
        price_vs_vwap_pct=0.2,
        **base,
    )
    c = TrendPullback().detect("X", up, 0, CFG)
    assert c and c.direction == "long"
    down = frame(
        1,
        close=99.5,
        low=99.4,
        high=100.1,
        ema_21=100.0,
        ema9_gt_21=0.0,
        ema21_gt_50=0.0,
        price_vs_vwap_pct=-0.2,
        **base,
    )
    c = TrendPullback().detect("X", down, 0, CFG)
    assert c and c.direction == "short"


def test_trend_pullback_rejects_no_touch_or_no_trend() -> None:
    no_touch = frame(
        1,
        close=101.0,
        low=100.5,
        high=101.2,
        ema_21=100.0,
        ema9_gt_21=1.0,
        ema21_gt_50=1.0,
        price_vs_vwap_pct=0.2,
        atr_14=0.4,
        rsi_14=50.0,
    )
    assert TrendPullback().detect("X", no_touch, 0, CFG) is None
    chop = frame(
        1,
        close=100.5,
        low=99.9,
        high=100.6,
        ema_21=100.0,
        ema9_gt_21=1.0,
        ema21_gt_50=0.0,
        price_vs_vwap_pct=0.2,
        atr_14=0.4,
        rsi_14=50.0,
    )
    assert TrendPullback().detect("X", chop, 0, CFG) is None


def test_vwap_reclaim_lookback_stays_in_today() -> None:
    # 5m bars: 09:35 is 20 min after open, so the 5-bar lookback would reach yesterday's
    # 15:25 bar. Yesterday's -0.5% must not count as today's "stretch below VWAP".
    idx = pd.DatetimeIndex(["2026-01-05 15:25"]).append(
        pd.date_range("2026-01-06 09:15", periods=5, freq="5min")
    )
    pv = [-0.5, 0.02, 0.02, 0.02, -0.02, 0.05]
    mins = [370.0, 0.0, 5.0, 10.0, 15.0, 20.0]
    fr = Frame(
        {
            "close": np.full(6, 100.0),
            "price_vs_vwap_pct": np.asarray(pv),
            "atr_14": np.full(6, 0.3),
            "minutes_since_open": np.asarray(mins),
        },
        idx,
    )
    assert VWAPReclaim().detect("X", fr, 5, CFG) is None
    # Control: the same depth today does trigger.
    fr.cols["price_vs_vwap_pct"] = np.asarray([0.0, -0.5, 0.02, 0.02, -0.02, 0.05])
    c = VWAPReclaim().detect("X", fr, 5, CFG)
    assert c is not None and c.direction == "long"
