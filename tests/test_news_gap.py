from datetime import date

import pandas as pd
import pytest

from bot.config import NewsGapCfg
from bot.strategy.news_gap import GapEvent, events_for, gap_events, live_universe, make_candidate

CFG = NewsGapCfg(universe_size=2)


def daily_rows() -> pd.DataFrame:
    days = pd.bdate_range("2026-10-01", periods=20)
    rows = [(d, s, 100.0, t) for d in days for s, t in (("A", 50.0), ("B", 30.0), ("C", 10.0))]
    rows += [(days[-1], "NEW", 100.0, 999.0)]  # listed one session ago: no 20-day history
    rows += [(d, "PENNY", 5.0, 900.0) for d in days]
    return pd.DataFrame(rows, columns=["date", "symbol", "close", "turnover"])


def test_live_universe_ranks_by_turnover_and_needs_history_and_price() -> None:
    assert live_universe(daily_rows(), CFG) == ["A", "B"]
    assert live_universe(daily_rows().query("date > '2026-10-10'"), CFG) == []  # < 20 sessions


def test_events_for_takes_news_since_the_last_close_only() -> None:
    sessions = pd.DatetimeIndex(["2026-11-12", "2026-11-13"])  # Thu, Fri; today is Mon 16th
    ann = pd.DataFrame({
        "symbol": ["A", "A", "B", "C", "D"],
        "ts": pd.to_datetime(["2026-11-13 18:00", "2026-11-14 10:00", "2026-11-16 08:30",
                              "2026-11-13 12:00", "2026-11-16 09:05"]),
        "kind": ["order", "results", "results", "order", "order"],
    })  # fmt: skip
    assert events_for(date(2026, 11, 16), ann, sessions) == {"A": "order", "B": "results"}


def test_gap_events_filter_and_order() -> None:
    quotes = {"A": (103.0, 100.0), "B": (101.9, 100.0), "C": (110.0, 100.0)}
    got = gap_events({"A": "order", "B": "order", "C": "results", "D": "order"}, quotes, CFG)
    assert [e.symbol for e in got] == ["C", "A"]


def test_make_candidate_stop_is_morning_high_with_a_floor() -> None:
    idx = pd.date_range("2026-11-16 09:15", periods=3, freq="1min")
    bars = pd.DataFrame({"high": [106.0, 104.0, 103.0], "close": [104.0, 103.0, 102.0]}, index=idx)
    ev = GapEvent("A", "order", 105.0, 100.0)
    c = make_candidate(ev, bars, CFG)
    assert (c.direction, c.entry, c.stop, c.target, c.ts) == ("short", 102.0, 106.0, 100.0, idx[-1])
    low = make_candidate(ev, bars.assign(high=102.2), CFG)
    assert low.stop == pytest.approx(102.0 * 1.01)
