from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.backtest.daily import (
    VARIANTS,
    build_signals,
    candidates,
    load_bhavcopy,
    net_return,
    summarize,
)
from bot.config import CostsCfg

ZERO = CostsCfg(
    brokerage_pct=0, brokerage_cap_per_order=20, stt_sell_pct=0, exchange_txn_pct=0,
    sebi_pct=0, stamp_buy_pct=0, gst_pct=0, slippage_pct=0,
)  # fmt: skip


def rows(n_days: int = 60, n_sym: int = 8, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_sym):
        close = 100.0
        for d in pd.bdate_range("2024-01-01", periods=n_days):
            prev = close
            opn = prev * (1 + rng.normal(0, 0.005))
            close = opn * (1 + rng.normal(0, 0.01))
            out.append((d, f"S{i}", prev, opn, close, float(rng.uniform(50, 500))))
    return pd.DataFrame(out, columns=["date", "symbol", "prev_close", "open", "close", "turnover"])


def test_signals_do_not_see_the_trade_day_or_later() -> None:
    base = rows()
    cut = base["date"].unique()[40]
    changed = base.copy()
    late = changed["date"] >= cut
    changed.loc[late, ["open", "close", "turnover"]] *= 1.7  # prev_close(cut) is known pre-open
    a, b = build_signals(base), build_signals(changed)
    for name in ("intraday20", "overnight20", "ret1", "shock_up", "shock_down"):
        pd.testing.assert_series_equal(a[name].loc[cut], b[name].loc[cut], check_names=False)


def test_net_return_hand_computed() -> None:
    cfg = ZERO.model_copy(update={"slippage_pct": 0.05, "stt_sell_pct": 0.025})
    costs = CostModel(cfg)
    r = pd.Series([0.01])
    # long: buy 1.0005, sell 1.01 * 0.9995 = 1.009495, STT on the sell
    assert net_return(r, "long", costs).iloc[0] == pytest.approx(
        1.009495 - 1.0005 - 1.009495 * 0.00025
    )
    # short: sell 0.9995 (STT), buy back 1.01 * 1.0005 = 1.010505
    assert net_return(r, "short", costs).iloc[0] == pytest.approx(
        0.9995 - 1.010505 - 0.9995 * 0.00025
    )


def test_candidates_pick_extremes_and_flip_short_gross() -> None:
    sig = build_signals(rows())
    costs = CostModel(ZERO)
    d5 = candidates(sig, VARIANTS[4], costs, top=2)  # lowest ret1, long
    day = d5["date"].iloc[-1]
    expect = sig["ret1"].loc[day].where(sig["universe"].loc[day]).nsmallest(2).index.tolist()
    assert d5[d5["date"] == day]["symbol"].tolist() == expect
    assert np.allclose(d5["gross"], d5["net"])
    d6 = candidates(sig, VARIANTS[5], costs, top=2)  # highest ret1, short
    row = d6.iloc[-1]
    assert row["gross"] == pytest.approx(-sig["intraday"].loc[row["date"], row["symbol"]])
    assert summarize(d6)["n"] == len(d6)


def test_load_bhavcopy_uses_file_date_and_skips_late_files(tmp_path: Path) -> None:
    head = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
    head += "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, "
    head += "DELIV_PER"
    row = "{}, {}, {}, 10.0, 10.1, 11, 9, 10.2, 10.3, 10.2, 100, 5.5, 7, -, -"
    day1 = "\n".join(
        [head, row.format("AAA", "EQ", "01-Jan-2024"), row.format("B", "BE", "01-Jan-2024")]
    )
    (tmp_path / "20240101.csv").write_text(day1)
    (tmp_path / "20240102.csv").write_text(day1)  # holiday: archive repeats the last session
    (tmp_path / "20240103.csv").write_text(
        "\n".join([head, row.format("AAA", "EQ", "03-Jan-2024")])
    )
    out = load_bhavcopy(tmp_path, last_day=date(2024, 1, 2))
    assert out[["symbol", "date"]].values.tolist() == [["AAA", pd.Timestamp("2024-01-01")]]
    assert len(load_bhavcopy(tmp_path)) == 2
