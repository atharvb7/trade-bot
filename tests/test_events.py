import pandas as pd

from bot.backtest.events import classify, event_flags, trade_day


def test_classify_follows_the_registered_rules() -> None:
    assert classify("Bagging/Receiving of orders or contracts", "") == "order"
    assert classify("Updates", "X Limited has informed about receipt of order from NTPC") == "order"
    assert classify("Press Release", "X has bagged a Rs 500 crore contract") == "order"
    assert classify("Financial Result Updates", "") == "results"
    assert classify("Outcome of Board Meeting", "approved the Financial Results") == "results"
    assert classify("Outcome of Board Meeting", "approved a dividend") is None
    assert classify("Trading Window", "closure") is None


def test_trade_day_maps_out_of_hours_news_to_the_next_open() -> None:
    sessions = pd.DatetimeIndex(["2024-01-05", "2024-01-08", "2024-01-09"])  # Fri, Mon, Tue
    ts = pd.Series(pd.to_datetime([
        "2024-01-05 08:59", "2024-01-05 09:00", "2024-01-05 12:00", "2024-01-05 15:30",
        "2024-01-05 15:31", "2024-01-06 11:00", "2024-01-08 07:00", "2024-01-09 18:00",
    ]))  # fmt: skip
    got = trade_day(ts, sessions)
    want = ["2024-01-05", None, None, None, "2024-01-08", "2024-01-08", "2024-01-08", None]
    assert got.isna().tolist() == [w is None for w in want]
    assert got.dropna().tolist() == [pd.Timestamp(w) for w in want if w]


def test_event_flags_shape_and_values() -> None:
    like = pd.DataFrame(
        0.0, index=pd.DatetimeIndex(["2024-01-05", "2024-01-08"]), columns=["A", "B"]
    )
    ann = pd.DataFrame({
        "symbol": ["A", "A", "ZZ"],
        "ts": pd.to_datetime(["2024-01-05 20:00", "2024-01-06 10:00", "2024-01-05 20:00"]),
        "kind": ["order", "order", "order"],
    })  # fmt: skip
    flags = event_flags(ann, like)["order"]
    assert flags.to_numpy().tolist() == [[False, False], [True, False]]
