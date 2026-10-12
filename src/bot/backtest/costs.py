"""Cost model (Rule 6). All rates come from config/costs.yaml (percent units)."""

from __future__ import annotations

from typing import Literal

from bot.config import CostsCfg

Side = Literal["buy", "sell"]


class CostModel:
    def __init__(self, cfg: CostsCfg) -> None:
        self.cfg = cfg

    def leg_fees(self, side: Side, value: float) -> float:
        """Statutory + broker fees for one executed order of notional ``value`` (excl. slippage)."""
        c = self.cfg
        brokerage = min(value * c.brokerage_pct / 100, c.brokerage_cap_per_order)
        exchange = value * c.exchange_txn_pct / 100
        sebi = value * c.sebi_pct / 100
        gst = (brokerage + exchange + sebi) * c.gst_pct / 100
        stt = value * c.stt_sell_pct / 100 if side == "sell" else 0.0
        stamp = value * c.stamp_buy_pct / 100 if side == "buy" else 0.0
        return brokerage + exchange + sebi + gst + stt + stamp

    def round_trip_fees(self, direction: str, entry_value: float, exit_value: float) -> float:
        first, second = ("buy", "sell") if direction == "long" else ("sell", "buy")
        return self.leg_fees(first, entry_value) + self.leg_fees(second, exit_value)  # type: ignore[arg-type]

    def estimate_round_trip(self, value: float) -> float:
        """Pre-trade estimate used by the minimum-edge rule: fees + slippage on both legs."""
        fees = self.leg_fees("buy", value) + self.leg_fees("sell", value)
        return fees + 2 * value * self.cfg.slippage_pct / 100
