"""PaperBroker: simulated fills with the backtester's slippage and cost model.

Market orders fill at the open of the first bar that starts at or after the order time, with
adverse slippage. Stop orders trigger on a touch: at the stop, or at the open if the bar gaps
through it, also with adverse slippage. Bars are pushed in by the runner through ``on_bar``.
"""

from __future__ import annotations

import pandas as pd

from bot.backtest.costs import CostModel
from bot.execution.broker import Order, OrderKind, Side


class PaperBroker:
    def __init__(self, cash: float, costs: CostModel) -> None:
        self.cash = cash
        self.costs = costs
        self._orders: dict[str, Order] = {}
        self._pos: dict[str, int] = {}
        self._seq = 0

    def place_order(
        self,
        symbol: str,
        side: Side,
        qty: int,
        ts: pd.Timestamp,
        kind: OrderKind = "market",
        trigger: float | None = None,
        tag: str = "",
    ) -> str:
        if qty < 1:
            raise ValueError("qty must be at least 1")
        if kind == "stop" and trigger is None:
            raise ValueError("a stop order needs a trigger price")
        self._seq += 1
        oid = f"P{self._seq}"
        self._orders[oid] = Order(oid, symbol, side, qty, kind, trigger, ts, tag)
        return oid

    def cancel_order(self, order_id: str) -> None:
        order = self._orders[order_id]
        if order.status == "open":
            order.status = "cancelled"

    def modify_order(self, order_id: str, trigger: float) -> None:
        order = self._orders[order_id]
        if order.status != "open" or order.kind != "stop":
            raise ValueError("only an open stop order can be modified")
        order.trigger = trigger

    def positions(self) -> dict[str, int]:
        return {s: q for s, q in self._pos.items() if q}

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    def funds(self) -> float:
        return self.cash

    def subscribe_ticks(self, symbols: list[str]) -> None:
        """Paper mode is fed closed bars by the runner; there is nothing to subscribe to."""

    def on_bar(self, symbol: str, ts: pd.Timestamp, o: float, h: float, low: float) -> list[Order]:
        """Apply one closed bar. Returns the orders it filled, in fill order."""
        filled: list[Order] = []
        for order in list(self._orders.values()):
            if order.status != "open" or order.symbol != symbol or ts < order.placed_ts:
                continue
            price: float | None = None
            if order.kind == "market":
                price = o
            elif order.trigger is not None:
                if order.side == "buy" and h >= order.trigger:
                    price = max(o, order.trigger)
                elif order.side == "sell" and low <= order.trigger:
                    price = min(o, order.trigger)
            if price is not None:
                self._fill(order, price, ts)
                filled.append(order)
        return filled

    def _fill(self, order: Order, price: float, ts: pd.Timestamp) -> None:
        slip = self.costs.cfg.slippage_pct / 100
        px = price * (1 + slip) if order.side == "buy" else price * (1 - slip)
        value = px * order.qty
        order.fees = self.costs.leg_fees(order.side, value)
        order.fill_price, order.fill_ts, order.status = px, ts, "filled"
        sign = 1 if order.side == "buy" else -1
        self.cash -= sign * value + order.fees
        self._pos[order.symbol] = self._pos.get(order.symbol, 0) + sign * order.qty
