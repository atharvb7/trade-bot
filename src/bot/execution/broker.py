"""Broker interface (Rule 2: nothing outside bot.execution talks to a broker SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import pandas as pd

Side = Literal["buy", "sell"]
OrderKind = Literal["market", "stop"]


@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    qty: int
    kind: OrderKind
    trigger: float | None  # stop orders only
    placed_ts: pd.Timestamp
    tag: str = ""
    status: Literal["open", "filled", "cancelled"] = "open"
    fill_price: float | None = None
    fill_ts: pd.Timestamp | None = None
    fees: float = 0.0


class BrokerAdapter(Protocol):
    def place_order(
        self,
        symbol: str,
        side: Side,
        qty: int,
        ts: pd.Timestamp,
        kind: OrderKind = "market",
        trigger: float | None = None,
        tag: str = "",
    ) -> str: ...

    def cancel_order(self, order_id: str) -> None: ...

    def modify_order(self, order_id: str, trigger: float) -> None: ...

    def positions(self) -> dict[str, int]: ...

    def orders(self) -> list[Order]: ...

    def funds(self) -> float: ...

    def subscribe_ticks(self, symbols: list[str]) -> None: ...
