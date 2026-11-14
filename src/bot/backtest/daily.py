"""Daily cross-sectional research on NSE bhavcopy files (open-to-close trades).

Signals for day t use rows of days <= t-1 only; the trade is OPEN(t) -> CLOSE(t).
See docs/experiments/2026-11-14-daily-signals.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from bot.backtest.costs import CostModel

COLS = {
    "SYMBOL": "symbol",
    "SERIES": "series",
    "DATE1": "date",
    "PREV_CLOSE": "prev_close",
    "OPEN_PRICE": "open",
    "CLOSE_PRICE": "close",
    "TURNOVER_LACS": "turnover",
}
LOOKBACK = 20
UNIVERSE_SIZE = 200
MIN_PRICE = 20.0
MAX_GAP = 0.20


@dataclass(frozen=True)
class Variant:
    id: str
    signal: str
    pick: Literal["high", "low"]
    side: Literal["long", "short"]


VARIANTS = [
    Variant("D1", "intraday20", "high", "long"),
    Variant("D2", "intraday20", "low", "short"),
    Variant("D3", "overnight20", "low", "long"),
    Variant("D4", "overnight20", "high", "short"),
    Variant("D5", "ret1", "low", "long"),
    Variant("D6", "ret1", "high", "short"),
    Variant("D7", "shock_up", "high", "long"),
    Variant("D8", "shock_down", "low", "short"),
]


def load_bhavcopy(folder: Path, last_day: date | None = None) -> pd.DataFrame:
    """Long frame of EQ rows. Files dated after ``last_day`` are never opened.

    The archive serves the previous session's file again on holidays, so the date comes from
    the DATE1 column and repeated (date, symbol) rows are dropped.
    """
    frames = []
    for path in sorted(folder.glob("*.csv")):
        day = pd.Timestamp(path.stem)
        if last_day is not None and day.date() > last_day:
            continue
        raw = pd.read_csv(path, skipinitialspace=True, usecols=list(COLS), na_values=["-"])
        raw = raw.rename(columns=COLS)
        raw = raw[raw["series"] == "EQ"].drop(columns="series")
        raw["date"] = pd.to_datetime(raw["date"], format="%d-%b-%Y")
        frames.append(raw)
    out = pd.concat(frames, ignore_index=True)
    num = ["prev_close", "open", "close", "turnover"]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce")
    return out.dropna(subset=num).drop_duplicates(["date", "symbol"])


def build_signals(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Wide (date x symbol) frames. Every signal at row t depends on rows <= t-1 only."""
    wide = {
        c: rows.pivot(index="date", columns="symbol", values=c)
        for c in ("open", "close", "prev_close", "turnover")
    }
    opn, close, prev, turn = wide["open"], wide["close"], wide["prev_close"], wide["turnover"]
    intraday = close / opn - 1
    overnight = opn / prev - 1
    ret = close / prev - 1
    med_turn = turn.rolling(LOOKBACK, min_periods=LOOKBACK).median()
    shock = turn >= 3 * med_turn.shift(1)  # day vs the 20 days before it
    liquid_rank = med_turn.shift(1).rank(axis=1, ascending=False, method="first")
    universe = (liquid_rank <= UNIVERSE_SIZE) & (prev >= MIN_PRICE) & (overnight.abs() <= MAX_GAP)
    return {
        "intraday": intraday,
        "universe": universe,
        "intraday20": intraday.rolling(LOOKBACK, min_periods=LOOKBACK).sum().shift(1),
        "overnight20": overnight.rolling(LOOKBACK, min_periods=LOOKBACK).sum().shift(1),
        "ret1": ret.shift(1),
        "shock_up": ret.where(shock & (ret >= 0.03)).shift(1),
        "shock_down": ret.where(shock & (ret <= -0.03)).shift(1),
        # The two gap signals use day t's own opening price (see the opening-auction write-up).
        "open": opn,
        "gap_up": overnight.where(overnight >= 0.01),
        "gap_down": overnight.where(overnight <= -0.01),
    }


OPEN_VARIANTS = [
    Variant("O1", "overnight20", "high", "short"),
    Variant("O2", "shock_down", "low", "short"),
    Variant("O3", "gap_up", "high", "short"),
    Variant("O4", "gap_down", "low", "long"),
]


def open_exit_prices(folder: Path, exit_time: time) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide (date x symbol) frames: open of the 09:15 bar and open of the ``exit_time`` bar."""
    first: dict[str, pd.Series] = {}
    exits: dict[str, pd.Series] = {}
    for path in sorted(folder.glob("*.parquet")):
        bars = pd.read_parquet(path, columns=["open"])["open"]
        for store, at in ((first, time(9, 15)), (exits, exit_time)):
            px = bars[pd.DatetimeIndex(bars.index).time == at]
            store[path.stem] = px.set_axis(px.index.normalize())
    return pd.DataFrame(first), pd.DataFrame(exits)


def with_open_exit(
    sig: dict[str, pd.DataFrame], first: pd.DataFrame, exits: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Copy of ``sig`` whose trade return is official OPEN -> exit price.

    Stock-days whose first 1m bar disagrees with the official open by more than 0.1% are blank.
    """
    opn = sig["open"]
    first, exits = first.reindex_like(opn), exits.reindex_like(opn)
    ok = (first / opn - 1).abs() <= 0.001
    return {**sig, "intraday": (exits / opn - 1).where(ok)}


def _long(wide: pd.DataFrame, name: str) -> pd.DataFrame:
    return wide.reset_index().melt(id_vars="date", var_name="symbol", value_name=name)


def net_return(intraday: pd.Series, side: str, costs: CostModel) -> pd.Series:
    """Net return per rupee of entry value, after slippage and fees on both legs."""
    slip = costs.cfg.slippage_pct / 100
    buy_fee, sell_fee = costs.leg_fees("buy", 1.0), costs.leg_fees("sell", 1.0)
    ratio = 1 + intraday  # close / open
    if side == "long":
        buy, sell = ratio * 0 + (1 + slip), ratio * (1 - slip)
    else:
        buy, sell = ratio * (1 + slip), ratio * 0 + (1 - slip)
    return sell - buy - buy * buy_fee - sell * sell_fee


def candidates(
    sig: dict[str, pd.DataFrame], variant: Variant, costs: CostModel, top: int = 20
) -> pd.DataFrame:
    """The ``top`` most extreme universe stocks per day, with rank (1 = most extreme)."""
    s = _long(sig[variant.signal].where(sig["universe"]), "signal").dropna(subset=["signal"])
    s = s.sort_values(["date", "signal", "symbol"], ascending=[True, variant.pick == "low", True])
    s["rank"] = s.groupby("date").cumcount() + 1
    s = s[s["rank"] <= top]
    s = s.merge(_long(sig["intraday"], "gross"), on=["date", "symbol"]).dropna(subset=["gross"])
    s["net"] = net_return(s["gross"], variant.side, costs)
    if variant.side == "short":
        s["gross"] = -s["gross"]
    return s.reset_index(drop=True)


def summarize(cands: pd.DataFrame, n: int = 2000, seed: int = 0) -> dict[str, float]:
    """Mean gross/net return per candidate (%) with a day-block bootstrap 90% interval."""
    if cands.empty:
        return {"n": 0.0}
    g = cands.groupby("date")["net"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(g), size=(n, len(g)))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1) * 100
    return {
        "n": float(len(cands)),
        "days": float(len(g)),
        "gross_pct": float(cands["gross"].mean() * 100),
        "net_pct": float(cands["net"].mean() * 100),
        "lo": float(np.percentile(means, 5)),
        "hi": float(np.percentile(means, 95)),
        "win_pct": float((cands["net"] > 0).mean() * 100),
    }
