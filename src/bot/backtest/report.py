"""Persist a backtest run so the dashboard and later comparisons can load it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from bot.backtest.engine import BacktestResult
from bot.backtest.metrics import compute_metrics
from bot.config import ROOT
from bot.detectors.base import Frame

BACKTEST_DIR = ROOT / "data" / "backtests"
CHART_COLS = ("open", "high", "low", "close", "volume", "vwap", "ema_21")


def save_run(
    res: BacktestResult,
    frames: dict[str, Frame],
    run_id: str,
    extra: dict[str, Any] | None = None,
    base: Path = BACKTEST_DIR,
) -> tuple[Path, dict[str, float]]:
    m = compute_metrics(res.trades, res.start_capital, res.n_days)
    out = base / run_id
    out.mkdir(parents=True, exist_ok=True)
    res.trades.to_parquet(out / "trades.parquet")
    res.decisions.to_parquet(out / "decisions.parquet")
    res.equity.to_parquet(out / "equity.parquet")
    bars = []
    for sym, fr in frames.items():
        b = pd.DataFrame({k: fr[k] for k in CHART_COLS}, index=fr.index)
        b["symbol"] = sym
        bars.append(b)
    if bars:
        pd.concat(bars).to_parquet(out / "bars.parquet")
    meta = {
        "metrics": m,
        "config": res.config,
        "n_days": res.n_days,
        "start_capital": res.start_capital,
        **(extra or {}),
    }
    (out / "metrics.json").write_text(json.dumps(meta, indent=1, default=str))
    return out, m
