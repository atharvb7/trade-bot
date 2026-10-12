"""Risk manager: sizing + account limits. Records the first rule that blocks a trade."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time

from bot.backtest.costs import CostModel
from bot.config import RiskCfg
from bot.detectors.base import Candidate


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class AccountState:
    equity: float
    start_of_day_equity: float
    trades_today: int = 0
    consecutive_losses: int = 0
    open_positions: int = 0  # filled + pending
    killed: bool = False


@dataclass
class RiskDecision:
    approved: bool
    qty: int = 0
    reason: str | None = None
    checks: dict[str, object] = field(default_factory=dict)


class RiskManager:
    def __init__(self, cfg: RiskCfg, costs: CostModel) -> None:
        self.cfg, self.costs = cfg, costs

    def size(self, cand: Candidate, equity: float) -> int:
        stop_dist = abs(cand.entry - cand.stop)
        if stop_dist <= 0:
            return 0
        by_risk = equity * self.cfg.risk_per_trade_pct / 100 / stop_dist
        # Cash cap with a buffer for slippage and entry fees so value never exceeds cash.
        slip = 1 + self.costs.cfg.slippage_pct / 100
        cash_cap = equity * self.cfg.max_position_value_pct_of_cash / 100
        by_cash = cash_cap / (cand.entry * slip * 1.002)
        return math.floor(min(by_risk, by_cash))  # never round up

    def evaluate(self, cand: Candidate, st: AccountState, now: datetime) -> RiskDecision:
        cfg = self.cfg

        def block(reason: str, **kw: object) -> RiskDecision:
            return RiskDecision(False, 0, reason, dict(kw))

        if st.killed:
            return block("kill_switch")
        t = now.time()
        if t < parse_hhmm(cfg.no_entry_before) or t > parse_hhmm(cfg.no_entry_after):
            return block("outside_entry_window", time=str(t))
        loss = st.start_of_day_equity - st.equity
        if loss >= st.start_of_day_equity * cfg.max_daily_loss_pct / 100:
            return block("max_daily_loss", loss=round(loss, 2))
        if st.trades_today >= cfg.max_trades_per_day:
            return block("max_trades_per_day")
        if st.open_positions >= cfg.max_open_positions:
            return block("max_open_positions")
        if st.consecutive_losses >= cfg.max_consecutive_losses:
            return block("losing_streak")
        qty = self.size(cand, st.equity)
        if qty < 1:
            return block("qty_below_1", equity=round(st.equity, 2), entry=round(cand.entry, 2))
        value = qty * cand.entry
        target_gain = qty * abs(cand.target - cand.entry)
        est_cost = self.costs.estimate_round_trip(value)
        if target_gain <= cfg.min_edge_cost_multiple * est_cost:
            return block("min_edge", target_gain=round(target_gain, 2), est_cost=round(est_cost, 2))
        return RiskDecision(
            True, qty, None, {"est_cost": round(est_cost, 2), "value": round(value, 2)}
        )
