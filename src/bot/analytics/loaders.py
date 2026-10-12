"""Load backtest runs and paper/live DB data into one common shape for the dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from bot.config import ROOT

BACKTEST_DIR = ROOT / "data" / "backtests"
TRADE_COLS = [
    "symbol",
    "setup",
    "direction",
    "qty",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "exit_reason",
    "gross_pnl",
    "costs",
    "net_pnl",
    "decision_id",
]


@dataclass
class RunData:
    name: str
    trades: pd.DataFrame
    decisions: pd.DataFrame
    equity: pd.DataFrame
    start_capital: float
    n_days: int
    metrics: dict[str, Any] = field(default_factory=dict)  # as written by the backtest report
    config: dict[str, Any] = field(default_factory=dict)
    bars: pd.DataFrame | None = None
    folds: pd.DataFrame | None = None


def list_runs(base: Path = BACKTEST_DIR) -> list[str]:
    if not base.exists():
        return []
    return sorted((p.name for p in base.iterdir() if (p / "metrics.json").exists()), reverse=True)


def _read(p: Path) -> pd.DataFrame | None:
    return pd.read_parquet(p) if p.exists() else None


def load_run(run_id: str, base: Path = BACKTEST_DIR) -> RunData:
    d = base / run_id
    meta = json.loads((d / "metrics.json").read_text())
    trades = _read(d / "trades.parquet")
    dec = _read(d / "decisions.parquet")
    eq = _read(d / "equity.parquet")
    return RunData(
        name=run_id,
        trades=trades if trades is not None else pd.DataFrame(columns=TRADE_COLS),
        decisions=dec if dec is not None else pd.DataFrame(),
        equity=eq if eq is not None else pd.DataFrame(columns=["ts", "equity"]),
        start_capital=float(meta.get("start_capital", meta["config"].get("start_capital", 1000))),
        n_days=int(meta.get("n_days", 0)),
        metrics=meta["metrics"],
        config=meta.get("config", {}),
        bars=_read(d / "bars.parquet"),
        folds=_read(d / "folds.parquet"),
    )


def load_db(mode: str, url: str, start_capital: float) -> RunData:
    """Paper/live data from the SQLite database (same shape as a backtest run)."""
    from sqlalchemy import create_engine

    eng = create_engine(url)
    try:
        trades = pd.read_sql("select * from trades where mode = :m", eng, params={"m": mode})
        dec = pd.read_sql("select * from decision_records where mode = :m", eng, params={"m": mode})
        eq = pd.read_sql("select * from equity_snapshots where mode = :m", eng, params={"m": mode})
    except Exception:  # tables not created yet
        trades, dec, eq = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    if not dec.empty:
        dec = dec.rename(columns={"id": "decision_id", "rejection_reason": "risk_reason"})
        dec["gate_failed"] = None
    if not trades.empty:
        for c in ("entry_ts", "exit_ts"):
            trades[c] = pd.to_datetime(trades[c])
        setup = dec.set_index("decision_id")["setup"] if not dec.empty else pd.Series(dtype=str)
        trades["setup"] = trades["decision_id"].map(setup).fillna("unknown")
        trades = trades.dropna(subset=["exit_ts"])
    else:
        trades = pd.DataFrame(columns=TRADE_COLS)
    days = pd.to_datetime(trades["exit_ts"]).dt.normalize().nunique() if len(trades) else 0
    return RunData(
        mode,
        trades,
        dec,
        eq if not eq.empty else pd.DataFrame(columns=["ts", "equity"]),
        start_capital,
        int(days),
    )


def filter_dates(rd: RunData, start: date | None, end: date | None) -> RunData:
    def sel(df: pd.DataFrame, col: str) -> pd.DataFrame:
        if df.empty or col not in df.columns:
            return df
        ts = pd.to_datetime(df[col])
        m = pd.Series(True, index=df.index)
        if start:
            m &= ts.dt.date >= start
        if end:
            m &= ts.dt.date <= end
        return df[m]

    trades = sel(rd.trades, "exit_ts")
    n_days = pd.to_datetime(trades["exit_ts"]).dt.normalize().nunique() if len(trades) else 0
    return RunData(
        rd.name,
        trades,
        sel(rd.decisions, "ts"),
        sel(rd.equity, "ts"),
        rd.start_capital,
        max(int(n_days), 0) if (start or end) else rd.n_days,
        rd.metrics,
        rd.config,
        rd.bars,
        rd.folds,
    )
