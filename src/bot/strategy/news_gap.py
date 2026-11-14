"""News gap fade: short a stock that gaps up after an out-of-hours order win or results.

Research: docs/experiments/2026-11-14-announcement-events.md (passed selection and
validation, not confirmed on the holdout). This module turns it into candidates for the
paper runner; it never sizes or places anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from bot.backtest.events import trade_day
from bot.config import NewsGapCfg
from bot.detectors.base import Candidate

LOOKBACK = 20


@dataclass(frozen=True)
class GapEvent:
    symbol: str
    kind: str  # "order" or "results"
    open: float
    prev_close: float

    @property
    def gap_pct(self) -> float:
        return (self.open / self.prev_close - 1) * 100


def live_universe(rows: pd.DataFrame, cfg: NewsGapCfg) -> list[str]:
    """Most traded stocks by median turnover over the last 20 sessions in ``rows``.

    ``rows`` must hold completed sessions only (bhavcopy rows before today).
    """
    days = sorted(rows["date"].unique())[-LOOKBACK:]
    recent = rows[rows["date"].isin(days)]
    stats = recent.groupby("symbol").agg(n=("turnover", "size"), med=("turnover", "median"))
    last = recent[recent["date"] == days[-1]].set_index("symbol")["close"]
    ok = stats[(stats["n"] == len(days)) & (len(days) == LOOKBACK)].join(last, how="inner")
    ok = ok[ok["close"] >= cfg.min_price]
    return sorted(ok.sort_values("med", ascending=False).head(cfg.universe_size).index)


def events_for(today: date, ann: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict[str, str]:
    """symbol -> kind for announcements that trade today (made since the last close)."""
    days = sessions.union(pd.DatetimeIndex([pd.Timestamp(today)]))
    hit = ann[trade_day(ann["ts"], days) == pd.Timestamp(today)]
    out: dict[str, str] = {}
    for symbol, kind in zip(hit["symbol"], hit["kind"], strict=True):
        if out.get(symbol) != "order":  # an order win outranks results
            out[symbol] = kind
    return out


def gap_events(
    events: dict[str, str], quotes: dict[str, tuple[float, float]], cfg: NewsGapCfg
) -> list[GapEvent]:
    """Events whose open is at least ``min_gap_pct`` above the previous close, largest first."""
    out = []
    for symbol, kind in events.items():
        opn, prev = quotes.get(symbol, (0.0, 0.0))
        if opn > 0 and prev > 0:
            ev = GapEvent(symbol, kind, opn, prev)
            if ev.gap_pct >= cfg.min_gap_pct:
                out.append(ev)
    return sorted(out, key=lambda e: (-e.gap_pct, e.symbol))


def make_candidate(ev: GapEvent, bars: pd.DataFrame, cfg: NewsGapCfg) -> Candidate:
    """Short candidate from today's closed 1m bars so far (the last one is the signal bar)."""
    entry = float(bars["close"].iloc[-1])
    stop = max(float(bars["high"].max()), entry * (1 + cfg.stop_floor_pct / 100))
    return Candidate(
        symbol=ev.symbol,
        setup=f"news_gap_{ev.kind}",
        direction="short",
        ts=bars.index[-1],
        entry=entry,
        stop=stop,
        target=ev.prev_close,  # a full gap fill; most trades exit at square-off
        atr=stop - entry,
        features={"gap_pct": round(ev.gap_pct, 3), "open": ev.open, "prev_close": ev.prev_close},
    )
