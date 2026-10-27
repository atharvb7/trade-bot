"""Hand-made 5-minute candles for IntradayMomentum, RelativeStrength and CrossSection."""

import numpy as np
import pandas as pd
import pytest

from bot.backtest.engine import Backtester
from bot.config import DetectorCfg, load_config
from bot.detectors.base import Frame
from bot.detectors.cross_section import CrossSection
from bot.detectors.momentum import IntradayMomentum, RelativeStrength

CFG = DetectorCfg(atr_stop_mult=1.0, reward_risk=3.0)
DAY = "2026-01-05"


def day_bars(
    closes: list[float], start: str = f"{DAY} 09:15", open0: float | None = None, wick: float = 0.05
) -> pd.DataFrame:
    """5m bars: open = previous close (or open0), high/low = max/min(open, close) +/- wick."""
    idx = pd.date_range(start, periods=len(closes), freq="5min")
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[open0 if open0 is not None else c[0]], c[:-1]])
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) + wick,
            "low": np.minimum(o, c) - wick,
            "close": c,
            "atr_14": 0.5,
        },
        index=idx,
    )


def fr(*parts: pd.DataFrame) -> Frame:
    return Frame.from_df(pd.concat(parts))


def ramp(
    start: float, end: float, n: int = 12, tail: int = 0, tail_px: float | None = None
) -> list[float]:
    """n bars from 09:15 rising linearly to ``end`` (the 10:10 bar closes at 10:15), then a tail."""
    xs = list(np.linspace(start, end, n))
    return xs + [tail_px if tail_px is not None else end] * tail


I_1015 = 11  # bar opening 10:10 closes 10:15


def test_long_on_morning_up_move_at_decision_bar_only() -> None:
    f = fr(day_bars(ramp(100, 101, tail=5), open0=100))
    det = IntradayMomentum("m1", "10:15", 0.5)
    c = det.detect("X", f, I_1015, CFG)
    assert c and c.direction == "long" and c.setup == "m1"
    assert c.entry == pytest.approx(101.0)
    assert c.stop == pytest.approx(100 - 0.05)  # session low is further than the 0.6% floor
    assert c.target == pytest.approx(101 + 3 * (101 - 99.95))
    for k in (I_1015 - 1, I_1015 + 1):
        assert det.detect("X", f, k, CFG) is None


def test_short_and_threshold() -> None:
    f = fr(day_bars(ramp(100, 99.3, tail=2), open0=100))
    c = IntradayMomentum("m1", "10:15", 0.5).detect("X", f, I_1015, CFG)
    assert c and c.direction == "short" and c.stop == pytest.approx(100 + 0.05)
    small = fr(day_bars(ramp(100, 100.4), open0=100))
    assert IntradayMomentum("m1", "10:15", 0.5).detect("X", small, I_1015, CFG) is None


def test_stop_floor_when_extreme_is_close() -> None:
    # +0.55% move with no dip: session low (the 100 open) is 0.55% away, inside the 0.6% floor
    f = fr(day_bars(ramp(100, 100.55), open0=100.0, wick=0.0))
    c = IntradayMomentum("m1", "10:15", 0.5).detect("X", f, I_1015, CFG)
    assert c and c.direction == "long"
    assert c.stop == pytest.approx(100.55 * (1 - 0.006))


def test_prev_close_anchor_and_late_measurement() -> None:
    prev = day_bars([98.0] * 75, start="2026-01-02 09:15")
    today = day_bars([100.0] * 60, open0=100.0)  # gap up 2.04%, flat afterwards
    f = fr(prev, today)
    i0 = 75
    gap = IntradayMomentum("m2", "10:15", 0.75, anchor="prev_close")
    c = gap.detect("X", f, i0 + I_1015, CFG)
    assert c and c.direction == "long"
    assert IntradayMomentum("m1", "10:15", 0.5).detect("X", f, i0 + I_1015, CFG) is None
    gao = IntradayMomentum("m8", "14:30", 0.5, anchor="prev_close", measure_at="09:45")
    f = fr(prev, day_bars([100.0] * 70, open0=100.0))
    i_1430 = i0 + 62  # bar opening 09:15 + 62 x 5 min = 14:25 closes at 14:30
    c = gao.detect("X", f, i_1430, CFG)
    assert c and c.direction == "long" and c.ts == pd.Timestamp(f"{DAY} 14:25")


def test_missing_session_open_or_previous_session() -> None:
    late = fr(day_bars(ramp(100, 101), start=f"{DAY} 09:20", open0=100))
    assert IntradayMomentum("m1", "10:15", 0.5).detect("X", late, I_1015 - 1, CFG) is None
    alone = fr(day_bars(ramp(100, 101), open0=100))
    assert (
        IntradayMomentum("m2", "10:15", 0.5, anchor="prev_close").detect("X", alone, I_1015, CFG)
        is None
    )


def universe(
    moves: dict[str, float], nifty: float, tail: int = 10
) -> tuple[dict[str, Frame], Frame]:
    frames = {
        s: fr(day_bars(ramp(100, 100 * (1 + m / 100), tail=tail), open0=100))
        for s, m in moves.items()
    }
    idx = fr(day_bars(ramp(20000, 20000 * (1 + nifty / 100), tail=tail), open0=20000))
    return frames, idx


def test_nifty_regime_filters() -> None:
    frames, idx = universe({"X": 1.0}, nifty=0.5)
    panel = CrossSection.from_frames(frames, idx)
    trend = IntradayMomentum("m4", "10:15", 0.5, nifty="trend", nifty_pct=0.3, panel=panel)
    rng = IntradayMomentum("m5", "10:15", 0.5, nifty="range", nifty_pct=0.3, panel=panel)
    assert trend.detect("X", frames["X"], I_1015, CFG) is not None
    assert rng.detect("X", frames["X"], I_1015, CFG) is None
    frames, idx = universe({"X": 1.0}, nifty=-0.5)  # index against the stock
    panel = CrossSection.from_frames(frames, idx)
    trend = IntradayMomentum("m4", "10:15", 0.5, nifty="trend", nifty_pct=0.3, panel=panel)
    assert trend.detect("X", frames["X"], I_1015, CFG) is None
    frames, idx = universe({"X": 1.0}, nifty=0.1)
    panel = CrossSection.from_frames(frames, idx)
    rng = IntradayMomentum("m5", "10:15", 0.5, nifty="range", nifty_pct=0.3, panel=panel)
    assert rng.detect("X", frames["X"], I_1015, CFG) is not None


def signals(det: RelativeStrength, frames: dict[str, Frame], i: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for s, f in frames.items():
        c = det.detect(s, f, i, CFG)
        if c is not None:
            out[s] = c.direction
    return out


def test_relative_strength_picks_one_stock_in_index_direction() -> None:
    frames, idx = universe({"A": 0.8, "B": 1.5, "C": -0.2}, nifty=0.4)
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx), "10:15", 0.2)
    assert signals(det, frames, I_1015) == {"B": "long"}
    frames, idx = universe({"A": -0.8, "B": -1.5, "C": 0.2}, nifty=-0.4)
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx), "10:15", 0.2)
    assert signals(det, frames, I_1015) == {"B": "short"}
    frames, idx = universe({"A": -0.8, "B": 1.5}, nifty=0.1)  # flat index -> nothing
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx), "10:15", 0.2)
    assert signals(det, frames, I_1015) == {}
    assert signals(det, frames, I_1015 + 1) == {}


def test_relative_strength_requires_outperformance_and_breaks_ties_alphabetically() -> None:
    frames, idx = universe({"A": 0.3, "B": 0.2}, nifty=0.5)  # all lag the index
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx), "10:15", 0.2)
    assert signals(det, frames, I_1015) == {}
    frames, idx = universe({"B": 1.0, "A": 1.0}, nifty=0.5)
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx), "10:15", 0.2)
    assert signals(det, frames, I_1015) == {"A": "long"}


def _mutate_after(f: Frame, ts: pd.Timestamp, factor: float) -> Frame:
    cols = {k: v.copy() for k, v in f.cols.items()}
    after = f.index > ts
    for k in ("open", "high", "low", "close"):
        cols[k][after] = cols[k][after] * factor
    return Frame(cols, f.index)


def test_future_bars_do_not_change_signals() -> None:
    moves = {"A": 0.8, "B": 1.5, "C": -0.9}
    frames, idx = universe(moves, nifty=0.4, tail=40)
    ts = frames["A"].index[I_1015]
    base_xs = signals(RelativeStrength("m6", CrossSection.from_frames(frames, idx)), frames, I_1015)
    base_ts = {s: IntradayMomentum("m1").detect(s, f, I_1015, CFG) for s, f in frames.items()}
    base_trend = IntradayMomentum("m4", nifty="trend", panel=CrossSection.from_frames(frames, idx))
    base_tr = {s: base_trend.detect(s, f, I_1015, CFG) is None for s, f in frames.items()}
    for factor in (0.9, 1.1):  # rewrite every symbol's AND the index's future bars
        fut = {s: _mutate_after(f, ts, factor) for s, f in frames.items()}
        fut_idx = _mutate_after(idx, ts, 1 / factor)
        panel = CrossSection.from_frames(fut, fut_idx)
        assert signals(RelativeStrength("m6", panel), fut, I_1015) == base_xs
        trend = IntradayMomentum("m4", nifty="trend", panel=panel)
        for s, f in fut.items():
            c, b = IntradayMomentum("m1").detect(s, f, I_1015, CFG), base_ts[s]
            assert (c is None) == (b is None)
            if c is not None and b is not None:
                assert (c.direction, c.entry, c.stop, c.target) == (
                    b.direction,
                    b.entry,
                    b.stop,
                    b.target,
                )
            assert (trend.detect(s, f, I_1015, CFG) is None) == base_tr[s]
    assert base_xs == {"B": "long"} and base_tr == {"A": False, "B": False, "C": True}


def test_panel_is_as_of_and_same_day_only() -> None:
    frames, idx = universe({"A": 1.0}, nifty=0.5)
    gap = {
        "A": Frame.from_df(
            pd.DataFrame(frames["A"].cols, index=frames["A"].index).drop(frames["A"].index[I_1015])
        )
    }
    panel = CrossSection.from_frames(gap, idx)
    ts = frames["A"].index[I_1015]
    # A's 10:10 bar is missing: use its last closed value (10:05 bar), never a later one
    expect = (frames["A"]["close"][I_1015 - 1] / 100 - 1) * 100
    assert panel.at(ts)["A"] == pytest.approx(expect)
    assert panel.at(pd.Timestamp("2026-01-06 09:10")) == {}  # next day before any bar


def test_backtester_runs_relative_strength_one_trade_with_time_exit() -> None:
    """Same Backtester code path: one stock picked, filled next bar, squared off at 15:10."""
    moves = {"A": 0.8, "B": 1.5, "C": -0.9}
    frames, idx = universe(moves, nifty=0.4, tail=63)  # 12 + 63 bars = whole session to 15:25
    cfg = load_config()
    cfg.app.detectors.reward_risk = 3.0
    det = RelativeStrength("m6", CrossSection.from_frames(frames, idx))
    res = Backtester(cfg, frames, detectors=[det], bar_minutes=5).run()
    assert len(res.trades) == 1
    t = res.trades.iloc[0]
    assert t["symbol"] == "B" and t["direction"] == "long"
    assert t["entry_ts"] == pd.Timestamp(f"{DAY} 10:15")
    assert t["exit_reason"] == "square_off" and t["exit_ts"] == pd.Timestamp(f"{DAY} 15:10")
