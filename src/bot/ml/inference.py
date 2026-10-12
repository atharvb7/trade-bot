"""Scores candidates with a trained model. Fail closed: any error returns None (= no trade)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from bot.detectors.base import Candidate, Frame
from bot.ml.dataset import candidate_features
from bot.ml.registry import MODELS_DIR, load_model
from bot.ml.trainer import TrainedModel

log = logging.getLogger("bot.ml")


class MLScorer:
    def __init__(self, model: TrainedModel, version: str = "in-memory") -> None:
        self.m, self.version = model, version

    @classmethod
    def load(cls, version: str, base: Path = MODELS_DIR) -> MLScorer:
        return cls(load_model(version, base), version)

    def __call__(self, c: Candidate, fr: Frame, i: int) -> float | None:
        try:
            x = pd.DataFrame([candidate_features(c, fr, i)])[self.m.features]
            return float(self.m.predict(x)[0])
        except Exception:
            log.exception("ML scoring failed for %s %s", c.symbol, c.setup)
            return None
