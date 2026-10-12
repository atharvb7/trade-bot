import pandas as pd
import plotly.express as px
import streamlit as st
from common import run_page

from bot.analytics.loaders import RunData
from bot.backtest.metrics import breakdowns, compute_metrics


def render(rd: RunData, mode: str) -> None:
    st.title(f"Performance · {mode}")
    t = rd.trades
    if t.empty:
        st.info("No trades in this range.")
        return
    m = compute_metrics(t, rd.start_capital, rd.n_days)  # same function as the backtest report
    keys = [
        "trades",
        "win_rate",
        "avg_win",
        "avg_loss",
        "expectancy",
        "profit_factor",
        "max_drawdown_pct",
        "sharpe",
        "exposure_pct",
        "cost_pct_of_gross_profit",
        "gross_pnl",
        "total_costs",
        "net_pnl",
        "final_equity",
    ]
    cols = st.columns(4)
    for i, k in enumerate(keys):
        cols[i % 4].metric(k.replace("_", " "), f"{m[k]:,.2f}")
    s = t.sort_values("exit_ts")
    eq = pd.DataFrame({"ts": s["exit_ts"], "equity": rd.start_capital + s["net_pnl"].cumsum()})
    st.plotly_chart(
        px.line(eq, x="ts", y="equity", title="Equity curve (net of costs)"),
        use_container_width=True,
    )
    dd = (eq["equity"].cummax() - eq["equity"]) / eq["equity"].cummax() * 100
    st.plotly_chart(
        px.area(x=eq["ts"], y=-dd, labels={"x": "ts", "y": "drawdown %"}, title="Drawdown %"),
        use_container_width=True,
    )
    for key, df in breakdowns(t).items():
        st.plotly_chart(
            px.bar(df.reset_index(), x=key, y="net_pnl", title=f"Net P&L by {key}"),
            use_container_width=True,
        )
    wd = (
        t.assign(weekday=pd.to_datetime(t["entry_ts"]).dt.day_name())
        .groupby("weekday")["net_pnl"]
        .sum()
        .reset_index()
    )
    st.plotly_chart(
        px.bar(wd, x="weekday", y="net_pnl", title="Net P&L by weekday"), use_container_width=True
    )
    cost = pd.DataFrame(
        {
            "component": ["gross P&L", "costs", "net P&L"],
            "₹": [m["gross_pnl"], -m["total_costs"], m["net_pnl"]],
        }
    )
    st.plotly_chart(
        px.bar(cost, x="component", y="₹", title="Cost breakdown"), use_container_width=True
    )


run_page(render)
