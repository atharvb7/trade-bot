"""ML dataset: one row per tradeable candidate, features at the signal bar, forward label.

``candidate_features`` is the ONLY place the ML feature vector is built; the trainer and the
live/backtest scorer both call it, so training and inference cannot drift apart.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from bot.backtest.costs import CostModel
from bot.backtest.outcome import simulate_outcome
from bot.config import Config
from bot.detectors import ALL_DETECTORS
from bot.detectors.base import Candidate, Detector, Frame
from bot.features.engine import FEATURE_COLUMNS
from bot.risk.manager import parse_hhmm

SETUPS = ["opening_range_breakout", "vwap_reclaim", "trend_pullback"]
# atr_14 is in rupees (a stock-price proxy), so only its % form is used.
ML_FEATURES = [c for c in FEATURE_COLUMNS if c != "atr_14"] + [
    "is_long",
    "stop_pct",
    *[f"setup_{s}" for s in SETUPS],
]


def candidate_features(c: Candidate, fr: Frame, i: int) -> dict[str, float]:
    row = {k: float(fr[k][i]) for k in ML_FEATURES if k in fr.cols}
    row["is_long"] = 1.0 if c.direction == "long" else 0.0
    row["stop_pct"] = abs(c.entry - c.stop) / c.entry * 100
    for s in SETUPS:
        row[f"setup_{s}"] = 1.0 if c.setup == s else 0.0
    return row


def build_dataset(
    frames: dict[str, Frame],
    cfg: Config,
    bar_minutes: int,
    detectors: list[Detector] | None = None,
) -> pd.DataFrame:
    """All candidates whose decision time (bar close) is inside the entry window."""
    dets = detectors if detectors is not None else ALL_DETECTORS
    lo, hi = parse_hhmm(cfg.risk.no_entry_before), parse_hhmm(cfg.risk.no_entry_after)
    sq_off = parse_hhmm(cfg.risk.square_off_time)
    costs = CostModel(cfg.costs)
    close_shift = pd.Timedelta(minutes=bar_minutes)
    rows: list[dict[str, Any]] = []
    for sym, fr in frames.items():
        decide = fr.index + close_shift
        ok = (decide.time >= lo) & (decide.time <= hi)
        for i in np.flatnonzero(ok):
            for det in dets:
                c = det.detect(sym, fr, int(i), cfg.app.detectors)
                if c is None:
                    continue
                out = simulate_outcome(c, fr, int(i), cfg.costs.slippage_pct, sq_off, bar_minutes)
                if out.reason == "no_entry":
                    continue
                risk = abs(c.entry - c.stop)
                fee = costs.round_trip_fees(c.direction, out.entry_price, out.exit_price)
                rows.append(
                    {
                        "symbol": sym,
                        "ts": c.ts,
                        "decision_ts": c.ts + close_shift,
                        "setup": c.setup,
                        "direction": c.direction,
                        "entry": c.entry,
                        "stop": c.stop,
                        "target": c.target,
                        "label": out.label,
                        "outcome": out.reason,
                        "pnl_per_share": out.pnl_per_share,
                        "gross_r": out.pnl_per_share / risk,
                        "net_r": (out.pnl_per_share - fee) / risk,
                        **candidate_features(c, fr, int(i)),
                    }
                )
    df = pd.DataFrame(rows)
    return df.sort_values(["decision_ts", "symbol"]).reset_index(drop=True) if len(df) else df
