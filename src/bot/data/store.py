"""Parquet candle store, partitioned data/parquet/<symbol>/<YYYY-MM>.parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.config import ROOT
from bot.data.sessions import clean_1m

DEFAULT_DIR = ROOT / "data" / "parquet"


def _safe(symbol: str) -> str:
    return symbol.replace(" ", "_").replace(":", "_")


def write_1m(df: pd.DataFrame, symbol: str, base: Path = DEFAULT_DIR) -> None:
    for period, part in df.groupby(pd.DatetimeIndex(df.index).to_period("M")):
        path = base / _safe(symbol) / f"{period}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            part = pd.concat([pd.read_parquet(path), part])
            part = part[~part.index.duplicated(keep="last")]
        part.sort_index().to_parquet(path)


def read_1m(symbol: str, base: Path = DEFAULT_DIR, clean: bool = True) -> pd.DataFrame:
    files = sorted((base / _safe(symbol)).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No data for {symbol} in {base}")
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    return clean_1m(df)[0] if clean else df
