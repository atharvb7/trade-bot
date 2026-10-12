"""Shared dashboard plumbing: sidebar (mode, run, date range), data loading, live refresh."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import streamlit as st

from bot.analytics.loaders import RunData, filter_dates, list_runs, load_db, load_run
from bot.config import ROOT, load_config

KILL_FLAG = ROOT / load_config().app.kill_switch_file


@st.cache_data(ttl=5)
def _run(run_id: str) -> RunData:
    return load_run(run_id)


def _db(mode: str) -> RunData:
    cfg = load_config()
    url = cfg.app.database_url
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{ROOT / url.removeprefix('sqlite:///')}"
    return load_db(mode, url, cfg.app.starting_capital)


def empty(rd: RunData) -> bool:
    return rd.trades.empty and rd.decisions.empty and rd.equity.empty


def run_page(render: Callable[[RunData, str], None]) -> None:
    """Sidebar controls + render. Live modes auto-refresh every 5 seconds."""
    st.sidebar.header("Data")
    mode = st.sidebar.selectbox("Mode", ["backtest", "paper", "live"])
    if mode == "backtest":
        runs = list_runs()
        if not runs:
            st.warning("No backtest runs yet. Run `python scripts/run_backtest.py --synthetic`.")
            return
        rd = _run(st.sidebar.selectbox("Backtest run", runs))
    else:
        rd = _db(mode)
    ts = (
        pd.to_datetime(rd.trades["exit_ts"])
        if len(rd.trades)
        else pd.Series(dtype="datetime64[ns]")
    )
    lo = ts.min().date() if len(ts) else date.today()
    hi = ts.max().date() if len(ts) else date.today()
    picked = st.sidebar.date_input("Date range", (lo, hi))
    if isinstance(picked, tuple) and len(picked) == 2:
        rd = filter_dates(rd, picked[0], picked[1])
    if mode == "backtest":
        render(rd, mode)
    else:
        st.sidebar.caption("Auto-refresh: every 5 s")
        st.fragment(run_every=5)(lambda: render(_db(mode), mode))()
