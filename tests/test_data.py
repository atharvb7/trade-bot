from datetime import datetime
from pathlib import Path

import pandas as pd

from bot.data.candles import CandleBuilder
from bot.data.quality import check
from bot.data.store import read_1m, write_1m
from bot.data.synthetic import make_1m


def test_quality_clean_data() -> None:
    r = check(make_1m(days=3), "X")
    assert r.missing_bars == 0 and r.duplicate_bars == 0 and r.bad_ohlc_bars == 0
    assert r.partial_days == []


def test_quality_detects_gap_and_dupe() -> None:
    d = make_1m(days=2)
    d = pd.concat([d.drop(d.index[100:110]), d.iloc[[5]]])
    r = check(d, "X")
    assert r.missing_bars == 10 and r.duplicate_bars == 1 and len(r.partial_days) == 1


def test_store_roundtrip(tmp_path: Path) -> None:
    d = make_1m(days=3)
    write_1m(d, "NIFTY 50", tmp_path)
    write_1m(d, "NIFTY 50", tmp_path)  # idempotent
    pd.testing.assert_frame_equal(read_1m("NIFTY 50", tmp_path), d, check_freq=False)


def test_candle_builder() -> None:
    b = CandleBuilder()
    t = lambda s: datetime(2026, 1, 5, 9, 15, s)  # noqa: E731
    assert b.on_tick(t(1), 100, 1000) is None
    b.on_tick(t(20), 102, 1500)
    b.on_tick(t(50), 99, 1800)
    bar = b.on_tick(datetime(2026, 1, 5, 9, 16, 2), 101, 2000)
    assert bar is not None
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (100, 102, 99, 99)


def test_clean_drops_preopen_and_special_sessions() -> None:
    from bot.data.sessions import clean_1m

    d = make_1m(days=3)
    pre = d.iloc[:2].copy()
    pre.index = pre.index - pd.Timedelta(minutes=8)  # 09:07, 09:08
    muhurat = make_1m(days=1, start="2026-01-12").iloc[270:330]  # 60-bar evening session
    raw = pd.concat([pre, d, muhurat]).sort_index()
    clean, notes = clean_1m(raw)
    assert len(clean) == 3 * 375
    assert notes["dropped_partial_days"] == ["2026-01-12:60"]
    assert len(notes["out_of_session_days"]) >= 1
