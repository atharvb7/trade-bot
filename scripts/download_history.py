"""Download 1m history for the watchlist + Nifty 50 into Parquet.

Needs FYERS_APP_ID and FYERS_ACCESS_TOKEN in .env (never pass keys on the command line).
Usage: python scripts/download_history.py [--months 12]
"""

import argparse
from datetime import date, timedelta

from bot.config import Secrets, load_config
from bot.data.fyers_provider import FyersProvider
from bot.data.store import write_1m

ap = argparse.ArgumentParser()
ap.add_argument("--months", type=int, default=12)
args = ap.parse_args()

cfg, sec = load_config(), Secrets()
if not (sec.fyers_app_id and sec.fyers_access_token):
    raise SystemExit("Set FYERS_APP_ID and FYERS_ACCESS_TOKEN in .env first.")
prov = FyersProvider(sec.fyers_app_id, sec.fyers_access_token)
end = date.today()
start = end - timedelta(days=30 * args.months)
for sym in [*cfg.watchlist.symbols, cfg.watchlist.index]:
    df = prov.history_1m(sym, start, end)
    write_1m(df, sym)
    print(f"{sym}: {len(df)} bars")
