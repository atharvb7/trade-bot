"""Bid-ask spread proxies from 1-minute OHLC bars (no quote data is available).

Three low-frequency estimators, all in relative (log-price) units, computed on pairs of
consecutive bars inside one session and pooled within a time-of-day bucket:

* Roll (1984): S = 2 * sqrt(-cov(r_t, r_{t+1})) from the bid-ask bounce in close-to-close
  returns. Undefined (reported as 0) when the autocovariance is positive.
* Corwin & Schultz (2012): from the high-low ranges of two consecutive bars and of the pair.
  Negative two-bar estimates are set to zero before averaging, as in the paper (biases up).
* Abdi & Ranaldo (2017): S^2 = 4 E[(c_t - eta_t)(c_t - eta_{t+1})], eta = mid of log high/low.

Uncertainty: a day-block bootstrap (whole sessions resampled), since bars within a day share
the same liquidity regime. The minimum possible spread is one tick (``fills.tick_size``).
These are proxies with known biases (see docs/experiments/2026-10-27-execution-realism.md).
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from bot.backtest.fills import tick_size

BUCKETS: list[tuple[time, time]] = [
    (time(9, 15), time(9, 30)),
    (time(9, 30), time(10, 0)),
    (time(10, 0), time(11, 0)),
    (time(11, 0), time(13, 0)),
    (time(13, 0), time(14, 30)),
    (time(14, 30), time(15, 30)),
]
_K = 3 - 2 * np.sqrt(2)


def spread_terms(df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar ingredients for pair (t, t+1); rows whose t+1 is in another session are dropped."""
    idx = pd.DatetimeIndex(df.index)
    day = np.asarray(idx.normalize())
    lh = np.log(df["high"].to_numpy(dtype=float))
    lo = np.log(df["low"].to_numpy(dtype=float))
    lc = np.log(df["close"].to_numpy(dtype=float))
    nxt = np.r_[day[1:] == day[:-1], False]  # t+1 exists in the same session
    prv = np.r_[False, nxt[:-1]]  # t-1 exists in the same session

    def lead(x: np.ndarray) -> np.ndarray:
        return np.asarray(np.r_[x[1:], np.nan], dtype=float)

    r = np.where(prv, np.diff(lc, prepend=np.nan), np.nan)  # return into bar t
    beta = (lh - lo) ** 2 + lead((lh - lo) ** 2)
    gamma = (np.maximum(lh, lead(lh)) - np.minimum(lo, lead(lo))) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / _K - np.sqrt(gamma / _K)
    eta = (lh + lo) / 2
    close = df["close"].to_numpy(dtype=float)
    out = pd.DataFrame(
        {
            "day": day,
            "tod": idx.time,
            "roll_a": r,
            "roll_b": lead(r),
            "cs": 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha)),
            "ar": (lc - eta) * (lc - lead(eta)),
            "tick_rel": np.array([tick_size(p) for p in close]) / close,
        },
        index=idx,
    )
    return out[nxt]


def _estimates(g: pd.DataFrame) -> pd.DataFrame:
    """Per-day sufficient statistics so that pooled estimates can be day-bootstrapped."""
    ok = g["roll_a"].notna() & g["roll_b"].notna()
    a, b = g["roll_a"].where(ok, 0.0), g["roll_b"].where(ok, 0.0)
    return (
        pd.DataFrame(
            {
                "n_roll": ok.astype(float),
                "sa": a,
                "sb": b,
                "sab": a * b,
                "n": 1.0,
                "cs0": g["cs"].clip(lower=0.0),
                "cs_raw": g["cs"],
                "ar": g["ar"],
                "tick": g["tick_rel"],
            }
        )
        .groupby(g["day"].to_numpy())
        .sum()
    )


def _pooled(s: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Estimators from summed statistics (vectorised over bootstrap replicates)."""
    n_r = s["n_roll"]
    cov = s["sab"] / n_r - (s["sa"] / n_r) * (s["sb"] / n_r)
    return {
        "roll": 2 * np.sqrt(np.maximum(0.0, -cov)),
        "cs": s["cs0"] / s["n"],
        "cs_raw": s["cs_raw"] / s["n"],
        "ar": np.sqrt(np.maximum(0.0, 4 * s["ar"] / s["n"])),
        "tick": s["tick"] / s["n"],
    }


def estimate_spreads(
    df: pd.DataFrame,
    buckets: list[tuple[time, time]] | None = None,
    n_boot: int = 500,
    seed: int = 0,
) -> pd.DataFrame:
    """Full relative spread (fraction of price) per time bucket, with 90% day-bootstrap CIs."""
    terms = spread_terms(df)
    rng = np.random.default_rng(seed)
    rows = []
    for lo, hi in buckets or BUCKETS:
        g = terms[(terms["tod"] >= lo) & (terms["tod"] < hi)]
        if g.empty:
            continue
        per_day = _estimates(g)
        arr = per_day.to_numpy()
        cols = list(per_day.columns)
        point = _pooled({c: arr[:, k].sum() for k, c in enumerate(cols)})
        sums = arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))].sum(axis=1)
        boot = _pooled({c: sums[:, k] for k, c in enumerate(cols)})
        row: dict[str, object] = {
            "bucket": f"{lo:%H:%M}-{hi:%H:%M}",
            "days": len(per_day),
            "pairs": int(per_day["n"].sum()),
        }
        for k, v in point.items():
            row[k] = float(v)
            if k != "tick":
                row[f"{k}_lo"] = float(np.quantile(boot[k], 0.05))
                row[f"{k}_hi"] = float(np.quantile(boot[k], 0.95))
        rows.append(row)
    return pd.DataFrame(rows)
