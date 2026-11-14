"""A whole simulated paper-trading day through PaperRunner, on fake market data."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bot.config import load_config
from bot.runner import PaperRunner
from bot.storage import DecisionRecord, EquitySnapshot, Event, Trade, make_session_factory

DAY = date(2026, 11, 16)  # a Monday
MINUTES = pd.date_range("2026-11-16 09:15", "2026-11-16 15:29", freq="1min")


def flat_then(drop_to: float) -> Callable[[pd.Timestamp], float]:
    """104 at the open, 103 from 09:25, then a straight line to ``drop_to`` by 15:10."""

    def price(ts: pd.Timestamp) -> float:
        if ts < pd.Timestamp("2026-11-16 09:25"):
            return 104.0
        frac = min(1.0, (ts - pd.Timestamp("2026-11-16 09:30")).total_seconds() / (340 * 60))
        return 103.0 + (drop_to - 103.0) * max(0.0, frac)

    return price


class FakeData:
    def __init__(self, price: Callable[[pd.Timestamp], float], prev_close: float = 100.0) -> None:
        self.price, self.prev_close = price, prev_close
        self.last_bar = MINUTES[-1]
        self.fail_news = False

    def daily_rows(self, today: date) -> pd.DataFrame:
        days = pd.bdate_range(end="2026-11-13", periods=20)
        rows = [(d, s, self.prev_close, 100.0) for d in days for s in ("AAA", "NTPC")]
        return pd.DataFrame(rows, columns=["date", "symbol", "close", "turnover"])

    def announcements(self, start: date, end: date) -> pd.DataFrame:
        if self.fail_news:
            raise OSError("feed down")
        ts = pd.to_datetime(["2026-11-13 19:00"])
        return pd.DataFrame({"symbol": ["AAA"], "ts": ts, "kind": ["order"]})

    def quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        return {s: (self.price(MINUTES[0]), self.prev_close) for s in symbols}

    def bars_1m(self, symbol: str, day: date) -> pd.DataFrame:
        idx = MINUTES[MINUTES <= self.last_bar]
        px = [self.price(t) if symbol == "AAA" else 300.0 for t in idx]
        return pd.DataFrame({"open": px, "high": px, "low": px, "close": px}, index=idx)


def run_day(
    runner: PaperRunner, until: str = "15:40", on_step: Callable[[datetime], None] | None = None
) -> bool:
    now, end = datetime(2026, 11, 16, 8, 55), datetime.fromisoformat(f"2026-11-16 {until}")
    alive = True
    while now <= end and alive:
        if on_step:
            on_step(now)
        alive = runner.step(now)
        now += timedelta(seconds=30)
    return alive


@pytest.fixture
def make(tmp_path: Path):  # type: ignore[no-untyped-def]
    cfg = load_config()
    sessions = make_session_factory(f"sqlite:///{tmp_path / 'bot.db'}")
    sent: list[str] = []

    def build(data: FakeData) -> PaperRunner:
        return PaperRunner(cfg, data, sessions, tmp_path / "KILL", sent.append)

    return build, sessions, sent, tmp_path


def rows(sessions, model):  # type: ignore[no-untyped-def]
    with sessions() as db:
        return db.query(model).all()


def test_full_day_enters_at_0930_and_squares_off_at_1510(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, sent, _ = make
    runner = build(FakeData(flat_then(101.0)))
    assert run_day(runner)
    (trade,) = rows(sessions, Trade)
    assert (trade.symbol, trade.direction, trade.qty) == ("AAA", "short", 9)
    assert trade.entry_ts == datetime(2026, 11, 16, 9, 30)
    assert trade.entry_price == pytest.approx(103 * (1 - 0.0005))
    assert (trade.exit_ts, trade.exit_reason) == (datetime(2026, 11, 16, 15, 10), "square_off")
    assert trade.exit_price == pytest.approx(101 * 1.0005)
    assert trade.net_pnl == pytest.approx(trade.gross_pnl - trade.costs) and trade.net_pnl > 0
    assert runner.equity == pytest.approx(1000 + trade.net_pnl)
    (rec,) = rows(sessions, DecisionRecord)
    assert rec.final_status == "filled" and rec.stop == pytest.approx(104.03)
    assert rec.features["outcome"]["short_from_entry_time_net_pct"] > 1.5
    assert rec.risk_result["approved"] and rec.gate_result["passed"]
    assert len(rows(sessions, EquitySnapshot)) == 2
    assert any("ENTRY" in m for m in sent) and any("EXIT" in m for m in sent)


def test_stop_is_placed_after_the_fill_and_closes_the_trade(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, _ = make
    base = flat_then(101.0)
    spike = pd.Timestamp("2026-11-16 10:00")
    runner = build(FakeData(lambda ts: 106.0 if ts == spike else base(ts)))
    run_day(runner)
    (trade,) = rows(sessions, Trade)
    assert (trade.exit_reason, trade.exit_ts) == ("stop", spike.to_pydatetime())
    assert trade.exit_price == pytest.approx(106 * 1.0005)  # gapped through the stop
    assert trade.net_pnl < 0 and runner.state.account.consecutive_losses == 1


def test_kill_switch_flattens_and_stops_the_loop(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, tmp = make
    runner = build(FakeData(flat_then(101.0)))

    def kill_at_11(now: datetime) -> None:
        if now == datetime(2026, 11, 16, 11, 0):
            (tmp / "KILL").touch()

    assert run_day(runner, on_step=kill_at_11) is False
    (trade,) = rows(sessions, Trade)
    assert trade.exit_reason == "kill_switch" and trade.exit_ts == datetime(2026, 11, 16, 11, 0)
    assert runner.broker.positions() == {}


def test_stale_data_at_entry_time_means_no_trade(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, _ = make
    data = FakeData(flat_then(101.0))
    data.last_bar = pd.Timestamp("2026-11-16 09:20")  # the feed stops at 09:20
    run_day(build(data), until="10:00")
    assert rows(sessions, Trade) == []
    (rec,) = rows(sessions, DecisionRecord)
    assert rec.final_status == "rejected_stale_data"


def test_a_failing_feed_fails_closed_and_keeps_the_loop_alive(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, _ = make
    data = FakeData(flat_then(101.0))
    data.fail_news = True
    assert run_day(build(data), until="10:00")
    assert rows(sessions, Trade) == [] and rows(sessions, DecisionRecord) == []
    assert any(e.level == "ERROR" and "feed down" in e.message for e in rows(sessions, Event))


def test_too_expensive_for_the_account_is_skipped_not_rounded_up(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, _ = make
    scale = 20.0
    base = flat_then(101.0)
    run_day(build(FakeData(lambda ts: base(ts) * scale, prev_close=100.0 * scale)), until="10:00")
    assert rows(sessions, Trade) == []
    (rec,) = rows(sessions, DecisionRecord)
    assert rec.final_status == "rejected_risk_qty_below_1"


def test_weekend_does_nothing(make) -> None:  # type: ignore[no-untyped-def]
    build, sessions, _, _ = make
    runner = build(FakeData(flat_then(101.0)))
    assert runner.step(datetime(2026, 11, 14, 9, 31))
    assert rows(sessions, DecisionRecord) == [] and rows(sessions, Event) == []
