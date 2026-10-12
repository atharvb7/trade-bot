"""Backtester behaviour on hand-made price paths with a scripted detector and zero costs."""

import pandas as pd

from bot.backtest.engine import Backtester
from bot.backtest.fills import check_exit
from bot.backtest.metrics import compute_metrics
from bot.config import Config, CostsCfg, load_config
from bot.detectors.base import Candidate, Frame, make_candidate
from tests.helpers import frame


class Scripted:
    name = "scripted"

    def __init__(self, at: int, direction: str = "long") -> None:
        self.at, self.direction = at, direction

    def detect(self, symbol: str, fr: Frame, i: int, cfg) -> Candidate | None:  # type: ignore[no-untyped-def]
        return (
            make_candidate(symbol, self.name, self.direction, fr, i, cfg) if i == self.at else None
        )  # type: ignore[arg-type]


def zero_cost_cfg() -> Config:
    cfg = load_config()
    cfg.costs = CostsCfg(**{k: 0.0 for k in CostsCfg.model_fields})
    cfg.risk.min_edge_cost_multiple = 0.0
    return cfg


def path(rows: list[tuple[float, float, float, float]], start: str = "2026-01-05 10:00") -> Frame:
    o, h, lo, c = (list(x) for x in zip(*rows, strict=True))
    return frame(
        len(rows),
        start,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=1000.0,
        atr_14=2.0,
        volume_vs_avg20=1.0,
    )


def run(rows, det, cfg=None, **kw):  # type: ignore[no-untyped-def]
    cfg = cfg or zero_cost_cfg()
    return Backtester(cfg, {"X": path(rows, **kw)}, detectors=[det]).run()


def test_target_hit_pnl_exact() -> None:
    # signal bar 0: close 100, ATR 2 -> stop 98, target 103; bar 1 high 104 hits it.
    rows = [(100, 100, 100, 100), (100, 104, 99.5, 103), (103, 103, 103, 103)]
    r = run(rows, Scripted(0))
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "target" and t["exit_price"] == 103
    assert t["entry_price"] == 100 and t["gross_pnl"] == t["qty"] * 3
    assert t["net_pnl"] > 0


def test_stop_first_when_both_inside_bar() -> None:
    rows = [(100, 100, 100, 100), (100, 110, 90, 100), (100, 100, 100, 100)]
    r = run(rows, Scripted(0))
    assert r.trades.iloc[0]["exit_reason"] == "stop"
    assert r.trades.iloc[0]["net_pnl"] < 0


def test_gap_through_stop_fills_at_open() -> None:
    assert check_exit("long", 98, 103, 95, 96, 94) == (95, "stop_gap")
    assert check_exit("short", 102, 97, 105, 106, 104) == (105, "stop_gap")


def test_short_target() -> None:
    rows = [(100, 100, 100, 100), (100, 100.5, 96, 97), (97, 97, 97, 97)]
    r = run(rows, Scripted(0, "short"))
    t = r.trades.iloc[0]
    assert t["direction"] == "short" and t["exit_reason"] == "target" and t["net_pnl"] > 0


def test_square_off_at_1510() -> None:
    rows = [(100, 100.2, 99.9, 100)] + [(100, 100.3, 99.8, 100)] * 35
    r = run(rows, Scripted(0), start="2026-01-05 14:40")
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "square_off" and t["exit_ts"] == pd.Timestamp("2026-01-05 15:10")


def test_no_entry_after_1445_and_before_0930() -> None:
    rows = [(100, 100, 100, 100), (100, 104, 99, 103)]
    assert run(rows, Scripted(0), start="2026-01-05 14:50").trades.empty
    assert run(rows, Scripted(0), start="2026-01-05 09:20").trades.empty


def test_fill_uses_next_bar_open_with_slippage() -> None:
    cfg = zero_cost_cfg()
    cfg.costs.slippage_pct = 0.05
    rows = [(100, 100, 100, 100), (101, 101.5, 100.9, 101.2), (101.2, 101.2, 101.2, 101.2)]
    # scripted decision price is 100 but next open is 101 -> entry 101*(1.0005)
    r = run(rows, Scripted(0), cfg)
    assert abs(r.trades.iloc[0]["entry_price"] - 101 * 1.0005) < 1e-9


def test_qty_below_one_is_skipped() -> None:
    rows = [(5000, 5000, 5000, 5000), (5000, 5100, 4999, 5050)]
    r = run(rows, Scripted(0))
    assert r.trades.empty
    assert r.decisions.iloc[0]["risk_reason"] == "qty_below_1"


def test_costs_reduce_pnl_and_metrics_consistent() -> None:
    rows = [(100, 100, 100, 100), (100, 104, 99.5, 103), (103, 103, 103, 103)]
    free = run(rows, Scripted(0)).trades.iloc[0]
    cfg = load_config()
    cfg.risk.min_edge_cost_multiple = 0.0
    paid = Backtester(cfg, {"X": path(rows)}, detectors=[Scripted(0)]).run()
    t = paid.trades.iloc[0]
    assert t["costs"] > 0 and abs(t["gross_pnl"] - t["costs"] - t["net_pnl"]) < 1e-9
    assert t["net_pnl"] < free["net_pnl"]
    m = compute_metrics(paid.trades, paid.start_capital, paid.n_days)
    assert m["trades"] == 1 and m["net_pnl"] == t["net_pnl"]


def test_outcome_label_recorded_for_rejected_candidates() -> None:
    rows = [(5000, 5000, 5000, 5000), (5000, 5100, 4999, 5050)]
    r = run(rows, Scripted(0))
    assert r.decisions.iloc[0]["outcome"] in {"target", "stop", "timeout"}


def test_5m_decision_time_is_bar_close() -> None:
    # 5m bar opening 14:40 closes 14:45 -> still inside the entry window (<= 14:45).
    # 5m bar opening 14:45 closes 14:50 -> outside it.
    cfg = zero_cost_cfg()
    rows = [(100, 100, 100, 100), (100, 104, 99.5, 103), (103, 103, 103, 103)]

    def run5(start: str) -> int:
        idx = pd.date_range(start, periods=3, freq="5min")
        o, h, lo, c = (list(x) for x in zip(*rows, strict=True))
        fr = frame(3, start, open=o, high=h, low=lo, close=c, volume=1000.0, atr_14=2.0)
        fr.index = idx
        return len(Backtester(cfg, {"X": fr}, detectors=[Scripted(0)], bar_minutes=5).run().trades)

    assert run5("2026-01-05 14:40") == 1
    assert run5("2026-01-05 14:45") == 0
