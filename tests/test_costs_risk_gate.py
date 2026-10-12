from datetime import datetime

import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.config import DecisionCfg, load_config
from bot.decision.gate import JevAnswer, evaluate_gate
from bot.detectors.base import Candidate
from bot.risk.manager import AccountState, RiskManager


def _cand(
    entry: float = 100.0, stop: float = 99.0, target: float = 101.5, d: str = "long"
) -> Candidate:
    return Candidate("X", "orb", d, pd.Timestamp("2026-01-05 10:00"), entry, stop, target, 1.0)  # type: ignore[arg-type]


def test_cost_model_hand_computed() -> None:
    cm = CostModel(load_config().costs)
    v = 10_000.0
    brokerage = v * 0.0003
    exch, sebi = v * 0.0000297, v * 0.000001
    gst = (brokerage + exch + sebi) * 0.18
    buy = brokerage + exch + sebi + gst + v * 0.00003
    sell = brokerage + exch + sebi + gst + v * 0.00025
    assert cm.leg_fees("buy", v) == pytest.approx(buy)
    assert cm.leg_fees("sell", v) == pytest.approx(sell)
    assert cm.round_trip_fees("long", v, v) == pytest.approx(buy + sell)
    assert cm.estimate_round_trip(v) == pytest.approx(buy + sell + 2 * v * 0.0005)


def test_brokerage_cap() -> None:
    cm = CostModel(load_config().costs)
    big = 10_000_000.0
    assert cm.leg_fees("buy", big) < big * 0.0003  # cap of Rs 20 binds


def _rm() -> RiskManager:
    cfg = load_config()
    cfg.risk.min_edge_cost_multiple = 3.0
    return RiskManager(cfg.risk, CostModel(cfg.costs))


NOW = datetime(2026, 1, 5, 10, 30)


def test_sizing_never_rounds_up_and_respects_cash() -> None:
    rm = _rm()
    # 1% of 1000 = 10 risk / 1.0 stop = 10 shares by risk; cash cap 1000/100 ~ 9.97 -> 9
    assert rm.size(_cand(), 1000.0) == 9
    assert rm.size(_cand(entry=2000, stop=1990), 1000.0) == 0  # can't afford one share


def test_qty_below_one_rejected() -> None:
    d = _rm().evaluate(_cand(entry=2000, stop=1980, target=2030), AccountState(1000, 1000), NOW)
    assert not d.approved and d.reason == "qty_below_1"


@pytest.mark.parametrize(
    "state,when,reason",
    [
        (AccountState(1000, 1000, killed=True), NOW, "kill_switch"),
        (AccountState(1000, 1000), datetime(2026, 1, 5, 9, 20), "outside_entry_window"),
        (AccountState(1000, 1000), datetime(2026, 1, 5, 14, 50), "outside_entry_window"),
        (AccountState(969, 1000), NOW, "max_daily_loss"),
        (AccountState(1000, 1000, trades_today=3), NOW, "max_trades_per_day"),
        (AccountState(1000, 1000, open_positions=1), NOW, "max_open_positions"),
        (AccountState(1000, 1000, consecutive_losses=2), NOW, "losing_streak"),
    ],
)
def test_risk_blocks(state: AccountState, when: datetime, reason: str) -> None:
    cand = _cand(entry=100, stop=90, target=130)
    d = _rm().evaluate(cand, state, when)
    assert not d.approved and d.reason == reason


def test_min_edge_blocks_thin_target() -> None:
    d = _rm().evaluate(_cand(target=100.05), AccountState(1000, 1000), NOW)
    assert not d.approved and d.reason == "min_edge"


def test_risk_approves_good_trade() -> None:
    d = _rm().evaluate(_cand(entry=100, stop=98, target=106), AccountState(1000, 1000), NOW)
    assert d.approved and d.qty >= 1
    assert d.qty * 100 <= 1000  # no leverage


def test_gate_modes_and_fail_closed() -> None:
    c = _cand()
    assert evaluate_gate(DecisionCfg(mode="rules_only"), c, None, None).passed
    assert not evaluate_gate(DecisionCfg(mode="rules_only"), None, None, None).passed
    assert not evaluate_gate(DecisionCfg(mode="rules_ml"), c, None, None).passed  # missing ML
    assert evaluate_gate(DecisionCfg(mode="rules_ml"), c, 0.65, None).passed
    assert not evaluate_gate(DecisionCfg(mode="rules_ml"), c, 0.55, None).passed
    full = DecisionCfg(mode="rules_ml_jev")
    good = JevAnswer("long", 0.8, 2.0, 0.1)
    assert evaluate_gate(full, c, 0.7, good).passed
    assert not evaluate_gate(full, c, 0.7, None).passed  # missing Jev -> fail closed
    assert (
        evaluate_gate(full, c, 0.7, JevAnswer("short", 0.9, 2.0, 0.1)).failed_gate == "jev_action"
    )
    assert (
        evaluate_gate(full, c, 0.7, JevAnswer("long", 0.5, 2.0, 0.1)).failed_gate
        == "jev_confidence"
    )
    assert (
        evaluate_gate(full, c, 0.7, JevAnswer("long", 0.8, 1.0, 0.1)).failed_gate == "jev_quality"
    )
    assert evaluate_gate(full, c, 0.7, JevAnswer("long", 0.8, 2.0, 0.5)).failed_gate == "jev_trap"
