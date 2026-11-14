"""Announcement events for the daily open-to-close research.

See docs/experiments/2026-11-14-announcement-events.md. An announcement is attached to the
first session whose 09:00 comes after it, and only if it was made outside market hours.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ORDER_CATEGORY = re.compile(r"order|contract", re.I)
ORDER_TEXT = re.compile(
    r"bagging|receipt of (an? )?(order|contract|letter of)|letter of (award|acceptance|intent)|"
    r"(awarded|secured|received|bags|bagged|wins|won)\b.{0,40}\b(order|contract)|order win",
    re.I,
)
RESULT_TEXT = re.compile(r"financial result", re.I)


def classify(category: str, text: str) -> str | None:
    """'order', 'results' or None, by the pre-registered text rules."""
    if ORDER_CATEGORY.search(category) or ORDER_TEXT.search(text):
        return "order"
    if category == "Financial Result Updates":
        return "results"
    if category == "Outcome of Board Meeting" and RESULT_TEXT.search(text):
        return "results"
    return None


def load_announcements(folder: Path, last_month: str | None = None) -> pd.DataFrame:
    """Rows (symbol, ts, kind) for classified announcements; months after ``last_month`` skipped."""
    out: list[tuple[str, str, str]] = []
    for path in sorted(folder.glob("*.json")):
        if last_month is not None and path.stem > last_month:
            continue
        for item in json.loads(path.read_text()):
            kind = classify(item.get("desc") or "", item.get("attchmntText") or "")
            if kind and item.get("symbol") and item.get("sort_date"):
                out.append((item["symbol"], item["sort_date"], kind))
    df = pd.DataFrame(out, columns=["symbol", "ts", "kind"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def trade_day(ts: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """Session an out-of-hours announcement trades on (NaT if made 09:00-15:30 of a session)."""
    days = sessions.sort_values()
    pos = np.searchsorted(days.to_numpy(), ts.dt.normalize().to_numpy(), side="left")
    same_day = (pos < len(days)) & (
        days.to_numpy()[np.minimum(pos, len(days) - 1)] == ts.dt.normalize()
    )
    minutes = ts.dt.hour * 60 + ts.dt.minute
    in_hours = same_day & (minutes >= 9 * 60) & (minutes <= 15 * 60 + 30)
    after_close = same_day & (minutes > 15 * 60 + 30)
    idx = pos + after_close.to_numpy().astype(int)
    result = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    ok = (~in_hours.to_numpy()) & (idx < len(days))
    result[ok] = days.to_numpy()[idx[ok]]
    return result


def event_flags(ann: pd.DataFrame, like: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Boolean (date x symbol) frames shaped like ``like``, one per kind."""
    ann = ann.assign(date=trade_day(ann["ts"], pd.DatetimeIndex(like.index))).dropna(
        subset=["date"]
    )
    flags = {}
    for kind, grp in ann.groupby("kind"):
        hit = grp.drop_duplicates(["date", "symbol"]).assign(v=True)
        wide = hit.pivot(index="date", columns="symbol", values="v")
        flags[str(kind)] = wide.reindex(index=like.index, columns=like.columns).eq(True)
    return flags
