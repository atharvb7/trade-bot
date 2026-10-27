"""Walk-forward LightGBM training with Platt calibration and validation-only threshold tuning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from bot.config import MLCfg
from bot.ml.dataset import ML_FEATURES

NO_TRADE = 1.01  # threshold that no probability can reach -> fold trades nothing


class PlattCalibrator:
    """Logistic fit on the log-odds of the raw model probability (fit on validation only)."""

    def __init__(self) -> None:
        self.lr = LogisticRegression(C=1e6)

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.asarray(np.log(p / (1 - p))).reshape(-1, 1)

    def fit(self, p_raw: np.ndarray, y: np.ndarray) -> PlattCalibrator:
        self.lr.fit(self._logit(p_raw), y)
        return self

    def transform(self, p_raw: np.ndarray) -> np.ndarray:
        return np.asarray(self.lr.predict_proba(self._logit(p_raw))[:, 1])


@dataclass
class TrainedModel:
    model: lgb.LGBMClassifier
    calibrator: PlattCalibrator
    features: list[str]
    threshold: float
    meta: dict[str, Any] = field(default_factory=dict)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raw = np.asarray(self.model.predict_proba(X[self.features]))[:, 1]
        return self.calibrator.transform(raw)


def _safe_auc(y: pd.Series, p: np.ndarray) -> float:
    return float(roc_auc_score(y, p)) if y.nunique() == 2 else float("nan")


def tune_threshold(p: np.ndarray, net_r: pd.Series, cfg: MLCfg) -> tuple[float, pd.DataFrame]:
    """Pick the grid threshold with the best mean net R on validation; none positive -> no trade."""
    rows = []
    for t in cfg.threshold_grid:
        m = p >= t
        rows.append(
            {
                "threshold": t,
                "n": int(m.sum()),
                "mean_net_r": float(net_r[m].mean()) if m.any() else float("nan"),
            }
        )
    table = pd.DataFrame(rows)
    ok = table[(table["n"] >= cfg.min_val_candidates) & (table["mean_net_r"] > 0)]
    # best mean net R; ties go to the LOWER threshold (more trades for the same edge)
    ranked = ok.sort_values(["mean_net_r", "threshold"], ascending=[False, True])
    best = float(ranked["threshold"].iloc[0]) if len(ok) else NO_TRADE
    return best, table


def _shuffled(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Permute (label, net_r) pairs across rows, keeping features fixed."""
    perm = np.random.default_rng(seed).permutation(len(df))
    out = df.copy()
    for col in ("label", "net_r"):
        out[col] = df[col].to_numpy()[perm]
    return out


def train_fold(
    train: pd.DataFrame, val: pd.DataFrame, cfg: MLCfg, shuffle_labels: bool = False
) -> TrainedModel:
    if shuffle_labels:
        # Sanity check: no stage (fit, calibration, threshold) may see real labels.
        train, val = _shuffled(train, cfg.seed), _shuffled(val, cfg.seed + 1)
    y = train["label"].to_numpy()
    params: dict[str, Any] = {**cfg.lgb_params, "random_state": cfg.seed, "verbose": -1}
    model = lgb.LGBMClassifier(deterministic=True, **params)
    model.fit(train[ML_FEATURES], y)
    raw_val = np.asarray(model.predict_proba(val[ML_FEATURES]))[:, 1]
    cal = PlattCalibrator().fit(raw_val, val["label"].to_numpy())
    p_val = cal.transform(raw_val)
    thr, table = tune_threshold(p_val, val["net_r"], cfg)
    imp = dict(zip(ML_FEATURES, model.booster_.feature_importance("gain").tolist(), strict=True))
    return TrainedModel(
        model,
        cal,
        list(ML_FEATURES),
        thr,
        {
            "val_auc": _safe_auc(val["label"], raw_val),
            "val_brier": float(brier_score_loss(val["label"], p_val)),
            "threshold_table": table.to_dict("records"),
            "feature_importance": dict(sorted(imp.items(), key=lambda kv: -kv[1])),
            "train_rows": len(train),
            "val_rows": len(val),
            "train_win_rate": float(train["label"].mean()),
        },
    )


@dataclass
class Fold:
    k: int
    train: tuple[pd.Timestamp, pd.Timestamp]
    val: tuple[pd.Timestamp, pd.Timestamp]
    test: tuple[pd.Timestamp, pd.Timestamp]


def make_folds(ts: pd.Series, cfg: MLCfg) -> list[Fold]:
    """Rolling calendar-month folds: [train | val | test], stepping one test window at a time."""
    months = pd.PeriodIndex(pd.to_datetime(ts).dt.to_period("M").unique()).sort_values()
    span = cfg.train_months + cfg.val_months + cfg.test_months
    folds: list[Fold] = []
    k = 0
    while k + span <= len(months):
        tr = months[k : k + cfg.train_months]
        va = months[k + cfg.train_months : k + cfg.train_months + cfg.val_months]
        te = months[k + cfg.train_months + cfg.val_months : k + span]
        folds.append(
            Fold(
                len(folds),
                (tr[0].start_time, tr[-1].end_time),
                (va[0].start_time, va[-1].end_time),
                (te[0].start_time, te[-1].end_time),
            )
        )
        k += cfg.test_months
    return folds


def _between(df: pd.DataFrame, w: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    return df[(df["decision_ts"] >= w[0]) & (df["decision_ts"] <= w[1])]


def walk_forward(
    data: pd.DataFrame, cfg: MLCfg, shuffle_labels: bool = False
) -> tuple[list[TrainedModel], pd.DataFrame, list[Fold]]:
    """Returns per-fold models and OUT-OF-SAMPLE test predictions (prob, fold, threshold)."""
    folds = make_folds(data["decision_ts"], cfg)
    models, preds = [], []
    for f in folds:
        tr, va, te = _between(data, f.train), _between(data, f.val), _between(data, f.test)
        if tr["label"].nunique() < 2 or va["label"].nunique() < 2 or te.empty:
            continue
        m = train_fold(tr, va, cfg, shuffle_labels)
        p = m.predict(te)
        m.meta.update(
            {
                "fold": f.k,
                "train": [str(x) for x in f.train],
                "val": [str(x) for x in f.val],
                "test": [str(x) for x in f.test],
                "test_rows": len(te),
                "test_auc": _safe_auc(te["label"], p),
                "test_brier": float(brier_score_loss(te["label"], p)),
                "test_brier_base_rate": float(
                    brier_score_loss(te["label"], np.full(len(te), tr["label"].mean()))
                ),
            }
        )
        models.append(m)
        preds.append(te.assign(ml_prob=p, fold=f.k, threshold=m.threshold))
    return models, (pd.concat(preds) if preds else pd.DataFrame()), folds
