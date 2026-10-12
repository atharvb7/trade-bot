import pandas as pd
import pytest

from bot.backtest.costs import CostModel
from bot.backtest.edge import candidate_r, edge_summary
from bot.config import CostsCfg


def test_candidate_r_zero_costs() -> None:
    dec = pd.DataFrame(
        {
            "final_status": [
                "filled",
                "rejected_risk_min_edge",
                "rejected_risk_outside_entry_window",
            ],
            "outcome": ["target", "stop", "target"],
            "direction": ["long", "short", "long"],
            "entry": [100.0, 100.0, 100.0],
            "stop": [99.0, 102.0, 99.0],
            "hyp_pnl_per_share": [1.5, -2.0, 1.5],
            "label": [1, 0, 1],
        }
    )
    free = CostModel(CostsCfg(**{k: 0.0 for k in CostsCfg.model_fields}))
    d = candidate_r(dec, free)
    assert len(d) == 2  # outside-window candidate is not tradeable
    assert d["gross_r"].tolist() == pytest.approx([1.5, -1.0])
    assert d["net_r"].tolist() == pytest.approx([1.5, -1.0])
    s = edge_summary(d, 1.5)
    assert s["win_rate"] == 50 and s["breakeven_win_rate"] == pytest.approx(40)
    assert s["mean_gross_r"] == pytest.approx(0.25)
