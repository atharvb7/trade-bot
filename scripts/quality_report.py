"""Print a data-quality report for every stored symbol (raw data, before cleaning)."""

import json

from bot.config import load_config
from bot.data.quality import check
from bot.data.sessions import clean_1m
from bot.data.store import read_1m

cfg = load_config()
for sym in [*cfg.watchlist.symbols, cfg.watchlist.index]:
    raw = read_1m(sym, clean=False)
    rep = check(raw, sym).as_dict()
    clean, notes = clean_1m(raw)
    rep["after_cleaning"] = {
        "bars": len(clean),
        "days": int(clean.index.normalize().nunique()),
        **notes,
    }
    print(json.dumps(rep, indent=1))
