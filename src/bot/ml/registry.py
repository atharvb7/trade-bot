"""Model registry: models/<version>/{model.joblib, model.txt, meta.json} (gitignored).

model.joblib is the loadable artefact (pinned lightgbm/sklearn versions); model.txt is the
human-readable LightGBM dump for inspection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb

from bot.config import ROOT
from bot.ml.trainer import TrainedModel

MODELS_DIR = ROOT / "models"


def save_model(m: TrainedModel, base: Path = MODELS_DIR) -> str:
    text = m.model.booster_.model_to_string()
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    version = f"{datetime.now():%Y%m%d_%H%M%S}_{digest}"
    out = base / version
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.txt").write_text(text)
    joblib.dump(m, out / "model.joblib")  # full fitted model + calibrator + threshold
    meta = {
        "version": version,
        "features": m.features,
        "threshold": m.threshold,
        "lightgbm": lgb.__version__,
        **m.meta,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    return version


def latest_version(base: Path = MODELS_DIR) -> str | None:
    vs = (
        sorted(p.name for p in base.glob("*") if (p / "meta.json").exists())
        if base.exists()
        else []
    )
    return vs[-1] if vs else None


def load_model(version: str, base: Path = MODELS_DIR) -> TrainedModel:
    m = joblib.load(base / version / "model.joblib")
    if not isinstance(m, TrainedModel):
        raise TypeError(f"{version} is not a TrainedModel")
    return m
