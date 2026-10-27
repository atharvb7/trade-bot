"""As-of cross-sectional panel for detectors that compare symbols (relative strength).

The Detector protocol sees one symbol's Frame. Cross-sectional setups also need every other
symbol's (and the index's) state at the same moment, so they are built with a CrossSection:
for each name, the return since today's 09:15 open, on CLOSED bars, in percent.

No look-ahead: ``at(ts)`` returns, for each name, the value of its latest bar that opened at
or before ``ts`` on the same day. All those bars have closed by ``ts + bar``, which is the
decision time of the signal bar opening at ``ts``. Live use: build the panel only after every
symbol's bar for ``ts`` has closed (or treat a late bar as missing, which falls back to the
previous closed bar).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.data.sessions import SESSION_OPEN
from bot.detectors.base import Frame


def return_since_open(fr: Frame) -> pd.Series:
    """close / open of today's 09:15 bar - 1, in percent; NaN on days whose 09:15 bar is missing."""
    idx = fr.index
    day = idx.normalize()
    first_open = pd.Series(fr["open"], index=idx).groupby(day).transform("first")
    first_ts = pd.Series(idx, index=idx).groupby(day).transform("first")
    valid = pd.DatetimeIndex(first_ts).time == SESSION_OPEN
    r = (pd.Series(fr["close"], index=idx) / first_open - 1) * 100
    return r.where(valid)


class CrossSection:
    """Return since open (%) for every symbol and the index, aligned as-of on bar open time."""

    def __init__(self, panel: pd.DataFrame, index_name: str) -> None:
        self.panel = panel.sort_index()
        self.index_name = index_name
        self._ts = pd.DatetimeIndex(self.panel.index)
        self._vals = self.panel.to_numpy(dtype=float)
        self._names = list(self.panel.columns)

    @classmethod
    def from_frames(
        cls, frames: dict[str, Frame], index: Frame | None = None, index_name: str = "NIFTY_50"
    ) -> CrossSection:
        series = {s: return_since_open(fr) for s, fr in frames.items()}
        if index is not None:
            series[index_name] = return_since_open(index)
        panel = pd.DataFrame(series).sort_index()
        # carry a name's last closed value forward within the same day only
        panel = panel.groupby(pd.DatetimeIndex(panel.index).normalize()).ffill()
        return cls(panel, index_name)

    def at(self, ts: pd.Timestamp) -> dict[str, float]:
        """Finite values as of the bar opening at ``ts`` (latest bar opened <= ts, same day)."""
        k = int(self._ts.searchsorted(ts, side="right")) - 1
        if k < 0 or self._ts[k].normalize() != ts.normalize():
            return {}
        row = self._vals[k]
        return {n: float(v) for n, v in zip(self._names, row, strict=True) if np.isfinite(v)}
