import json
from pathlib import Path

import pandas as pd

from bot.analytics.funnel import calibration_table, funnel, rejection_reasons
from bot.analytics.loaders import filter_dates, list_runs, load_run
from bot.backtest.metrics import compute_metrics


def _dec() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "final_status": [
                "filled",
                "rejected_risk_min_edge",
                "rejected_ml_prob",
                "rejected_jev_action",
                "filled",
            ],
            "gate_failed": [None, None, "ml_prob", "jev_action", None],
        }
    )


def test_funnel_counts() -> None:
    f = funnel(_dec()).set_index("stage")["count"]
    assert list(f) == [5, 4, 3, 2, 2]


def test_rejection_reasons() -> None:
    r = rejection_reasons(_dec())
    assert r["count"].sum() == 3


def test_calibration_table() -> None:
    c = calibration_table(pd.Series([0.1, 0.12, 0.9, 0.95]), pd.Series([0, 0, 1, 1]))
    assert c["win_rate"].tolist() == [0.0, 1.0]


def test_dashboard_metrics_match_report(tmp_path: Path) -> None:
    trades = pd.DataFrame(
        {
            "symbol": ["A", "A", "B"],
            "setup": ["orb"] * 3,
            "direction": ["long"] * 3,
            "qty": [1] * 3,
            "entry_ts": pd.to_datetime(
                ["2026-01-05 10:00", "2026-01-06 10:00", "2026-01-07 10:00"]
            ),
            "exit_ts": pd.to_datetime(["2026-01-05 10:30", "2026-01-06 10:20", "2026-01-07 11:00"]),
            "entry_price": [100.0] * 3,
            "exit_price": [102.0, 99.0, 103.0],
            "exit_reason": ["target", "stop", "target"],
            "gross_pnl": [2.0, -1.0, 3.0],
            "costs": [0.3, 0.3, 0.3],
            "net_pnl": [1.7, -1.3, 2.7],
            "decision_id": [0, 1, 2],
        }
    )
    run = tmp_path / "r1"
    run.mkdir()
    trades.to_parquet(run / "trades.parquet")
    m = compute_metrics(trades, 1000.0, 3)
    (run / "metrics.json").write_text(
        json.dumps({"metrics": m, "config": {}, "n_days": 3, "start_capital": 1000.0})
    )
    assert list_runs(tmp_path) == ["r1"]
    rd = load_run("r1", tmp_path)
    assert (
        compute_metrics(rd.trades, rd.start_capital, rd.n_days) == rd.metrics
    )  # dashboard == report
    cut = filter_dates(rd, pd.Timestamp("2026-01-06").date(), pd.Timestamp("2026-01-07").date())
    assert len(cut.trades) == 2
