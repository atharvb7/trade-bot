"""Export saved backtest runs to frontend/data/runs.js for the static website.

Reads every run in data/backtests/<run_id>/ (written by scripts/run_backtest.py) and writes one
JavaScript file that the dashboard page loads. Numbers come straight from the run files and the
same metric/funnel/edge functions the Streamlit dashboard uses; nothing is invented or rounded
beyond display precision.

Usage: python scripts/export_frontend_data.py [--runs RUN_ID ...] [--max-trades 400]
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from bot.analytics.funnel import funnel, rejection_reasons
from bot.analytics.loaders import list_runs, load_run
from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r, edge_summary
from bot.backtest.metrics import breakdowns
from bot.config import ROOT, CostsCfg

OUT = ROOT / "frontend" / "data" / "runs.js"
REJECTED_SAMPLE = 250


def clean(x: Any) -> Any:
    """JSON-safe values: NaN/inf -> None, numpy/pandas scalars -> Python, timestamps -> ISO."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, pd.Timestamp | datetime):
        return pd.Timestamp(x).strftime("%Y-%m-%dT%H:%M:%S")
    if hasattr(x, "item") and not isinstance(x, str):
        x = x.item()
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return round(x, 6)
    return x


def records(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    cols = [c for c in cols if c in df.columns]
    return [clean(r) for r in df[cols].to_dict("records")]


def created_at(run_id: str) -> str | None:
    try:
        return datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def export_run(run_id: str, max_trades: int) -> dict[str, Any]:
    rd = load_run(run_id)
    meta = json.loads((ROOT / "data" / "backtests" / run_id / "metrics.json").read_text())
    cfg = rd.config
    risk = cfg.get("risk", {})
    trades = rd.trades.sort_values("entry_ts") if len(rd.trades) else rd.trades
    dec = rd.decisions

    status = dec["final_status"].value_counts().to_dict() if len(dec) else {}
    fun = funnel(dec) if len(dec) else pd.DataFrame({"stage": [], "count": []})
    reasons = rejection_reasons(dec) if len(dec) else pd.DataFrame({"reason": [], "count": []})

    edge: dict[str, Any] = {"overall": {"candidates": 0}, "by_setup": {}}
    if len(dec) and "costs" in cfg:
        cm = CostModel(CostsCfg(**cfg["costs"]))
        rr = float(cfg.get("detectors", {}).get("reward_risk", 1.5))
        er = candidate_r(dec, cm)
        edge = {
            "overall": edge_summary(er, rr),
            "by_setup": {s: edge_summary(g, rr) for s, g in er.groupby("setup")} if len(er) else {},
        }

    br = {
        k: [{"key": clean(i), **clean(r)} for i, r in df.to_dict("index").items()]
        for k, df in breakdowns(trades).items()
    }

    eq_daily: list[dict[str, Any]] = []
    if len(rd.equity):
        e = rd.equity.copy()
        e["ts"] = pd.to_datetime(e["ts"])
        last = e.groupby(e["ts"].dt.normalize())["equity"].last()
        eq_daily = [{"date": d.strftime("%Y-%m-%d"), "equity": clean(v)} for d, v in last.items()]

    shown = trades.tail(max_trades) if len(trades) else trades
    bars_by_key: dict[str, list[list[Any]]] = {}
    if rd.bars is not None and len(shown):
        b = rd.bars.copy()
        b.index = pd.to_datetime(b.index)
        for sym, day in {
            (s, pd.Timestamp(t).normalize())
            for s, t in zip(shown["symbol"], shown["entry_ts"], strict=True)
        }:
            part = b[
                (b["symbol"] == sym) & (b.index >= day) & (b.index < day + pd.Timedelta(days=1))
            ]
            key = f"{sym}|{day.strftime('%Y-%m-%d')}"
            bars_by_key[key] = [
                [
                    ts.strftime("%H:%M"),
                    *[
                        clean(float(r[c]))
                        for c in ("open", "high", "low", "close", "vwap", "ema_21")
                    ],
                ]
                for ts, r in part.iterrows()
            ]

    rej = dec[dec["final_status"].astype(str).str.startswith("rejected")] if len(dec) else dec
    rej = rej.sort_values("ts").tail(REJECTED_SAMPLE) if len(rej) else rej
    stop_target = (
        dec.set_index("decision_id")[["stop", "target"]].to_dict("index") if len(dec) else {}
    )
    trade_rows = records(
        shown,
        [
            "decision_id",
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
        ],
    )
    for t in trade_rows:
        st = stop_target.get(t["decision_id"], {})
        t["stop"], t["target"] = clean(st.get("stop")), clean(st.get("target"))

    synthetic = bool(meta.get("synthetic", False))
    min_edge = risk.get("min_edge_cost_multiple")
    label = (
        f"{meta.get('bar_minutes', 1)}m bars, {cfg.get('decision_mode', meta.get('mode', ''))}, "
        f"min-edge {min_edge}x" + (", synthetic data" if synthetic else ", market data")
    )
    return clean(
        {
            "id": run_id,
            "label": label,
            "created_at": created_at(run_id),
            "synthetic": synthetic,
            "bar_minutes": meta.get("bar_minutes", 1),
            "mode": cfg.get("decision_mode", meta.get("mode")),
            "n_days": rd.n_days,
            "start_capital": rd.start_capital,
            "config": cfg,
            "metrics": rd.metrics,
            "candidates": int(len(dec)),
            "status_counts": status,
            "funnel": fun.to_dict("records"),
            "rejection_reasons": reasons.to_dict("records"),
            "edge": edge,
            "breakdowns": br,
            "equity_daily": eq_daily,
            "trades_total": int(len(trades)),
            "trades": trade_rows,
            "bars": bars_by_key,
            "rejected_sample": records(
                rej,
                [
                    "ts",
                    "symbol",
                    "setup",
                    "direction",
                    "entry",
                    "stop",
                    "target",
                    "final_status",
                    "outcome",
                    "label",
                    "hyp_pnl_per_share",
                ],
            ),
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", help="run ids (default: all saved runs)")
    ap.add_argument("--max-trades", type=int, default=400, help="latest N trades kept per run")
    args = ap.parse_args()
    run_ids = args.runs or list_runs()
    if not run_ids:
        raise SystemExit("No runs in data/backtests/. Run scripts/run_backtest.py first.")
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs": [export_run(r, args.max_trades) for r in run_ids],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    OUT.write_text(f"window.TRADEBOT_DATA = {body};\n")
    print(
        f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB, {len(run_ids)} runs)"
    )


if __name__ == "__main__":
    main()
