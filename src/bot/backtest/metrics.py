"""Backtest metrics, all on net (after-cost) P&L."""

from __future__ import annotations

import numpy as np
import pandas as pd

SESSION_MINUTES = 375


def _pf(pnl: pd.Series) -> float:
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf") if gains > 0 else 0.0


def compute_metrics(trades: pd.DataFrame, start_capital: float, n_days: int) -> dict[str, float]:
    if trades.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "net_pnl": 0.0,
            "max_drawdown_pct": 0.0,
        }
    net = trades["net_pnl"]
    wins, losses = net[net > 0], net[net < 0]
    t = trades.sort_values("exit_ts")
    equity = start_capital + t["net_pnl"].cumsum()
    peak = np.maximum.accumulate(np.concatenate([[start_capital], equity.to_numpy()]))[1:]
    dd = float(((peak - equity) / peak).max() * 100)
    days = pd.to_datetime(t["exit_ts"]).dt.normalize()
    daily = t.groupby(days)["net_pnl"].sum()
    all_days = max(n_days, len(daily))
    padded = np.concatenate([daily.to_numpy(), np.zeros(all_days - len(daily))])
    sharpe = (
        float(padded.mean() / padded.std(ddof=1) * np.sqrt(252))
        if all_days > 1 and padded.std(ddof=1) > 0
        else 0.0
    )
    held = (
        pd.to_datetime(trades["exit_ts"]) - pd.to_datetime(trades["entry_ts"])
    ).dt.total_seconds() / 60
    gross_profit = trades.loc[trades["gross_pnl"] > 0, "gross_pnl"].sum()
    return {
        "trades": int(len(trades)),
        "win_rate": float((net > 0).mean() * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "expectancy": float(net.mean()),
        "profit_factor": _pf(net),
        "max_drawdown_pct": dd,
        "sharpe": sharpe,
        "exposure_pct": float(held.sum() / (max(n_days, 1) * SESSION_MINUTES) * 100),
        "cost_pct_of_gross_profit": float(trades["costs"].sum() / gross_profit * 100)
        if gross_profit > 0
        else float("nan"),
        "gross_pnl": float(trades["gross_pnl"].sum()),
        "total_costs": float(trades["costs"].sum()),
        "net_pnl": float(net.sum()),
        "final_equity": float(start_capital + net.sum()),
    }


def breakdowns(trades: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if trades.empty:
        return {}
    t = trades.copy()
    t["hour"] = pd.to_datetime(t["entry_ts"]).dt.hour
    out = {}
    for key in ("setup", "symbol", "hour"):
        g = t.groupby(key)["net_pnl"]
        out[key] = pd.DataFrame(
            {
                "trades": g.size(),
                "win_rate": g.apply(lambda s: (s > 0).mean() * 100),
                "net_pnl": g.sum(),
                "expectancy": g.mean(),
            }
        )
    return out
