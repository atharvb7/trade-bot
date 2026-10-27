"""Phase 4: build the candidate dataset, walk-forward train, and compare rules_only vs rules_ml.

Everything reported is out-of-sample (test months). Thresholds/calibration come from each
fold's validation month only. Also runs the shuffled-label and cost-doubling sanity checks,
and registers every fold model plus a final model trained on the most recent window.

Usage: python scripts/train_model.py [--shuffle-seeds 5]
"""

import argparse
import json
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from bot.analytics.funnel import calibration_table
from bot.backtest.engine import Backtester, BacktestResult
from bot.backtest.report import save_run
from bot.config import ROOT, Config, load_config
from bot.data.store import read_1m
from bot.detectors.base import Frame
from bot.features.engine import bar_table
from bot.ml.dataset import build_dataset
from bot.ml.inference import MLScorer
from bot.ml.registry import save_model
from bot.ml.trainer import NO_TRADE, TrainedModel, train_fold, walk_forward

ap = argparse.ArgumentParser()
ap.add_argument("--shuffle-seeds", type=int, default=5)
args = ap.parse_args()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
cfg = load_config()
bm = cfg.app.bar_minutes
OUT = ROOT / "data" / "ml"
OUT.mkdir(parents=True, exist_ok=True)

# 1. dataset ------------------------------------------------------------------------------
nifty = read_1m(cfg.watchlist.index)
tables = {s: bar_table(read_1m(s), nifty, bm) for s in cfg.watchlist.symbols}
frames = {s: Frame.from_df(t) for s, t in tables.items()}
data = build_dataset(frames, cfg, bm)
data.to_parquet(OUT / f"{STAMP}_dataset.parquet")
print(
    f"dataset: {len(data)} candidates, {data['decision_ts'].min()} .. {data['decision_ts'].max()}, "
    f"win rate {data['label'].mean() * 100:.1f}%, mean net R {data['net_r'].mean():+.3f}"
)

# 2. walk-forward ---------------------------------------------------------------------------
models, oos, folds = walk_forward(data, cfg.app.ml)
fold_rows = []
for m in models:
    k = m.meta["fold"]
    te = oos[oos["fold"] == k]
    kept = te[te["ml_prob"] >= m.threshold]
    fold_rows.append(
        {
            "fold": k,
            "test": m.meta["test"][0][:7],
            "train_rows": m.meta["train_rows"],
            "test_rows": len(te),
            "test_auc": m.meta["test_auc"],
            "test_brier": m.meta["test_brier"],
            "base_brier": m.meta["test_brier_base_rate"],
            "threshold": "no-trade" if m.threshold == NO_TRADE else m.threshold,
            "kept": len(kept),
            "kept_net_r": kept["net_r"].mean() if len(kept) else float("nan"),
            "all_net_r": te["net_r"].mean(),
        }
    )
fold_df = pd.DataFrame(fold_rows)
print("\n=== walk-forward folds (test month = out-of-sample) ===")
print(fold_df.round(3).to_string(index=False))
pooled_auc = roc_auc_score(oos["label"], oos["ml_prob"])
pooled_brier = brier_score_loss(oos["label"], oos["ml_prob"])
base_brier = brier_score_loss(oos["label"], np.full(len(oos), data["label"].mean()))
cal = calibration_table(oos["ml_prob"], oos["label"])
print(f"\npooled OOS AUC {pooled_auc:.3f} | Brier {pooled_brier:.4f} vs base-rate {base_brier:.4f}")
print("calibration (OOS):\n" + cal.round(3).to_string(index=False))

# 3. shuffled-label sanity check (train+val labels shuffled; average over seeds) -----------
shuf_aucs = []
for seed in range(args.shuffle_seeds):
    _s_models, s_oos, _s_folds = walk_forward(
        data, cfg.app.ml.model_copy(update={"seed": seed}), shuffle_labels=True
    )
    shuf_aucs.append(float(roc_auc_score(s_oos["label"], s_oos["ml_prob"])))
print(
    f"\nshuffled-label OOS AUC: mean {np.mean(shuf_aucs):.3f} over {len(shuf_aucs)} seeds "
    f"(each: {', '.join(f'{a:.3f}' for a in shuf_aucs)})"
)


# 4. OOS backtests on the test months, equity chained across folds -------------------------
def window(lo: pd.Timestamp, hi: pd.Timestamp) -> dict[str, Frame]:
    return {s: Frame.from_df(t[(t.index >= lo) & (t.index <= hi)]) for s, t in tables.items()}


def chained(
    base: Config, mode: str, cost_mult: float = 1.0
) -> tuple[BacktestResult, dict[str, Frame]]:
    equity = base.app.starting_capital
    parts: list[BacktestResult] = []
    shown: dict[str, list[pd.DataFrame]] = {}
    for m in models:
        lo, hi = (pd.Timestamp(x) for x in m.meta["test"])
        c = base.model_copy(deep=True)
        c.app.decision.mode = mode  # type: ignore[assignment]
        c.app.decision.ml_min_prob = m.threshold
        c.app.starting_capital = equity
        for f in type(c.costs).model_fields:
            setattr(c.costs, f, getattr(c.costs, f) * cost_mult)
        fr = window(lo, hi)
        scorer = MLScorer(m, f"fold{m.meta['fold']}") if mode != "rules_only" else None
        res = Backtester(c, fr, ml_prob_fn=scorer, bar_minutes=bm).run()
        offset = sum(len(p.decisions) for p in parts)
        if len(res.decisions):
            res.decisions["decision_id"] += offset
        if len(res.trades):
            res.trades["decision_id"] += offset
        parts.append(res)
        equity += float(res.trades["net_pnl"].sum()) if len(res.trades) else 0.0
        for s, f_ in fr.items():
            shown.setdefault(s, []).append(pd.DataFrame(f_.cols, index=f_.index))
    merged = BacktestResult(
        trades=pd.concat([p.trades for p in parts if len(p.trades)] or [pd.DataFrame()]),
        decisions=pd.concat([p.decisions for p in parts]),
        equity=pd.concat([p.equity for p in parts]),
        n_days=sum(p.n_days for p in parts),
        start_capital=base.app.starting_capital,
        config={**parts[0].config, "decision_mode": mode, "cost_multiplier": cost_mult},
    )
    return merged, {s: Frame.from_df(pd.concat(v)) for s, v in shown.items()}


variants = {}
for name, mode, mult in [
    ("rules_only", "rules_only", 1.0),
    ("rules_ml", "rules_ml", 1.0),
    ("rules_ml_costx2", "rules_ml", 2.0),
]:
    res, fr = chained(cfg, mode, mult)
    _run_dir, met = save_run(
        res,
        fr,
        f"{STAMP}_wf_{name}_{bm}m",
        {"mode": mode, "bar_minutes": bm, "walk_forward": True, "cost_multiplier": mult},
    )
    variants[name] = met
cmp = pd.DataFrame(variants).T[
    [
        "trades",
        "win_rate",
        "expectancy",
        "net_pnl",
        "max_drawdown_pct",
        "profit_factor",
        "sharpe",
        "total_costs",
        "final_equity",
    ]
]
print("\n=== OOS backtest on test months (equity chained, ₹1,000 start) ===")
print(cmp.round(3).to_string())

# 5. registry: fold models + final model on the most recent train/val window ----------------
versions = [save_model(m) for m in models]
last = models[-1]
lo_tr = pd.Timestamp(last.meta["train"][0]) + pd.DateOffset(months=cfg.app.ml.test_months)
recent = data[data["decision_ts"] >= lo_tr]
months = recent["decision_ts"].dt.to_period("M")
val_m = months.max()
final: TrainedModel = train_fold(recent[months < val_m], recent[months == val_m], cfg.app.ml)
final.meta.update(
    {
        "role": "final",
        "train": [str(recent["decision_ts"].min()), str(val_m)],
        "walk_forward": {
            "pooled_oos_auc": pooled_auc,
            "pooled_oos_brier": pooled_brier,
            "base_rate_brier": base_brier,
            "shuffled_auc_mean": float(np.mean(shuf_aucs)),
            "oos_backtest": variants,
        },
    }
)
final_v = save_model(final)
print(
    f"\nregistered fold models: {versions}\nfinal model: {final_v} (threshold "
    f"{'no-trade' if final.threshold == NO_TRADE else final.threshold})"
)

report = {
    "stamp": STAMP,
    "dataset_rows": len(data),
    "folds": fold_df.to_dict("records"),
    "pooled_oos_auc": pooled_auc,
    "pooled_oos_brier": pooled_brier,
    "base_rate_brier": base_brier,
    "calibration": cal.to_dict("records"),
    "shuffled_aucs": shuf_aucs,
    "oos_backtests": variants,
    "fold_models": versions,
    "final_model": final_v,
    "top_features": dict(list(final.meta["feature_importance"].items())[:10]),
}
(OUT / f"{STAMP}_report.json").write_text(json.dumps(report, indent=1, default=str))
print(f"report: data/ml/{STAMP}_report.json")
