"""Hand-made candle tests for the fade detectors, plus a no-future-bars check on real features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bot.config import DetectorCfg
from bot.data.synthetic import make_1m
from bot.detectors.base import Detector, Frame
from bot.detectors.fades import FailedORBFade, GapFade, RSI2Fade, VWAPFade, rsi2_last
from bot.features.engine import bar_table
from bot.features.indicators import rsi

CFG = DetectorCfg()


def bars15(
    rows: list[tuple[float, float, float, float]], start: str = "2026-01-05 09:15", **extra: object
) -> Frame:
    idx = pd.date_range(start, periods=len(rows), freq="15min")
    o, h, lo, c = (np.array(x, dtype=float) for x in zip(*rows, strict=True))
    cols = {"open": o, "high": h, "low": lo, "close": c, "atr_14": np.full(len(rows), 0.5)}
    for k, v in extra.items():
        cols[k] = np.broadcast_to(np.asarray(v, dtype=float), len(rows)).copy()
    return Frame(cols, idx)


def flat(closes: list[float]) -> list[tuple[float, float, float, float]]:
    return [(c, c + 0.1, c - 0.1, c) for c in closes]


# ---------------- VWAP fade ----------------


def vwap_frame(closes: list[float], vwap: float = 100.0, **kw: object) -> Frame:
    c = np.array(closes)
    return bars15(flat(closes), vwap=vwap, price_vs_vwap_pct=(c / vwap - 1) * 100, **kw)


def test_vwap_fade_short_on_fresh_stretch_target_vwap_stop_1to1() -> None:
    fr = vwap_frame([100.2, 100.5, 101.2])
    c = VWAPFade(1.0).detect("X", fr, 2, CFG)
    assert c and c.direction == "short" and c.setup == "vwap_fade1"
    assert c.target == 100.0 and c.stop == pytest.approx(102.4) and c.entry == 101.2


def test_vwap_fade_long_mirror_and_threshold() -> None:
    fr = vwap_frame([99.8, 99.5, 98.8])
    c = VWAPFade(1.0).detect("X", fr, 2, CFG)
    assert c and c.direction == "long" and c.stop == pytest.approx(97.6) and c.target == 100.0
    assert VWAPFade(1.5).detect("X", fr, 2, CFG) is None  # 1.2% < 1.5%


def test_vwap_fade_needs_fresh_cross_same_session() -> None:
    fr = vwap_frame([100.2, 101.1, 101.3])
    assert VWAPFade(1.0).detect("X", fr, 2, CFG) is None  # previous bar already stretched
    two_days = Frame(
        fr.cols,
        pd.DatetimeIndex(["2026-01-05 15:15", "2026-01-06 09:15", "2026-01-06 09:30"]),
    )
    two_days.cols["price_vs_vwap_pct"] = np.array([0.2, 1.2, 1.3])
    assert VWAPFade(1.0).detect("X", two_days, 1, CFG) is None  # prev bar is yesterday


def test_vwap_fade_confirm_reversal_stop_at_session_high() -> None:
    rows = [
        (100.0, 100.3, 99.9, 100.2),
        (100.2, 101.6, 100.1, 101.4),  # stretched 1.4% (session high 101.6)
        (101.4, 101.5, 101.0, 101.3),
        (101.3, 101.35, 100.7, 100.8),  # closes below previous low 101.0, still 0.8% above
        (100.8, 100.9, 100.6, 100.7),
        (100.7, 101.0, 100.5, 100.65),  # closes below previous low again: not the first
    ]
    c_ = np.array([r[3] for r in rows])
    fr = bars15(rows, vwap=100.0, price_vs_vwap_pct=(c_ / 100 - 1) * 100)
    det = VWAPFade(1.0, confirm=True)
    assert det.detect("X", fr, 2, CFG) is None  # no reversal bar yet
    c = det.detect("X", fr, 3, CFG)
    assert c and c.direction == "short" and c.setup == "vwap_fade1_confirm"
    assert c.stop == pytest.approx(101.6) and c.target == 100.0
    assert det.detect("X", fr, 5, CFG) is None


def test_vwap_fade_confirm_risk_floor() -> None:
    rows = [
        (100.0, 100.3, 99.9, 100.2),
        (100.2, 101.2, 101.0, 101.1),
        (101.1, 101.15, 100.85, 100.9),  # high of day 101.2 is only 0.3 above entry
    ]
    c_ = np.array([r[3] for r in rows])
    fr = bars15(rows, vwap=100.0, price_vs_vwap_pct=(c_ / 100 - 1) * 100)
    c = VWAPFade(1.0, confirm=True).detect("X", fr, 2, CFG)
    assert c and c.stop == pytest.approx(100.9 * 1.006)


# ---------------- failed opening-range breakout ----------------

RANGE = [(100, 101, 99.5, 100.5), (100.5, 100.8, 99, 100)]  # 30-min range 99..101


def test_failed_orb_short_after_close_back_inside() -> None:
    fr = bars15([*RANGE, (100, 101.8, 99.9, 101.5), (101.5, 101.6, 100.4, 100.5)])
    det = FailedORBFade(30, rr=1.0)
    assert det.detect("X", fr, 2, CFG) is None  # the breakout bar itself
    c = det.detect("X", fr, 3, CFG)
    assert c and c.direction == "short" and c.setup == "failed_orb30"
    assert c.stop == pytest.approx(101.8) and c.target == pytest.approx(100.5 - 1.3)


def test_failed_orb_long_with_risk_floor() -> None:
    fr = bars15([*RANGE, (99.2, 99.3, 98.8, 98.9), (98.9, 99.4, 98.85, 99.2)])
    c = FailedORBFade(30, rr=1.0).detect("X", fr, 3, CFG)
    assert c and c.direction == "long"
    risk = 99.2 * 0.006  # session low 98.8 is only 0.4 below -> floored
    assert c.stop == pytest.approx(99.2 - risk) and c.target == pytest.approx(99.2 + risk)


def test_failed_orb_only_first_failure_per_side() -> None:
    fr = bars15(
        [
            *RANGE,
            (100, 101.8, 99.9, 101.5),
            (101.5, 101.6, 100.4, 100.5),
            (100.5, 101.5, 100.4, 101.3),
            (101.3, 101.4, 100.6, 100.7),
        ]
    )
    det = FailedORBFade(30)
    assert det.detect("X", fr, 3, CFG) is not None
    assert det.detect("X", fr, 5, CFG) is None


def test_failed_orb_ignores_bars_inside_range_window() -> None:
    rows = [(100, 101, 99.5, 100.5), (100.5, 100.8, 99, 100), (100, 100.6, 99.8, 100.3)]
    fr = bars15(rows)
    assert FailedORBFade(60).detect("X", fr, 2, CFG) is None  # 60-min range not closed yet


# ---------------- gap fade ----------------


def gap_frame(gap: float, room: float, start: str = "2026-01-05 09:15") -> Frame:
    return bars15(flat([101.0, 101.1]), start=start, gap_pct=gap, dist_prev_close_pct=room)


def test_gap_fade_short_toward_previous_close() -> None:
    fr = gap_frame(1.5, 1.0)
    c = GapFade(1.0).detect("X", fr, 0, CFG)
    pc = 101.0 / 1.01
    assert c and c.direction == "short" and c.target == pytest.approx(pc)
    assert c.stop == pytest.approx(101.0 + (101.0 - pc))


def test_gap_fade_long_and_filters() -> None:
    c = GapFade(1.0).detect("X", gap_frame(-1.2, -0.8), 0, CFG)
    assert c and c.direction == "long" and c.target == pytest.approx(101.0 / 0.992)
    assert GapFade(1.0).detect("X", gap_frame(0.8, 0.8), 0, CFG) is None  # gap too small
    assert GapFade(1.0).detect("X", gap_frame(1.5, 0.4), 0, CFG) is None  # mostly filled
    assert GapFade(1.0).detect("X", gap_frame(1.5, 1.0), 1, CFG) is None  # only 09:30 close
    late = gap_frame(1.5, 1.0, start="2026-01-05 09:30")
    assert GapFade(1.0).detect("X", late, 0, CFG) is None  # session open missing


def test_gap_fade_bar_size_aware() -> None:
    idx = pd.date_range("2026-01-05 09:15", periods=4, freq="5min")
    one = np.ones(4)
    fr = Frame(
        {
            "open": 101 * one,
            "high": 101.1 * one,
            "low": 100.9 * one,
            "close": 101 * one,
            "gap_pct": 1.5 * one,
            "dist_prev_close_pct": one,
        },
        idx,
    )
    det = GapFade(1.0, bar_minutes=5)
    assert [det.detect("X", fr, i, CFG) is not None for i in range(4)] == [0, 0, 1, 0]


# ---------------- RSI(2) ----------------


def test_rsi2_matches_indicator() -> None:
    rng = np.random.default_rng(1)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 0.3, 120)))
    ref = rsi(s, 2).to_numpy()
    prev, now = rsi2_last(s.to_numpy()[-41:])
    assert prev == pytest.approx(ref[-2], abs=1e-6) and now == pytest.approx(ref[-1], abs=1e-6)


def rsi_frame(trend_up: float) -> Frame:
    closes = [100 + 0.1 * k + (0.05 if k % 2 else 0) for k in range(42)] + [104.3, 101.5]
    return bars15(flat(closes), start="2026-01-01 09:15", ema21_gt_50=trend_up)


def test_rsi2_long_only_with_uptrend_filter() -> None:
    i = 43
    fr = rsi_frame(1.0)
    c = RSI2Fade(10, 90, trend=True).detect("X", fr, i, CFG)
    assert c and c.direction == "long" and c.setup == "rsi2_trend"
    assert c.stop == pytest.approx(101.5 - 1.0) and c.target == pytest.approx(101.5 + 1.0)
    assert RSI2Fade(10, 90, trend=True).detect("X", rsi_frame(0.0), i, CFG) is None
    assert RSI2Fade(5, 95, trend=False).detect("X", rsi_frame(0.0), i, CFG) is not None
    assert RSI2Fade(10, 90).detect("X", fr, i - 1, CFG) is None  # still overbought, not long


# ---------------- no future bars ----------------

DETECTORS: list[Detector] = [
    VWAPFade(0.5),
    VWAPFade(0.5, confirm=True, min_room_pct=0.2),
    FailedORBFade(30),
    FailedORBFade(60),
    GapFade(0.5),
    RSI2Fade(10, 90, trend=True),
    RSI2Fade(5, 95, trend=False),
]


def _real_frame() -> Frame:
    df = make_1m(days=12, seed=3)
    day = pd.DatetimeIndex(df.index).normalize()
    k = pd.Series(np.arange(len(day.unique())), index=day.unique()).reindex(day).to_numpy()
    df = df.mul(np.where(k % 2, 1.012, 0.988), axis=0).assign(volume=df["volume"])  # add gaps
    nifty = make_1m(days=12, seed=4, base=20000)
    return Frame.from_df(bar_table(df, nifty, 15))


def _cut(fr: Frame, n: int) -> Frame:
    return Frame({k: v[:n].copy() for k, v in fr.cols.items()}, fr.index[:n])


def _scramble_after(fr: Frame, i: int, seed: int) -> Frame:
    rng = np.random.default_rng(seed)
    cols = {}
    for k, v in fr.cols.items():
        w = v.astype(float).copy()
        w[i + 1 :] = w[i + 1 :] * rng.uniform(0.9, 1.1, len(w) - i - 1)
        cols[k] = w
    return Frame(cols, fr.index)


@pytest.mark.parametrize("det", DETECTORS, ids=lambda d: d.name)
def test_signal_never_depends_on_future_bars(det: Detector) -> None:
    fr = _real_frame()
    fired = 0
    for i in range(len(fr) - 1):
        full = det.detect("X", fr, i, CFG)
        cut = det.detect("X", _cut(fr, i + 1), i, CFG)
        scr = det.detect("X", _scramble_after(fr, i, i), i, CFG)
        assert (full is None) == (cut is None) == (scr is None), i
        if full is not None:
            fired += 1
            for other in (cut, scr):
                assert other is not None
                assert (other.direction, other.entry, other.stop, other.target) == (
                    full.direction,
                    full.entry,
                    full.stop,
                    full.target,
                )
    assert fired > 0, "test is vacuous: detector never fired on the synthetic data"
