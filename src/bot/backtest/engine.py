"""Event-driven backtester.

One chronological loop over bar-open timestamps across all symbols. On each timestamp:
  1. fill orders queued on the previous bar's close (next-bar open + slippage),
  2. check exits (stop / target / 15:10 square-off) on the current bar,
  3. run detectors on bars that just opened-and-closed; gate -> risk -> queue an order.
At a day boundary, any position still open (the day's data ended before square-off) is
closed at that day's last close, and unfilled orders are cancelled: nothing carries overnight.
Detectors, gate and risk manager are the same objects the live runner will use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from math import inf
from typing import Any

import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.fills import adverse, check_exit, limit_filled, limit_price, must_square_off
from bot.backtest.outcome import simulate_outcome
from bot.config import Config
from bot.decision.gate import JevAnswer, evaluate_gate
from bot.detectors import ALL_DETECTORS
from bot.detectors.base import Candidate, Detector, Frame
from bot.risk.manager import AccountState, RiskManager, parse_hhmm


@dataclass
class Position:
    symbol: str
    setup: str
    direction: str
    qty: int
    entry_ts: pd.Timestamp
    entry_price: float
    stop: float
    target: float
    decision_id: int


@dataclass
class Pending:
    cand: Candidate
    qty: int
    decision_id: int
    limit: float | None = None  # passive entry limit; None = market order at next open
    bars_left: int = 0


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    decisions: pd.DataFrame
    equity: pd.DataFrame
    n_days: int
    start_capital: float
    config: dict[str, Any] = field(default_factory=dict)


class Backtester:
    def __init__(
        self,
        cfg: Config,
        frames: dict[str, Frame],
        detectors: list[Detector] | None = None,
        ml_prob_fn: Any = None,
        jev_fn: Any = None,
        bar_minutes: int = 1,
    ) -> None:
        self.cfg, self.frames = cfg, frames
        self.detectors = detectors if detectors is not None else ALL_DETECTORS
        self.costs = CostModel(cfg.costs)
        self.risk = RiskManager(cfg.risk, self.costs)
        self.ml_prob_fn = ml_prob_fn  # (cand, frame, i) -> float | None   (Phase 4)
        self.jev_fn = jev_fn  # (cand, frame, i, ml_prob) -> JevAnswer | None   (Phase 5)
        self.bar_minutes = bar_minutes

    def run(self) -> BacktestResult:
        cfg, slip = self.cfg, self.cfg.costs.slippage_pct
        ex = cfg.app.execution
        through = ex.target_fill == "through"
        sq_off = parse_hhmm(cfg.risk.square_off_time)
        pos_idx = {s: {ts: k for k, ts in enumerate(fr.index)} for s, fr in self.frames.items()}
        all_ts = sorted(set().union(*[set(fr.index) for fr in self.frames.values()]))

        equity = cfg.app.starting_capital
        st = AccountState(equity=equity, start_of_day_equity=equity)
        positions: dict[str, Position] = {}
        pending: dict[str, Pending] = {}
        trades: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        eq_rows: list[dict[str, Any]] = []
        cur_day: date | None = None
        days_seen: set[date] = set()
        last_ts: dict[str, pd.Timestamp] = {}

        def close_position(
            p: Position, ts: pd.Timestamp, raw_px: float, reason: str, slipped: bool
        ) -> None:
            nonlocal equity
            px = adverse(raw_px, p.direction, False, slip) if slipped else raw_px
            sign = 1 if p.direction == "long" else -1
            gross = sign * (px - p.entry_price) * p.qty
            fees = self.costs.round_trip_fees(p.direction, p.entry_price * p.qty, px * p.qty)
            net = gross - fees
            equity += net
            st.consecutive_losses = st.consecutive_losses + 1 if net < 0 else 0
            trades.append(
                {
                    "symbol": p.symbol,
                    "setup": p.setup,
                    "direction": p.direction,
                    "qty": p.qty,
                    "entry_ts": p.entry_ts,
                    "exit_ts": ts,
                    "entry_price": p.entry_price,
                    "exit_price": px,
                    "exit_reason": reason,
                    "gross_pnl": gross,
                    "costs": fees,
                    "net_pnl": net,
                    "decision_id": p.decision_id,
                }
            )
            decisions[p.decision_id]["final_status"] = "filled"
            positions.pop(p.symbol)

        for ts in all_ts:
            if ts.date() != cur_day:
                for s, op in list(positions.items()):  # day ended before square-off
                    k = pos_idx[s][last_ts[s]]
                    px_eod = float(self.frames[s]["close"][k])
                    close_position(op, last_ts[s], px_eod, "square_off_eod", True)
                for pend_eod in pending.values():
                    decisions[pend_eod.decision_id]["final_status"] = "cancelled_eod"
                pending.clear()
                cur_day = ts.date()
                days_seen.add(cur_day)
                st.start_of_day_equity, st.trades_today, st.consecutive_losses = equity, 0, 0
            st.equity = equity

            present = [(s, pos_idx[s][ts]) for s in self.frames if ts in pos_idx[s]]
            for s, i in present:
                fr = self.frames[s]
                last_ts[s] = ts
                o, h, lo = float(fr["open"][i]), float(fr["high"][i]), float(fr["low"][i])
                pend = pending.pop(s, None)
                filled_limit = False
                if pend is not None:
                    c = pend.cand
                    px: float | None = None
                    if pend.limit is None:
                        px = adverse(o, c.direction, True, slip)
                    elif not must_square_off(ts, self.bar_minutes, sq_off) and (
                        ts.date() == c.ts.date()
                    ):
                        if limit_filled(c.direction, pend.limit, h, lo):
                            px, filled_limit = pend.limit, True
                        elif pend.bars_left > 1:
                            pend.bars_left -= 1
                            pending[s] = pend
                    if px is not None:
                        # Sized on the signal close; a gap at the fill must not breach the cash
                        # cap (rule 10, no leverage). Only ever shrinks qty, never rounds up.
                        cash = equity * cfg.risk.max_position_value_pct_of_cash / 100
                        qty = min(pend.qty, math.floor(cash / px))
                        if qty < 1:
                            decisions[pend.decision_id]["final_status"] = "cancelled_cash"
                        else:
                            positions[s] = Position(
                                s,
                                c.setup,
                                c.direction,
                                qty,
                                ts,
                                px,
                                c.stop,
                                c.target,
                                pend.decision_id,
                            )
                            st.trades_today += 1
                    elif s not in pending:
                        decisions[pend.decision_id]["final_status"] = "cancelled_unfilled"
                p = positions.get(s)
                if p is None:
                    continue
                if must_square_off(ts, self.bar_minutes, sq_off):
                    close_position(p, ts, o, "square_off", True)
                    continue
                # On a limit's fill bar the price order is unknown: allow the stop, not the target.
                tgt = p.target if not filled_limit else (inf if p.direction == "long" else -inf)
                hit = check_exit(p.direction, p.stop, tgt, o, h, lo, through)
                if hit:
                    px, why = hit
                    close_position(p, ts, px, why, why.startswith("stop"))

            st.equity = equity
            st.open_positions = len(positions) + len(pending)
            cands: list[tuple[Candidate, int]] = []
            for s, i in present:
                if s in positions or s in pending:
                    continue
                fr = self.frames[s]
                for det in self.detectors:
                    found = det.detect(s, fr, i, cfg.app.detectors)
                    if found is not None:
                        found.features = {k: float(fr[k][i]) for k in _FEATS if k in fr.cols}
                        cands.append((found, i))
            cands.sort(key=lambda ci: -ci[0].features.get("volume_vs_avg20", 0.0))
            now = ts + pd.Timedelta(minutes=self.bar_minutes)  # decision time = bar close
            for c, i in cands:
                fr = self.frames[c.symbol]
                ml_prob = self.ml_prob_fn(c, fr, i) if self.ml_prob_fn else None
                jev: JevAnswer | None = self.jev_fn(c, fr, i, ml_prob) if self.jev_fn else None
                gate = evaluate_gate(cfg.app.decision, c, ml_prob, jev)
                st.open_positions = len(positions) + len(pending)
                risk = self.risk.evaluate(c, st, now.to_pydatetime()) if gate.passed else None
                status = (
                    "pending_fill"
                    if risk and risk.approved
                    else (
                        f"rejected_{gate.failed_gate}"
                        if not gate.passed
                        else f"rejected_risk_{risk.reason}"  # type: ignore[union-attr]
                    )
                )
                out = simulate_outcome(
                    c, fr, i, slip, sq_off, bar_minutes=self.bar_minutes, execution=ex
                )
                did = len(decisions)
                decisions.append(
                    {
                        "decision_id": did,
                        "ts": ts,
                        "symbol": c.symbol,
                        "setup": c.setup,
                        "direction": c.direction,
                        "entry": c.entry,
                        "stop": c.stop,
                        "target": c.target,
                        "ml_prob": ml_prob,
                        "gate_failed": gate.failed_gate,
                        "risk_reason": risk.reason if risk else None,
                        "final_status": status,
                        "outcome": out.reason,
                        "label": out.label,
                        "hyp_pnl_per_share": out.pnl_per_share,
                        "hyp_entry_price": out.entry_price,
                        "hyp_exit_price": out.exit_price,
                        **{f"f_{k}": v for k, v in c.features.items()},
                    }
                )
                if risk and risk.approved:
                    lim = (
                        limit_price(c.direction, c.entry, ex.limit_offset_ticks)
                        if ex.entry_order == "limit"
                        else None
                    )
                    pending[c.symbol] = Pending(c, risk.qty, did, lim, ex.limit_cancel_bars)

            eq_rows.append({"ts": ts, "equity": equity})

        for s, p in list(positions.items()):  # data ended mid-position
            fr = self.frames[s]
            close_position(p, last_ts[s], float(fr["close"][-1]), "end_of_data", True)

        eq = pd.DataFrame(eq_rows)
        return BacktestResult(
            trades=pd.DataFrame(trades),
            decisions=pd.DataFrame(decisions),
            equity=eq,
            n_days=len(days_seen),
            start_capital=cfg.app.starting_capital,
            config={
                "decision_mode": cfg.app.decision.mode,
                "detectors": cfg.app.detectors.model_dump(),
                "risk": cfg.risk.model_dump(),
                "costs": cfg.costs.model_dump(),
            },
        )


_FEATS = [
    "price_vs_vwap_pct",
    "rsi_14",
    "volume_vs_avg20",
    "atr_pct",
    "nifty_trend_15m",
    "rel_strength_vs_nifty",
    "minutes_to_close",
]
