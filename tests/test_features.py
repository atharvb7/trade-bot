"""Look-ahead tests (Rule 5): truncated-history features must equal full-history features."""

import numpy as np
import pandas as pd

from bot.data.candles import resample_closed
from bot.data.synthetic import make_1m
from bot.features.engine import FEATURE_COLUMNS, compute_features


def _data() -> tuple[pd.DataFrame, pd.DataFrame]:
    return make_1m(days=4, seed=1), make_1m(days=4, seed=2, base=20000)


def test_no_lookahead_prefix_invariance() -> None:
    stock, nifty = _data()
    full = compute_features(stock, nifty)
    for cut in (130, 400, 777, 1100):  # arbitrary points incl. mid-bar for 5m/15m
        s, n = stock.iloc[:cut], nifty.iloc[:cut]
        part = compute_features(s, n)
        pd.testing.assert_frame_equal(
            part, full.iloc[:cut], check_exact=False, rtol=1e-9, atol=1e-9
        )


def test_future_change_does_not_alter_past_features() -> None:
    stock, nifty = _data()
    base = compute_features(stock, nifty)
    stock2, nifty2 = stock.copy(), nifty.copy()
    k = 600
    stock2.iloc[k:, :4] *= 1.5
    nifty2.iloc[k:, :4] *= 0.5
    alt = compute_features(stock2, nifty2)
    pd.testing.assert_frame_equal(base.iloc[:k], alt.iloc[:k])


def test_feature_timestamp_not_after_decision_time() -> None:
    stock, nifty = _data()
    f = compute_features(stock, nifty)
    assert (f["available_at"] == f.index + pd.Timedelta(minutes=1)).all()
    for m in (5, 15):
        bars = resample_closed(nifty, m)
        assert (bars["available_at"] == bars.index + pd.Timedelta(minutes=m)).all()


def test_resample_drops_partial_bar() -> None:
    _, nifty = _data()
    part = resample_closed(nifty.iloc[:12], 5)  # 12 one-minute bars -> only 2 complete 5m bars
    assert len(part) == 2


def test_or_undefined_inside_first_15_minutes() -> None:
    stock, nifty = _data()
    f = compute_features(stock, nifty)
    first_day = f.iloc[:15]
    assert first_day["dist_or_high_pct"].isna().all()
    assert f.iloc[15:375]["dist_or_high_pct"].notna().all()


def test_feature_columns_present_and_finite_late_in_data() -> None:
    stock, nifty = _data()
    f = compute_features(stock, nifty)
    late = f.iloc[-100:][FEATURE_COLUMNS]
    assert not late.isna().any().any()
    assert np.isfinite(late.to_numpy()).all()


def test_no_lookahead_5m_bars() -> None:
    """Same prefix-invariance check when features are computed on 5-minute bars."""
    stock, nifty = _data()
    full = compute_features(stock, nifty, bar_minutes=5)
    assert (full["available_at"] == full.index + pd.Timedelta(minutes=5)).all()
    for cut in (130, 403, 777, 1100):  # 403 cuts mid-way through a 5m bar
        part = compute_features(stock.iloc[:cut], nifty.iloc[:cut], bar_minutes=5)
        assert len(part) == cut // 5  # the partial 5m bar is dropped, never half-formed
        pd.testing.assert_frame_equal(
            part, full.iloc[: len(part)], check_exact=False, rtol=1e-9, atol=1e-9
        )


def test_5m_bars_have_75_per_day() -> None:
    stock, nifty = _data()
    f = compute_features(stock, nifty, bar_minutes=5)
    assert f.groupby(f.index.normalize()).size().eq(75).all()
    assert f["minutes_to_close"].iloc[74] == 0  # 15:25 bar closes at 15:30
