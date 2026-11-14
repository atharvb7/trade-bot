import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.config import load_config
from bot.execution.paper import PaperBroker

T0 = pd.Timestamp("2026-11-16 09:30")


def broker() -> PaperBroker:
    return PaperBroker(1000.0, CostModel(load_config().costs))


def test_market_order_fills_at_next_bar_open_with_slippage_and_fees() -> None:
    b = broker()
    oid = b.place_order("X", "sell", 2, T0)
    assert b.on_bar("X", T0 - pd.Timedelta(minutes=1), 100, 101, 99) == []  # bar before the order
    (order,) = b.on_bar("X", T0, 100.0, 101.0, 99.0)
    assert order.id == oid and order.fill_price == pytest.approx(100 * (1 - 0.0005))
    assert order.fees == pytest.approx(b.costs.leg_fees("sell", 2 * order.fill_price))
    assert b.positions() == {"X": -2}
    assert b.funds() == pytest.approx(1000 + 2 * order.fill_price - order.fees)


def test_buy_stop_triggers_on_touch_and_gaps_fill_at_open() -> None:
    b = broker()
    b.place_order("X", "sell", 1, T0)
    b.on_bar("X", T0, 100, 100, 100)
    stop = b.place_order("X", "buy", 1, T0, kind="stop", trigger=102.0)
    assert b.on_bar("X", T0 + pd.Timedelta(minutes=1), 100, 101.9, 99) == []
    (hit,) = b.on_bar("X", T0 + pd.Timedelta(minutes=2), 101, 102.5, 100)
    assert hit.id == stop and hit.fill_price == pytest.approx(102 * 1.0005)
    assert b.positions() == {}

    b2 = broker()
    b2.place_order("X", "buy", 1, T0, kind="stop", trigger=102.0)
    (gap,) = b2.on_bar("X", T0, 103, 104, 102.5)
    assert gap.fill_price == pytest.approx(103 * 1.0005)


def test_sell_stop_cancel_and_modify() -> None:
    b = broker()
    oid = b.place_order("X", "sell", 1, T0, kind="stop", trigger=95.0)
    b.modify_order(oid, 97.0)
    (hit,) = b.on_bar("X", T0, 99, 99.5, 96.5)
    assert hit.fill_price == pytest.approx(97 * (1 - 0.0005))
    other = b.place_order("X", "buy", 1, T0, kind="stop", trigger=120.0)
    b.cancel_order(other)
    assert b.on_bar("X", T0 + pd.Timedelta(minutes=1), 121, 122, 120) == []
    with pytest.raises(ValueError):
        b.place_order("X", "buy", 0, T0)
    with pytest.raises(ValueError):
        b.place_order("X", "buy", 1, T0, kind="stop")
