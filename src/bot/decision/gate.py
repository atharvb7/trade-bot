"""Decision gate: combines detector, ML and Jev outputs against config thresholds."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.config import DecisionCfg
from bot.detectors.base import Candidate


@dataclass
class JevAnswer:
    action: str  # long | short | stay_out
    action_confidence: float
    quality: float
    trap: float


@dataclass
class GateResult:
    passed: bool
    failed_gate: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)


def evaluate_gate(
    cfg: DecisionCfg, cand: Candidate | None, ml_prob: float | None, jev: JevAnswer | None
) -> GateResult:
    """Fail closed: a missing ML/Jev output in a mode that needs it is a rejection."""
    if cand is None:
        return GateResult(False, "no_candidate")
    checks: dict[str, bool] = {"candidate": True}
    if cfg.mode in ("rules_ml", "rules_ml_jev"):
        checks["ml_prob"] = ml_prob is not None and ml_prob >= cfg.ml_min_prob
    if cfg.mode == "rules_ml_jev":
        checks["jev_present"] = jev is not None
        if jev is not None:
            checks["jev_action"] = jev.action == cand.direction
            checks["jev_confidence"] = jev.action_confidence >= cfg.jev_min_conf
            checks["jev_quality"] = jev.quality >= cfg.jev_min_quality
            checks["jev_trap"] = jev.trap < cfg.jev_max_trap
    failed = next((k for k, ok in checks.items() if not ok), None)
    return GateResult(failed is None, failed, checks)
