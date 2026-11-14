"""Paper-trading runner for the news gap fade (docs/experiments/2026-11-14-paper-protocol.md).

``step(now)`` is called every few seconds and advances one trading day through its stages:
prepare (universe + overnight announcements) -> screen (opening gaps) -> enter (gate, risk
manager, order) -> manage (stop, 15:10 square-off) -> finalize (hypothetical outcomes for
every candidate). Every candidate gets a DecisionRecord, traded or not.

Fail closed (rule 3): an error or stale data in any stage means no new trade. The entry
stage runs once per day, so a failure there is never retried into a late entry.
"""

from __future__ import annotations

import logging
import time as clock
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import sessionmaker

from bot.backtest.costs import CostModel
from bot.backtest.daily import net_return
from bot.config import Config
from bot.data.live import MarketData
from bot.decision.gate import evaluate_gate
from bot.detectors.base import Candidate
from bot.execution.broker import Order, Side
from bot.execution.paper import PaperBroker
from bot.risk.kill_switch import is_killed
from bot.risk.manager import AccountState, RiskManager, parse_hhmm
from bot.storage import DecisionRecord, EquitySnapshot, Event, Trade
from bot.strategy.news_gap import GapEvent, events_for, gap_events, live_universe, make_candidate

log = logging.getLogger("bot.runner")
MODE = "paper"
ONE_MIN = pd.Timedelta(minutes=1)


def order_side(direction: str, entry: bool) -> Side:
    """Order side that opens (``entry``) or closes a position in ``direction``."""
    return "buy" if (direction == "long") == entry else "sell"


@dataclass
class DayState:
    day: date
    account: AccountState
    closed: bool = False  # weekend or exchange holiday
    universe: list[str] | None = None
    events: dict[str, str] = field(default_factory=dict)
    gaps: list[GapEvent] | None = None
    decisions: dict[str, int] = field(default_factory=dict)  # symbol -> DecisionRecord id
    entered: bool = False
    finalized: bool = False


@dataclass
class LiveTrade:
    decision_id: int
    cand: Candidate
    qty: int
    entry_id: str
    from_ts: pd.Timestamp
    trade_id: int | None = None
    entry: Order | None = None
    stop_id: str | None = None
    exit_id: str | None = None
    exit_reason: str | None = None
    last_bar: pd.Timestamp | None = None


class PaperRunner:
    def __init__(
        self,
        cfg: Config,
        data: MarketData,
        session_factory: sessionmaker[Any],
        kill_file: Path,
        notify: Callable[[str], None] | None = None,
        run_id: str = "paper",
    ) -> None:
        self.cfg, self.data, self.Session = cfg, data, session_factory
        self.kill_file, self.run_id = kill_file, run_id
        self.notify = notify or (lambda _text: None)
        self.costs = CostModel(cfg.costs)
        self.risk = RiskManager(cfg.risk, self.costs)
        self.equity = cfg.app.starting_capital + self._restore()
        self.broker = PaperBroker(self.equity, self.costs)
        self.state: DayState | None = None
        self.live: LiveTrade | None = None
        self.killed = False
        self._last_error = ""

    # ---- public -----------------------------------------------------------------------

    def step(self, now: datetime) -> bool:
        """Advance to ``now`` (naive IST). Returns False once the kill switch has flattened."""
        try:
            return self._step(now)
        except Exception as err:  # noqa: BLE001 - fail closed, keep the loop alive
            log.exception("step failed")
            message = f"{type(err).__name__}: {err}"
            if message != self._last_error:  # log and alert once per distinct failure
                self._last_error = message
                self._event(now, "ERROR", "runner", message)
                self.notify(f"Paper runner error (no new trades): {message[:300]}")
            return True

    # ---- stages -----------------------------------------------------------------------

    def _step(self, now: datetime) -> bool:
        if self.state is None or self.state.day != now.date():
            self.state = DayState(
                now.date(), AccountState(self.equity, self.equity), closed=now.weekday() >= 5
            )
        st, ng, t = self.state, self.cfg.app.news_gap, now.time()
        if not self.killed and is_killed(self.kill_file):
            self.killed = st.account.killed = True
            self._event(now, "WARNING", "kill_switch", "kill switch set: flattening and stopping")
            self.notify("KILL SWITCH: flattening and stopping the paper runner")
            if self.live is not None:
                self._exit_market(now, "kill_switch")
        if self.live is not None:
            self._pump(now)
        if self.killed:
            return self.live is not None  # keep stepping only until the exit has filled
        if st.closed:
            return True
        if st.universe is None and t >= parse_hhmm(ng.prepare_time):
            self._prepare(now)
        if st.universe is not None and st.gaps is None and t >= parse_hhmm(ng.screen_time):
            self._screen(now)
        if st.gaps is not None and not st.entered and t >= parse_hhmm(ng.entry_time):
            st.entered = True  # one attempt per day, whatever happens next
            self._enter(now)
        live = self.live
        if live is not None and live.exit_id is None and live.entry is not None:
            if t >= parse_hhmm(self.cfg.risk.square_off_time):
                self._exit_market(now, "square_off")
        if st.gaps is not None and not st.finalized and self.live is None:
            if t >= parse_hhmm(ng.finalize_time):
                self._finalize(now)
        return True

    def _prepare(self, now: datetime) -> None:
        assert self.state is not None
        st = self.state
        rows = self.data.daily_rows(st.day)
        universe = live_universe(rows, self.cfg.app.news_gap)
        sessions = pd.DatetimeIndex(sorted(rows["date"].unique()))
        ann = self.data.announcements(sessions[-1].date(), st.day)
        events = events_for(st.day, ann, sessions)
        st.events = {s: k for s, k in events.items() if s in set(universe)}
        st.universe = universe
        self._event(
            now,
            "INFO",
            "prepare",
            f"universe {len(universe)}, overnight events in universe {len(st.events)}",
        )

    def _screen(self, now: datetime) -> None:
        assert self.state is not None
        st = self.state
        reference = self.cfg.watchlist.symbols[0]
        if self._closed_bars(reference, now).empty:
            st.closed = True
            self._event(now, "INFO", "screen", f"no bars for {reference} today: market closed")
            return
        quotes = self.data.quotes(sorted(st.events)) if st.events else {}
        gaps = gap_events(st.events, quotes, self.cfg.app.news_gap)
        with self.Session() as db:
            for ev in gaps:
                rec = DecisionRecord(
                    mode=MODE,
                    run_id=self.run_id,
                    ts=now,
                    symbol=ev.symbol,
                    setup=f"news_gap_{ev.kind}",
                    direction="short",
                    entry=ev.open,
                    stop=0.0,
                    target=ev.prev_close,
                    features={"gap_pct": round(ev.gap_pct, 3), "open": ev.open},
                    final_status="candidate",
                )
                db.add(rec)
                db.flush()
                st.decisions[ev.symbol] = rec.id
            db.commit()
        st.gaps = gaps
        names = ", ".join(f"{e.symbol} +{e.gap_pct:.1f}%" for e in gaps) or "none"
        self._event(now, "INFO", "screen", f"gap candidates: {names}")
        if gaps:
            self.notify(f"Paper: news gap candidates today: {names}")

    def _enter(self, now: datetime) -> None:
        assert self.state is not None and self.state.gaps is not None
        st, gaps = self.state, self.state.gaps
        for ev in gaps:
            t0 = clock.perf_counter()
            update: dict[str, Any] = {"ts": now}
            try:
                bars = self._closed_bars(ev.symbol, now)
                if self._stale(bars, now):
                    update |= {"final_status": "rejected_stale_data", "rejection_reason": "stale"}
                else:
                    update |= self._decide(ev, bars, now)
            except Exception as err:  # noqa: BLE001 - one bad symbol must not stop the rest
                log.exception("entry failed for %s", ev.symbol)
                update |= {"final_status": "rejected_error", "rejection_reason": type(err).__name__}
            update["timings_ms"] = {"decide": round((clock.perf_counter() - t0) * 1000, 1)}
            self._update_decision(st.decisions[ev.symbol], update)

    def _decide(self, ev: GapEvent, bars: pd.DataFrame, now: datetime) -> dict[str, Any]:
        assert self.state is not None
        st = self.state
        cand = make_candidate(ev, bars, self.cfg.app.news_gap)
        out: dict[str, Any] = {
            "entry": cand.entry,
            "stop": cand.stop,
            "target": cand.target,
            "features": cand.features,
        }
        gate = evaluate_gate(self.cfg.app.decision, cand, None, None)
        out["gate_result"] = {"passed": gate.passed, "checks": gate.checks}
        if not gate.passed:
            return out | {
                "final_status": f"rejected_{gate.failed_gate}",
                "rejection_reason": gate.failed_gate,
            }
        st.account.open_positions = 1 if self.live is not None else 0
        risk = self.risk.evaluate(cand, st.account, now)
        out["risk_result"] = {"approved": risk.approved, "qty": risk.qty, **risk.checks}
        if not risk.approved:
            return out | {
                "final_status": f"rejected_risk_{risk.reason}",
                "rejection_reason": risk.reason,
            }
        ts = pd.Timestamp(now).floor("min")  # fills at the open of the bar that starts now
        side = order_side(cand.direction, entry=True)
        oid = self.broker.place_order(cand.symbol, side, risk.qty, ts, tag="entry")
        self.live = LiveTrade(st.decisions[ev.symbol], cand, risk.qty, oid, ts)
        st.account.open_positions = 1
        return out | {"final_status": "pending_fill"}

    # ---- position management ----------------------------------------------------------

    def _pump(self, now: datetime) -> None:
        """Feed newly closed bars of the open trade's symbol to the paper broker."""
        live = self.live
        assert live is not None
        bars = self._closed_bars(live.cand.symbol, now)
        start = live.from_ts if live.last_bar is None else live.last_bar + ONE_MIN
        for stamp, bar in bars[bars.index >= start].iterrows():
            ts = pd.Timestamp(str(stamp))
            live.last_bar = ts
            for _ in range(2):  # second pass lets a stop placed on the fill bar trigger on it
                fills = self.broker.on_bar(
                    live.cand.symbol, ts, float(bar["open"]), float(bar["high"]), float(bar["low"])
                )
                for order in fills:
                    self._on_fill(order, ts)
                if self.live is None or not fills:
                    break
            if self.live is None:
                return

    def _on_fill(self, order: Order, ts: pd.Timestamp) -> None:
        live = self.live
        assert live is not None and self.state is not None and order.fill_price is not None
        if order.id == live.entry_id:
            live.entry = order
            self.state.account.trades_today += 1
            with self.Session() as db:
                trade = Trade(
                    decision_id=live.decision_id,
                    mode=MODE,
                    run_id=self.run_id,
                    symbol=order.symbol,
                    direction=live.cand.direction,
                    qty=order.qty,
                    entry_ts=ts.to_pydatetime(),
                    entry_price=order.fill_price,
                )
                db.add(trade)
                db.commit()
                live.trade_id = trade.id
            self._update_decision(live.decision_id, {"final_status": "filled"})
            exit_side = order_side(live.cand.direction, entry=False)
            try:  # rule 4: a stop right after the fill, or get out
                live.stop_id = self.broker.place_order(
                    order.symbol,
                    exit_side,
                    order.qty,
                    ts,
                    "stop",
                    live.cand.stop,
                    "stop",
                )
            except Exception as err:  # noqa: BLE001
                self._event(ts, "ERROR", "execution", f"stop not placed ({err}): exiting")
                self._exit_market(ts.to_pydatetime(), "stop_failed")
            self.notify(
                f"Paper ENTRY {live.cand.direction} {order.qty} {order.symbol} "
                f"@ {order.fill_price:.2f}, stop {live.cand.stop:.2f}"
            )
            return
        entry = live.entry
        assert entry is not None and entry.fill_price is not None
        reason = live.exit_reason if order.id == live.exit_id else "stop"
        sign = 1 if live.cand.direction == "long" else -1
        gross = sign * order.qty * (order.fill_price - entry.fill_price)
        fees = entry.fees + order.fees
        net = gross - fees
        self.equity += net
        acct = self.state.account
        acct.equity, acct.open_positions = self.equity, 0
        acct.consecutive_losses = acct.consecutive_losses + 1 if net < 0 else 0
        with self.Session() as db:
            trade = db.get(Trade, live.trade_id)
            trade.exit_ts, trade.exit_price = ts.to_pydatetime(), order.fill_price
            trade.exit_reason, trade.gross_pnl, trade.costs, trade.net_pnl = (
                reason,
                gross,
                fees,
                net,
            )
            db.add(EquitySnapshot(
                mode=MODE, run_id=self.run_id, ts=ts.to_pydatetime(), equity=self.equity,
                cash=self.broker.funds(),
            ))  # fmt: skip
            db.commit()
        self.notify(
            f"Paper EXIT {order.symbol} ({reason}) @ {order.fill_price:.2f}: "
            f"net {net:+.2f}, equity {self.equity:.2f}"
        )
        self.live = None

    def _exit_market(self, now: datetime, reason: str) -> None:
        live = self.live
        assert live is not None
        if live.entry is None:  # the entry never filled: nothing to close
            self.broker.cancel_order(live.entry_id)
            self._update_decision(live.decision_id, {"final_status": f"cancelled_{reason}"})
            if self.state is not None:
                self.state.account.open_positions = 0
            self.live = None
            return
        if live.stop_id is not None:
            self.broker.cancel_order(live.stop_id)
        side = order_side(live.cand.direction, entry=False)
        ts = pd.Timestamp(now).floor("min")
        live.exit_id = self.broker.place_order(live.cand.symbol, side, live.qty, ts, tag=reason)
        live.exit_reason = reason

    # ---- end of day -------------------------------------------------------------------

    def _finalize(self, now: datetime) -> None:
        """Record what every candidate would have made, traded or not (the forward dataset)."""
        assert self.state is not None and self.state.gaps is not None
        st, gaps = self.state, self.state.gaps
        sq = parse_hhmm(self.cfg.risk.square_off_time)
        entry_t = parse_hhmm(self.cfg.app.news_gap.entry_time)
        for ev in gaps:
            bars = self._closed_bars(ev.symbol, now)
            times = pd.DatetimeIndex(bars.index).time
            at_entry, at_exit = bars[times == entry_t], bars[times == sq]
            if at_entry.empty or at_exit.empty:
                continue
            p_in, p_out = float(at_entry["open"].iloc[0]), float(at_exit["open"].iloc[0])
            later = bars[(times >= entry_t) & (times < sq)]

            def short_net(p0: float, p1: float = p_out) -> float:
                return float(net_return(pd.Series([p1 / p0 - 1]), "short", self.costs).iloc[0])

            outcome = {
                "entry_time_price": p_in,
                "square_off_price": p_out,
                "short_from_open_net_pct": round(short_net(ev.open) * 100, 4),
                "short_from_entry_time_net_pct": round(short_net(p_in) * 100, 4),
                "max_adverse_pct": round((float(later["high"].max()) / p_in - 1) * 100, 4),
            }
            with self.Session() as db:
                rec = db.get(DecisionRecord, st.decisions[ev.symbol])
                rec.features = {**rec.features, "outcome": outcome}
                rec.hypothetical_pnl = short_net(p_in) * p_in  # rupees per share
                db.commit()
        with self.Session() as db:
            db.add(EquitySnapshot(
                mode=MODE, run_id=self.run_id, ts=now, equity=self.equity, cash=self.broker.funds()
            ))  # fmt: skip
            db.commit()
        st.finalized = True
        self._event(now, "INFO", "finalize", f"{len(gaps)} candidates, equity {self.equity:.2f}")

    # ---- helpers ----------------------------------------------------------------------

    def _closed_bars(self, symbol: str, now: datetime) -> pd.DataFrame:
        """Today's bars that have fully closed by ``now`` (rule 5: closed bars only)."""
        bars = self.data.bars_1m(symbol, now.date())
        if bars.empty:
            return bars
        bars = bars[pd.DatetimeIndex(bars.index).normalize() == pd.Timestamp(now.date())]
        return bars[bars.index + ONE_MIN <= pd.Timestamp(now)]

    def _stale(self, bars: pd.DataFrame, now: datetime) -> bool:
        if bars.empty:
            return True
        age = pd.Timestamp(now) - (bars.index[-1] + ONE_MIN)
        return bool(age > timedelta(seconds=self.cfg.app.stale_feed_seconds + 60))

    def _update_decision(self, decision_id: int, fields: dict[str, Any]) -> None:
        with self.Session() as db:
            rec = db.get(DecisionRecord, decision_id)
            for key, value in fields.items():
                setattr(rec, key, value)
            db.commit()

    def _event(self, now: datetime | pd.Timestamp, level: str, source: str, message: str) -> None:
        log.log(getattr(logging, level, logging.INFO), "%s: %s", source, message)
        with self.Session() as db:
            db.add(Event(ts=pd.Timestamp(now).to_pydatetime(), level=level, source=source,
                         message=message[:1000]))  # fmt: skip
            db.commit()

    def _restore(self) -> float:
        """Net P&L of this run's closed trades. Positions left open by a crash are orphaned.

        Paper positions exist only in memory, so a trade without an exit cannot be resumed;
        it is closed in the journal as ``orphaned_restart`` with no P&L and logged.
        """
        with self.Session() as db:
            trades = db.query(Trade).filter_by(mode=MODE, run_id=self.run_id).all()
            total = sum(t.net_pnl or 0.0 for t in trades if t.exit_ts is not None)
            orphans = [t for t in trades if t.exit_ts is None]
            for t in orphans:
                t.exit_ts, t.exit_reason = t.entry_ts, "orphaned_restart"
                msg = f"trade {t.id} {t.symbol} was open at restart: orphaned"
                db.add(Event(ts=datetime.now(), level="ERROR", source="runner", message=msg))
            db.commit()
        return float(total)
