"""Backtest audit (docs/experiments/2026-10-27-backtest-audit.md): hand-made candles.

Pins the riskiest conventions (same-bar stop+target, short cost legs, N-minute bar timing,
engine == per-candidate R) and covers the bugs the audit fixed.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r
from bot.backtest.engine import Backtester
from bot.backtest.outcome import simulate_outcome
from bot.config import Config, load_config
from bot.data.synthetic import make_1m
from bot.detectors.base import Candidate, Frame, make_candidate
from bot.features.engine import compute_features
from bot.ml.dataset import build_dataset
from tests.test_backtester import zero_cost_cfg

Row = tuple[float, float, float, float]


class At:
    """Scripted detector: fires at the given bar positions."""

    name = "scripted"

    def __init__(self, *at: int, direction: str = "long") -> None:
        self.at, self.direction = set(at), direction

    def detect(self, symbol: str, fr: Frame, i: int, cfg) -> Candidate | None:  # type: ignore[no-untyped-def]
        if i not in self.at:
            return None
        return make_candidate(symbol, self.name, self.direction, fr, i, cfg)  # type: ignore[arg-type]


def bars(rows: list[Row], index: pd.DatetimeIndex | list[str], atr: float = 2.0) -> Frame:
    idx = pd.DatetimeIndex(index)
    assert len(idx) == len(rows)
    o, h, lo, c = (np.asarray(x, dtype=float) for x in zip(*rows, strict=True))
    n = len(rows)
    cols = {
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": np.full(n, 1000.0),
        "atr_14": np.full(n, atr),
        "volume_vs_avg20": np.ones(n),
    }
    return Frame(cols, idx)


def rng(start: str, n: int, minutes: int = 1) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=f"{minutes}min")


def bt(cfg: Config, fr: Frame, det: At, bm: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    res = Backtester(cfg, {"X": fr}, detectors=[det], bar_minutes=bm).run()  # type: ignore[list-item]
    return res.trades, res.decisions


def real_cost_cfg(slippage: float = 0.05) -> Config:
    cfg = load_config()
    cfg.costs.slippage_pct = slippage
    cfg.risk.min_edge_cost_multiple = 0.0
    return cfg


# ---------------------------------------------------------------- pinned conventions


def test_same_bar_stop_and_target_assumes_stop_short() -> None:
    # short at 100, ATR 2 -> stop 102, target 97; bar 1 spans both levels -> stop first.
    rows: list[Row] = [(100, 100, 100, 100), (100, 103, 96, 100), (100, 100, 100, 100)]
    fr = bars(rows, rng("2026-01-05 10:00", 3))
    trades, dec = bt(zero_cost_cfg(), fr, At(0, direction="short"))
    assert trades.iloc[0]["exit_reason"] == "stop" and trades.iloc[0]["exit_price"] == 102
    assert dec.iloc[0]["outcome"] == "stop" and dec.iloc[0]["label"] == 0


def test_short_cost_legs_sell_first_then_buy() -> None:
    cm = CostModel(load_config().costs)
    entry_v, exit_v = 10_000.0, 9_000.0
    assert cm.round_trip_fees("short", entry_v, exit_v) == pytest.approx(
        cm.leg_fees("sell", entry_v) + cm.leg_fees("buy", exit_v)
    )

    # Hand-computed: STT on the (opening) sell value, stamp on the (closing) buy value.
    def common(v: float) -> float:
        b, ex, sebi = v * 0.0003, v * 0.0000297, v * 0.000001
        return (b + ex + sebi) * 1.18

    expect = common(entry_v) + entry_v * 0.00025 + common(exit_v) + exit_v * 0.00003
    assert cm.round_trip_fees("short", entry_v, exit_v) == pytest.approx(expect)


def test_engine_short_trade_pnl_sign_and_costs() -> None:
    cfg = real_cost_cfg()
    rows: list[Row] = [(100, 100, 100, 100), (100, 100.5, 96, 97), (97, 97, 97, 97)]
    trades, _ = bt(cfg, bars(rows, rng("2026-01-05 10:00", 3)), At(0, direction="short"))
    t = trades.iloc[0]
    assert t["entry_price"] == pytest.approx(100 * (1 - 0.0005))  # sell receives less
    assert t["exit_reason"] == "target" and t["exit_price"] == 97  # limit buy, no slippage
    assert t["gross_pnl"] == pytest.approx(t["qty"] * (t["entry_price"] - 97))
    cm = CostModel(cfg.costs)
    fees = cm.round_trip_fees("short", t["entry_price"] * t["qty"], 97 * t["qty"])
    assert t["costs"] == pytest.approx(fees) and t["net_pnl"] == pytest.approx(
        t["gross_pnl"] - fees
    )


def test_stop_exit_slipped_target_exit_not() -> None:
    cfg = real_cost_cfg()
    rows: list[Row] = [(100, 100, 100, 100), (100, 100, 97, 98), (98, 98, 98, 98)]
    trades, _ = bt(cfg, bars(rows, rng("2026-01-05 10:00", 3)), At(0))
    assert trades.iloc[0]["exit_price"] == pytest.approx(98 * (1 - 0.0005))


def test_15m_signal_on_0915_bar_decides_at_0930_and_fills_at_next_open() -> None:
    rows: list[Row] = [(100, 100, 100, 100), (100.4, 101, 100, 100.5), (100.5,) * 4]  # type: ignore[list-item]
    fr = bars(rows, rng("2026-01-05 09:15", 3, 15))
    trades, dec = bt(zero_cost_cfg(), fr, At(0), bm=15)
    assert dec.iloc[0]["final_status"] == "filled"  # 09:15 bar closes 09:30 -> inside window
    t = trades.iloc[0]
    assert t["entry_ts"] == pd.Timestamp("2026-01-05 09:30") and t["entry_price"] == 100.4
    # Same bars at 1m spacing: the 09:15 bar closes 09:16 -> before 09:30 -> no entry.
    _, dec1 = bt(zero_cost_cfg(), bars(rows, rng("2026-01-05 09:15", 3)), At(0))
    assert dec1.iloc[0]["final_status"] == "rejected_risk_outside_entry_window"


def test_no_lookahead_15m_bars_including_nifty_trend() -> None:
    stock, nifty = make_1m(days=4, seed=1), make_1m(days=4, seed=2, base=20000)
    full = compute_features(stock, nifty, bar_minutes=15)
    assert (full["available_at"] == full.index + pd.Timedelta(minutes=15)).all()
    for cut in (400, 412, 777, 1100):  # 412 cuts inside a 15m bar
        part = compute_features(stock.iloc[:cut], nifty.iloc[:cut], bar_minutes=15)
        assert len(part) == cut // 15
        pd.testing.assert_frame_equal(
            part, full.iloc[: len(part)], check_exact=False, rtol=1e-9, atol=1e-9
        )
    # Shock Nifty inside the 15m bar that is still open at 10:00 (10:00-10:15 bar):
    # rows that closed at or before 10:00 must not move.
    shocked = nifty.copy()
    shocked.loc[shocked.index >= pd.Timestamp("2026-01-05 10:00"), "close"] *= 1.5
    after = compute_features(stock, shocked, bar_minutes=15)
    early = full["available_at"] <= pd.Timestamp("2026-01-05 10:00")
    pd.testing.assert_frame_equal(after[early], full[early])


def test_losing_streak_and_trade_count_reset_each_day() -> None:
    flat: Row = (100, 100, 100, 100)
    stop: Row = (100, 100, 97, 100)  # long stop at 98 hit
    day1 = [flat, stop, flat, flat, stop, flat, flat, flat]
    day2 = [flat, flat, flat]
    idx = rng("2026-01-05 10:00", 8).append(rng("2026-01-06 10:00", 3))
    trades, dec = bt(zero_cost_cfg(), bars(day1 + day2, idx), At(0, 3, 6, 8))
    assert len(trades) == 3 and (trades["exit_reason"].iloc[:2] == "stop").all()
    assert dec.iloc[2]["risk_reason"] == "losing_streak"
    assert dec.iloc[3]["final_status"] == "filled"  # new day: streak reset


# ---------------------------------------------------------------- fixed by the audit


def test_engine_net_r_equals_candidate_r_exactly() -> None:
    """Per-candidate R (edge.candidate_r and ml.dataset) must equal the engine's realised R."""
    cfg = real_cost_cfg()
    # signal close 100, next open 100.6 (gap up) -> fees must be on the fill, not the signal.
    rows: list[Row] = [(100, 100, 100, 100), (100.6, 104, 100.2, 103), (103,) * 4]  # type: ignore[list-item]
    fr = bars(rows, rng("2026-01-05 10:00", 3))
    trades, dec = bt(cfg, fr, At(0))
    t = trades.iloc[0]
    risk = 2.0  # |signal close - stop| = ATR 2 x 1.0
    engine_r = t["net_pnl"] / (t["qty"] * risk)
    d = candidate_r(dec, CostModel(cfg.costs))
    assert d["net_r"].iloc[0] == pytest.approx(engine_r, rel=0, abs=1e-12)
    ds = build_dataset({"X": fr}, cfg, 1, [At(0)])  # type: ignore[list-item]
    assert ds["net_r"].iloc[0] == pytest.approx(engine_r, rel=0, abs=1e-12)


def test_square_off_never_holds_past_1510_on_15m_bars() -> None:
    # 15m bars: 14:30 signal, 14:45 entry, 15:00 bar (15:00-15:15) contains 15:10.
    # Holding it would count a target hit between 15:10 and 15:15; must exit at its open.
    rows: list[Row] = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100, 104, 100, 103)]
    rows.append((103, 103, 103, 103))
    fr = bars(rows, rng("2026-01-05 14:30", 4, 15))
    trades, dec = bt(zero_cost_cfg(), fr, At(0), bm=15)
    t = trades.iloc[0]
    assert t["exit_reason"] == "square_off" and t["exit_ts"] == pd.Timestamp("2026-01-05 15:00")
    assert dec.iloc[0]["outcome"] == "timeout"
    c = make_candidate("X", "s", "long", fr, 0, load_config().app.detectors)
    assert c is not None
    out = simulate_outcome(c, fr, 0, 0.0, time(15, 10), bar_minutes=15)
    assert out.reason == "timeout" and out.exit_price == 100


def test_square_off_5m_still_at_1510() -> None:
    rows: list[Row] = [(100, 100, 100, 100)] + [(100, 100.5, 99.5, 100)] * 8
    fr = bars(rows, rng("2026-01-05 14:40", 9, 5))
    trades, _ = bt(zero_cost_cfg(), fr, At(0), bm=5)
    assert trades.iloc[0]["exit_ts"] == pd.Timestamp("2026-01-05 15:10")


def test_position_not_carried_overnight_when_day_ends_early() -> None:
    # Day 1 data stops at 14:05 (half day / missing bars); day 2 opens far below the stop.
    day1: list[Row] = [(100, 100, 100, 100)] + [(100, 100.5, 99.5, 100.2)] * 5
    day2: list[Row] = [(90, 90, 90, 90)] * 3
    idx = rng("2026-01-05 14:00", 6).append(rng("2026-01-06 09:15", 3))
    cfg = zero_cost_cfg()
    cfg.costs.slippage_pct = 0.05
    fr = bars(day1 + day2, idx)
    trades, _ = bt(cfg, fr, At(0))
    t = trades.iloc[0]
    assert t["exit_ts"] == pd.Timestamp("2026-01-05 14:05")
    assert t["exit_reason"] == "square_off_eod"
    assert t["exit_price"] == pytest.approx(100.2 * (1 - 0.0005))
    c = make_candidate("X", "s", "long", fr, 0, cfg.app.detectors)
    assert c is not None
    out = simulate_outcome(c, fr, 0, 0.05)
    assert out.reason == "timeout" and out.exit_price == pytest.approx(t["exit_price"])


def test_pending_order_not_filled_next_day() -> None:
    day1: list[Row] = [(100, 100, 100, 100)] * 2
    day2: list[Row] = [(100, 104, 99.5, 103)] * 3
    idx = rng("2026-01-05 14:00", 2).append(rng("2026-01-06 09:15", 3))
    trades, dec = bt(zero_cost_cfg(), bars(day1 + day2, idx), At(1))
    assert trades.empty
    assert dec.iloc[0]["final_status"] == "cancelled_eod"


def test_fill_never_exceeds_cash_after_gap() -> None:
    # Sized on the signal close (100): 9 shares fit in Rs 1,000. Next open gaps to 112:
    # 9 x 112 > 1,000 would breach rule 10 (no leverage), so the fill must shrink to 8.
    cfg = zero_cost_cfg()
    rows: list[Row] = [(100, 100, 100, 100), (112, 112, 112, 112), (112,) * 4]  # type: ignore[list-item]
    trades, _ = bt(cfg, bars(rows, rng("2026-01-05 10:00", 3), atr=0.5), At(0))
    t = trades.iloc[0]
    assert t["qty"] * t["entry_price"] <= cfg.app.starting_capital
    assert t["qty"] == 8
