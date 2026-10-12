import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import run_page

from bot.analytics.loaders import RunData
from bot.data.store import read_1m
from bot.features.indicators import ema, session_vwap


def _bars(rd: RunData, symbol: str) -> pd.DataFrame | None:
    if rd.bars is not None:
        b = rd.bars[rd.bars["symbol"] == symbol]
        return b if len(b) else None
    try:
        b = read_1m(symbol)
    except FileNotFoundError:
        return None
    b["vwap"] = session_vwap(b)
    return b


def render(rd: RunData, mode: str) -> None:
    st.title(f"Trades · {mode}")
    t = rd.trades
    if t.empty:
        st.info("No trades in this range.")
        return
    f1, f2, f3 = st.columns(3)
    sym = f1.multiselect("Symbol", sorted(t["symbol"].unique()))
    setup = f2.multiselect("Setup", sorted(t["setup"].unique()))
    res = f3.selectbox("Result", ["all", "winners", "losers"])
    v = t
    if sym:
        v = v[v["symbol"].isin(sym)]
    if setup:
        v = v[v["setup"].isin(setup)]
    if res != "all":
        v = v[v["net_pnl"] > 0] if res == "winners" else v[v["net_pnl"] <= 0]
    v = v.sort_values("entry_ts", ascending=False).reset_index(drop=True)
    show = v.drop(columns=["decision_id"]).round(3)
    event = st.dataframe(
        show, on_select="rerun", selection_mode="single-row", use_container_width=True
    )
    rows = event.selection.rows if event else []
    if not rows:
        st.caption("Select a row to see the chart and its full decision record.")
        return
    tr = v.iloc[rows[0]]
    day = pd.Timestamp(tr["entry_ts"]).normalize()
    b = _bars(rd, tr["symbol"])
    dec = (
        rd.decisions[rd.decisions["decision_id"] == tr["decision_id"]]
        if len(rd.decisions)
        else pd.DataFrame()
    )
    if b is not None:
        full = b.copy()
        for n in (9, 21, 50):
            full[f"ema{n}"] = ema(full["close"], n)
        d = full[(full.index >= day) & (full.index < day + pd.Timedelta(days=1))]
        fig = go.Figure(
            go.Candlestick(
                x=d.index,
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"],
                name="price",
            )
        )
        fig.add_scatter(x=d.index, y=d["vwap"], name="VWAP", line=dict(width=1))
        for n in (9, 21, 50):
            fig.add_scatter(x=d.index, y=d[f"ema{n}"], name=f"EMA{n}", line=dict(width=1))
        fig.add_scatter(
            x=[tr["entry_ts"]],
            y=[tr["entry_price"]],
            mode="markers",
            name="entry",
            marker=dict(size=12, symbol="triangle-up"),
        )
        fig.add_scatter(
            x=[tr["exit_ts"]],
            y=[tr["exit_price"]],
            mode="markers",
            name=f"exit ({tr['exit_reason']})",
            marker=dict(size=12, symbol="x"),
        )
        if len(dec):
            fig.add_hline(y=float(dec.iloc[0]["stop"]), line_dash="dot", annotation_text="stop")
            fig.add_hline(y=float(dec.iloc[0]["target"]), line_dash="dot", annotation_text="target")
        fig.update_layout(xaxis_rangeslider_visible=False, height=560)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No candle data available for this symbol.")
    st.subheader("Decision record")
    if len(dec):
        st.json(
            {k: (None if pd.isna(x) else x) for k, x in dec.iloc[0].astype(object).items()},
            expanded=True,
        )
    st.subheader("Costs")
    st.write(
        {
            "gross_pnl": round(tr["gross_pnl"], 3),
            "costs": round(tr["costs"], 3),
            "net_pnl": round(tr["net_pnl"], 3),
        }
    )


run_page(render)
