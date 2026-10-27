"""Execution realism: tick grid, trade-through limit entries, target fills, spread proxies."""

import numpy as np
import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r, day_bootstrap
from bot.backtest.engine import Backtester
from bot.backtest.fills import check_exit, limit_filled, limit_price, tick_size
from bot.backtest.liquidity import estimate_spreads
from bot.backtest.outcome import simulate_outcome
from bot.config import Config, CostsCfg, ExecutionCfg
from bot.detectors.base import Candidate
from tests.helpers import ohlc_frame
from tests.test_backtester import Scripted, path, zero_cost_cfg

LIMIT = ExecutionCfg(entry_order="limit", limit_cancel_bars=1)


def cand(direction: str = "long") -> Candidate:
    # signal close 100 (tick 0.01), stop 98 / target 103 for a long; mirrored for a short
    if direction == "long":
        return Candidate("X", "t", "long", pd.Timestamp("2026-01-05 10:00"), 100, 98, 103, 2)
    return Candidate("X", "t", "short", pd.Timestamp("2026-01-05 10:00"), 100, 102, 97, 2)


def test_tick_size_bands() -> None:
    assert tick_size(190.37) == 0.01 and tick_size(249.99) == 0.01
    assert tick_size(250) == 0.05 and tick_size(430.85) == 0.05
    assert tick_size(1500) == 0.10


def test_limit_price_offsets_away_from_market() -> None:
    assert limit_price("long", 300.0, 0) == pytest.approx(300.0)
    assert limit_price("long", 300.0, 1) == pytest.approx(299.95)
    assert limit_price("short", 300.0, 1) == pytest.approx(300.05)
    assert limit_price("long", 190.37, 2) == pytest.approx(190.35)


def test_limit_fills_only_when_traded_through() -> None:
    assert not limit_filled("long", 300.0, 301.0, 300.0)  # touch only
    assert limit_filled("long", 300.0, 301.0, 299.95)
    assert not limit_filled("short", 300.0, 300.0, 299.0)
    assert limit_filled("short", 300.0, 300.05, 299.0)


def test_target_through_needs_one_tick_beyond() -> None:
    assert check_exit("long", 98, 103, 100, 103.0, 99) == (103, "target")
    assert check_exit("long", 98, 103, 100, 103.0, 99, target_through=True) is None
    assert check_exit("long", 98, 103, 100, 103.01, 99, target_through=True) == (103, "target")
    assert check_exit("short", 102, 97, 100, 101, 97.0, target_through=True) is None
    assert check_exit("short", 102, 97, 100, 101, 96.99, target_through=True) == (97, "target")
    # stops still trigger on a touch
    assert check_exit("long", 98, 103, 100, 101, 98.0, target_through=True) == (98, "stop")


def test_market_entry_is_unchanged_by_default() -> None:
    fr = ohlc_frame([(100, 100, 100, 100), (101, 101.5, 100.9, 101.2), (101.2, 104, 101, 103)])
    out = simulate_outcome(cand(), fr, 0, 0.05)
    assert out.entry_price == pytest.approx(101 * 1.0005)
    assert out.reason == "target" and out.exit_ts == fr.index[2]


def test_limit_touch_only_is_not_filled() -> None:
    fr = ohlc_frame([(100, 100, 100, 100), (100.5, 101, 100.0, 100.2), (100.2, 100.3, 99, 99.5)])
    assert simulate_outcome(cand(), fr, 0, 0.05, execution=LIMIT).reason == "no_fill"
    # resting one bar longer catches the trade-through on bar 2
    ex = ExecutionCfg(entry_order="limit", limit_cancel_bars=2)
    out = simulate_outcome(cand(), fr, 0, 0.05, execution=ex)
    assert out.reason == "timeout" and out.entry_price == 100  # filled at the limit, no slippage


def test_limit_fill_at_limit_then_target() -> None:
    fr = ohlc_frame([(100, 100, 100, 100), (100.2, 100.4, 99.9, 100.1), (100.1, 103.5, 100, 103)])
    out = simulate_outcome(cand(), fr, 0, 0.05, execution=LIMIT)
    assert out.entry_price == 100 and out.reason == "target"
    assert out.pnl_per_share == pytest.approx(3.0)


def test_limit_fill_bar_allows_stop_but_not_target() -> None:
    stop_bar = ohlc_frame([(100, 100, 100, 100), (100.2, 100.3, 97.5, 97.8), (98, 98, 98, 98)])
    out = simulate_outcome(cand(), stop_bar, 0, 0.0, execution=LIMIT)
    assert out.reason == "stop" and out.exit_ts == stop_bar.index[1]
    assert out.pnl_per_share == pytest.approx(-2.0)
    # fill bar spans both the limit and the target: order unknown, so the target is not counted
    wide = ohlc_frame([(100, 100, 100, 100), (100.2, 103.5, 99.9, 101), (101, 101.5, 100.5, 101)])
    assert simulate_outcome(cand(), wide, 0, 0.0, execution=LIMIT).reason == "timeout"


def test_short_limit_mirrors_long() -> None:
    fr = ohlc_frame([(100, 100, 100, 100), (99.8, 100.1, 99.6, 99.9), (99.9, 100, 96.5, 97)])
    out = simulate_outcome(cand("short"), fr, 0, 0.05, execution=LIMIT)
    assert out.entry_price == 100 and out.reason == "target"


def test_limit_never_fills_at_or_after_square_off() -> None:
    fr = ohlc_frame([(100, 100, 100, 100), (100, 100, 99, 99.5)], start="2026-01-05 15:09")
    assert simulate_outcome(cand(), fr, 0, 0.05, execution=LIMIT).reason == "no_fill"


def limit_cfg(cancel_bars: int = 1) -> Config:
    cfg = zero_cost_cfg()
    cfg.app.execution = ExecutionCfg(entry_order="limit", limit_cancel_bars=cancel_bars)
    return cfg


def test_backtester_limit_entry_fills_at_limit() -> None:
    rows = [(100, 100, 100, 100), (100.5, 101, 99.99, 100.2), (100.2, 103.5, 100.1, 103)]
    r = Backtester(limit_cfg(), {"X": path(rows)}, detectors=[Scripted(0)]).run()
    t = r.trades.iloc[0]
    assert t["entry_price"] == 100 and t["exit_reason"] == "target" and t["exit_price"] == 103
    d = r.decisions.iloc[0]  # one code path: hypothetical outcome equals the simulated trade
    assert d["hyp_pnl_per_share"] == pytest.approx(t["gross_pnl"] / t["qty"])


def test_backtester_limit_cancelled_when_only_touched() -> None:
    rows = [(100, 100, 100, 100), (100.5, 101, 100.0, 100.2), (100.2, 100.3, 99, 99.5)]
    r = Backtester(limit_cfg(), {"X": path(rows)}, detectors=[Scripted(0)]).run()
    assert r.trades.empty
    assert r.decisions.iloc[0]["final_status"] == "cancelled_unfilled"
    assert r.decisions.iloc[0]["outcome"] == "no_fill"
    r2 = Backtester(limit_cfg(2), {"X": path(rows)}, detectors=[Scripted(0)]).run()
    assert len(r2.trades) == 1 and r2.trades.iloc[0]["entry_ts"] == pd.Timestamp("2026-01-05 10:02")


def test_backtester_limit_fill_bar_stop() -> None:
    rows = [(100, 100, 100, 100), (100.2, 100.3, 97.5, 97.8), (98, 98, 98, 98)]
    r = Backtester(limit_cfg(), {"X": path(rows)}, detectors=[Scripted(0)]).run()
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["entry_ts"] == t["exit_ts"]


def test_candidate_r_skips_unfilled_limits() -> None:
    dec = pd.DataFrame(
        {
            "final_status": ["filled", "cancelled_unfilled"],
            "outcome": ["target", "no_fill"],
            "direction": ["long", "long"],
            "entry": [100.0, 100.0],
            "stop": [99.0, 99.0],
            "hyp_pnl_per_share": [1.5, 0.0],
            "label": [1, 0],
        }
    )
    free = CostModel(CostsCfg(**{k: 0.0 for k in CostsCfg.model_fields}))
    assert len(candidate_r(dec, free)) == 1


def test_day_bootstrap_brackets_the_mean() -> None:
    rng = np.random.default_rng(3)
    ts = pd.date_range("2026-01-05 10:00", periods=400, freq="2h")
    df = pd.DataFrame({"decision_ts": ts, "net_r": rng.normal(0.2, 1.0, len(ts))})
    lo, hi = day_bootstrap(df)
    assert lo < df["net_r"].mean() < hi and hi - lo < 0.5


def synth_bars(spread: float, sigma: float, days: int = 20, per_min: int = 20) -> pd.DataFrame:
    """Trades alternate randomly between bid and ask around a random-walk mid."""
    rng = np.random.default_rng(1)
    parts = []
    for d in range(days):
        mid = 100 * np.exp(np.cumsum(rng.normal(0, sigma, 375 * per_min)))
        px = (mid * (1 + rng.choice([-1.0, 1.0], mid.size) * spread / 2)).reshape(375, per_min)
        start = pd.Timestamp("2026-01-05 09:15") + pd.Timedelta(days=d)
        idx = pd.date_range(start, periods=375, freq="1min")
        bars = {"open": px[:, 0], "high": px.max(1), "low": px.min(1), "close": px[:, -1]}
        parts.append(pd.DataFrame({**bars, "volume": 1.0}, index=idx))
    return pd.concat(parts)


def test_spread_estimators_recover_a_known_spread() -> None:
    est = estimate_spreads(synth_bars(4e-4, 3e-5), n_boot=50).mean(numeric_only=True)
    assert est["roll"] == pytest.approx(4e-4, rel=0.15)
    assert est["ar"] == pytest.approx(4e-4, rel=0.15)
    assert est["cs"] == pytest.approx(4e-4, rel=0.3)
    zero = estimate_spreads(synth_bars(0.0, 3e-5), n_boot=50).mean(numeric_only=True)
    assert zero["roll"] < 0.5e-4 and zero["ar"] < 0.5e-4
