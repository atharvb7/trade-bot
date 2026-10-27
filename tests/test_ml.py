"""Phase 4 checks: shuffled labels collapse to random, no label leakage, train/infer parity."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bot.config import MLCfg, load_config
from bot.data.synthetic import make_1m
from bot.detectors.base import Frame
from bot.features.engine import bar_table
from bot.ml.dataset import ML_FEATURES, build_dataset, candidate_features
from bot.ml.inference import MLScorer
from bot.ml.registry import load_model, save_model
from bot.ml.trainer import NO_TRADE, make_folds, train_fold, tune_threshold, walk_forward

FAST = MLCfg(
    lgb_params={"n_estimators": 60, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 20}
)


def synthetic_dataset(months: int = 9, per_day: int = 12, signal: float = 1.5) -> pd.DataFrame:
    """Rows with ML_FEATURES; label depends on two features plus noise (learnable)."""
    rng = np.random.default_rng(0)
    days = pd.bdate_range("2025-01-01", periods=months * 21)
    ts = np.repeat(days + pd.Timedelta(hours=10), per_day)
    n = len(ts)
    X = pd.DataFrame(rng.normal(size=(n, len(ML_FEATURES))), columns=ML_FEATURES)
    logit = signal * X["rsi_slope_3"] - signal * X["price_vs_vwap_pct"] - 0.4
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    rr = 1.5
    net_r = np.where(y == 1, rr, -1.0) - 0.3
    return X.assign(decision_ts=ts, label=y, net_r=net_r)


def test_learns_real_signal_and_shuffled_labels_collapse() -> None:
    """Real labels -> high OOS AUC; shuffled train+val labels -> AUC ~0.5 on average.

    A single noise model can sit a few points off 0.5 by chance (it is a random function of
    the same features that carry the signal), so the shuffled check averages several seeds.
    """
    from sklearn.metrics import roc_auc_score

    data = synthetic_dataset(months=12, per_day=40)
    _, real, _ = walk_forward(data, FAST)
    assert roc_auc_score(real["label"], real["ml_prob"]) > 0.75
    aucs = []
    for seed in range(8):
        _, shuf, _ = walk_forward(data, FAST.model_copy(update={"seed": seed}), shuffle_labels=True)
        aucs.append(roc_auc_score(shuf["label"], shuf["ml_prob"]))
    assert abs(float(np.mean(aucs)) - 0.5) < 0.02


def test_folds_are_ordered_and_disjoint() -> None:
    data = synthetic_dataset()
    folds = make_folds(data["decision_ts"], FAST)
    assert len(folds) == 9 - 8 + 1
    for f in folds:
        assert f.train[1] < f.val[0] and f.val[1] < f.test[0]
    tests = [f.test for f in folds]
    assert all(a[1] < b[0] for a, b in zip(tests, tests[1:], strict=False))


def test_threshold_fails_closed_when_nothing_positive() -> None:
    p = np.linspace(0, 1, 200)
    thr, _ = tune_threshold(p, pd.Series(-0.5, index=range(200)), FAST)
    assert thr == NO_TRADE
    good = pd.Series(np.where(p > 0.5, 1.0, -1.0))
    thr, _ = tune_threshold(p, good, FAST)
    assert 0.5 <= thr <= 0.55


def test_no_label_columns_in_features() -> None:
    forbidden = {"label", "outcome", "pnl_per_share", "gross_r", "net_r", "target", "stop", "entry"}
    assert not forbidden & set(ML_FEATURES)


def _frames(stock: pd.DataFrame, nifty: pd.DataFrame) -> dict[str, Frame]:
    return {"X": Frame.from_df(bar_table(stock, nifty, 5))}


def test_dataset_features_ignore_the_future() -> None:
    """Changing bars AFTER a candidate's decision time must not change its features."""
    cfg = load_config()
    stock, nifty = make_1m(days=6, seed=3), make_1m(days=6, seed=4, base=20000)
    base = build_dataset(_frames(stock, nifty), cfg, 5)
    assert len(base) > 0
    cut = stock.index[4 * 375]  # start of day 5
    s2 = stock.copy()
    s2.loc[s2.index >= cut, ["open", "high", "low", "close"]] *= 1.3
    alt = build_dataset(_frames(s2, nifty), cfg, 5)
    early_b = base[base["decision_ts"] <= cut].reset_index(drop=True)
    early_a = alt[alt["decision_ts"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(early_b[ML_FEATURES], early_a[ML_FEATURES])


def test_inference_matches_training_features_and_registry_roundtrip(tmp_path: Path) -> None:
    cfg = load_config()
    stock, nifty = make_1m(days=30, seed=5), make_1m(days=30, seed=6, base=20000)
    frames = _frames(stock, nifty)
    data = build_dataset(frames, cfg, 5)
    half = len(data) // 2
    model = train_fold(data.iloc[:half], data.iloc[half:], FAST)
    # Re-detect one candidate and score it through the live path.
    from bot.detectors import ALL_DETECTORS

    row = data.iloc[-1]
    fr = frames["X"]
    i = int(np.flatnonzero(fr.index == row["ts"])[0])
    cand = next(
        c
        for d in ALL_DETECTORS
        if (c := d.detect("X", fr, i, cfg.app.detectors)) and c.setup == row["setup"]
    )
    feats = candidate_features(cand, fr, i)
    assert feats == pytest.approx({k: row[k] for k in feats}, nan_ok=True)
    live = MLScorer(model)(cand, fr, i)
    offline = float(model.predict(data.iloc[[-1]])[0])
    assert live == pytest.approx(offline)
    v = save_model(model, tmp_path)
    assert MLScorer(load_model(v, tmp_path), v)(cand, fr, i) == pytest.approx(live)
