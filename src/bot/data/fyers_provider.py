"""Fyers historical data provider (API v3).

UNVERIFIED against the live API until credentials exist: request/response shape is
taken from Fyers' v3 docs (history -> {"s": "ok", "candles": [[epoch,o,h,l,c,v], ...]},
1-min limited to ~100 days per request). Run scripts/download_history.py to verify.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import pandas as pd

from bot.config import ROOT
from bot.data.provider import OHLCV

CHUNK_DAYS = 90
LOG_DIR = ROOT / "logs"
INDEX_SYMBOLS = {"NIFTY 50": "NSE:NIFTY50-INDEX"}


def fyers_symbol(symbol: str) -> str:
    return INDEX_SYMBOLS.get(symbol, f"NSE:{symbol}-EQ")


def parse_candles(candles: list[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(candles, columns=["ts", *OHLCV])
    idx = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df.index = pd.DatetimeIndex(idx.dt.tz_localize(None), name="ts")
    return df.drop(columns="ts").astype(float)


class FyersProvider:
    def __init__(self, client_id: str, access_token: str, pause_s: float = 0.5) -> None:
        from fyers_apiv3 import fyersModel  # lazy: optional dependency

        self._fyers: Any = fyersModel.FyersModel(
            client_id=client_id, token=access_token, is_async=False, log_path=str(LOG_DIR) + "/"
        )
        self._pause = pause_s

    def history_1m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        cur = start
        while cur <= end:
            stop = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
            resp = self._fyers.history(
                data={
                    "symbol": fyers_symbol(symbol),
                    "resolution": "1",
                    "date_format": "1",
                    "range_from": cur.isoformat(),
                    "range_to": stop.isoformat(),
                    "cont_flag": "1",
                }
            )
            if resp.get("s") not in ("ok", "no_data"):  # no_data = no trading days in range
                raise RuntimeError(f"Fyers history failed for {symbol}: {resp.get('message')}")
            if resp.get("candles"):
                frames.append(parse_candles(resp["candles"]))
            cur = stop + timedelta(days=1)
            time.sleep(self._pause)  # stay well under rate limits
        if not frames:
            return pd.DataFrame(columns=OHLCV)
        out = pd.concat(frames)
        return out[~out.index.duplicated(keep="last")].sort_index()
