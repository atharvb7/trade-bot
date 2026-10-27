"""Experiment: execution realism — slippage, stop fills and passive limit entries.

Protocol (fixed before running; docs/experiments/2026-10-27-execution-realism.md):
  * Data: 1-minute bars up to 2026-07-31 ONLY. The 2026-08-01+ holdout is never loaded:
    every series is truncated right after reading, before any feature is computed.
  * Part 1 — spread proxies per symbol and time-of-day bucket (Roll, Corwin-Schultz,
    Abdi-Ranaldo, tick floor) with day-bootstrap 90% intervals.
  * Part 2 — stop fills: for every stop exit of the two setups, locate the 1-minute bar in
    which the stop was first touched and measure how far that minute's extreme and close
    went beyond the stop (plus the detector bar's own low/high and close).
  * Part 3 — market-entry latency proxy: signed drift over the first minute after the
    decision, in the trade direction.
  * Per-symbol evidence-based slippage (b) = max(entry, stop) estimate, rounded UP to 0.005%:
      entry = half the largest of the three spread estimates in any 09:30-15:30 bucket
              + latency drift over 2 s (if adverse);
      stop  = that half-spread + mean overshoot of the trigger minute's close beyond the stop.
  * Part 4 — on the selection window 2025-10-17 .. 2026-07-31, two setups
    (5m 3 detectors atr1.0 rr1.5; 15m RangeORB(60) rr3) under:
      (a) 0.05%/side (costs.yaml), (b) per-symbol estimate, (c) 2x (b),
      (d) passive limit entry at the signal price (offset 0 and 1 tick) resting 15 minutes,
          exits with (b) slippage, (e) (b) + targets fill only when traded through.
    Mean net R per candidate with a day-block bootstrap 90% CI. For limit entries, missed
    candidates count as 0 R; adverse selection = market-entry net R of filled vs missed.
"""

import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from bot.backtest.edge import day_bootstrap
from bot.backtest.fills import tick_size
from bot.backtest.liquidity import BUCKETS, estimate_spreads
from bot.config import ROOT, Config, ExecutionCfg, load_config
from bot.data.store import read_1m
from bot.detectors import ALL_DETECTORS
from bot.detectors.base import Detector, Frame
from bot.detectors.orb_range import RangeORB
from bot.features.engine import bar_table
from bot.ml.dataset import build_dataset

SELECT = (date(2025, 10, 17), date(2026, 7, 31))
LAST_ALLOWED = date(2026, 7, 31)  # holdout starts 2026-08-01: never loaded
LATENCY_S = 2.0  # bar close -> order at exchange (features + ML + Jev 800 ms + placement)
REST_MINUTES = 15  # passive limit rests this long before cancel
SETUPS: list[tuple[str, int, list[Detector], float, float]] = [
    ("5m_3det_atr1_rr1.5", 5, ALL_DETECTORS, 1.0, 1.5),
    ("15m_orb60_range_rr3", 15, [RangeORB(60)], 1.0, 3.0),
]
OUT = ROOT / "data" / "experiments" / "execution"
BP = 1e4


def load_raw(cfg: Config) -> dict[str, pd.DataFrame]:
    raw = {}
    for s in [*cfg.watchlist.symbols, cfg.watchlist.index]:
        df = read_1m(s)
        df = df[pd.DatetimeIndex(df.index).date <= LAST_ALLOWED]
        assert pd.DatetimeIndex(df.index).date.max() <= LAST_ALLOWED
        raw[s] = df
    return raw


def window(frames: dict[str, pd.DataFrame], lo: date, hi: date) -> dict[str, Frame]:
    out = {}
    for s, t in frames.items():
        d = pd.DatetimeIndex(t.index).date
        out[s] = Frame.from_df(t[(d >= lo) & (d <= hi)])
    return out


def setup_cfg(base: Config, atr: float, rr: float) -> Config:
    c = base.model_copy(deep=True)
    c.app.detectors.atr_stop_mult, c.app.detectors.reward_risk = atr, rr
    return c


def dataset(
    frames: dict[str, Frame],
    cfg: Config,
    bm: int,
    dets: list[Detector],
    slip: dict[str, float],
    ex: ExecutionCfg,
) -> pd.DataFrame:
    """Candidates for every symbol with that symbol's slippage (same code path as always)."""
    parts = []
    for s, fr in frames.items():
        c = cfg.model_copy(deep=True)
        c.costs.slippage_pct, c.app.execution = slip[s], ex
        parts.append(build_dataset({s: fr}, c, bm, dets))
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)
    return df.sort_values(["decision_ts", "symbol"]).reset_index(drop=True)


KEY = ["symbol", "ts", "setup", "direction"]


# ---------------------------------------------------------------- part 1: spreads
def spreads(raw: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    rows = []
    for s in symbols:
        e = estimate_spreads(raw[s], BUCKETS, n_boot=1000)
        e.insert(0, "symbol", s)
        rows.append(e)
    return pd.concat(rows, ignore_index=True)


def half_spread_by_symbol(sp: pd.DataFrame) -> dict[str, float]:
    """Half of the largest point estimate in any bucket inside 09:30-15:30 (fraction)."""
    trade = sp[sp["bucket"] != "09:15-09:30"]
    worst = trade[["roll", "cs", "ar"]].max(axis=1)
    return {str(s): float(v) / 2 for s, v in worst.groupby(trade["symbol"]).max().items()}


# ---------------------------------------------------------------- part 2: stop fills
def stop_overshoot(
    ds: pd.DataFrame, frames: dict[str, Frame], raw: dict[str, pd.DataFrame], bm: int
) -> pd.DataFrame:
    """Per stop exit: how far price went beyond the stop, at detector-bar and 1-minute level."""
    recs = []
    for r in ds[ds["outcome"] == "stop"].to_dict(orient="records"):
        fr, m1 = frames[str(r["symbol"])], raw[str(r["symbol"])]
        ts = pd.Timestamp(r["exit_ts"])
        k = fr.index.get_loc(ts)
        lo, hi, cl = (float(fr[x][k]) for x in ("low", "high", "close"))
        stop, sg = float(r["stop"]), 1 if r["direction"] == "long" else -1
        w = m1[(m1.index >= ts) & (m1.index < ts + pd.Timedelta(minutes=bm))]
        hit = w[w["low"] <= stop] if sg == 1 else w[w["high"] >= stop]
        if hit.empty:  # cannot happen with consistent data; keep the count honest
            continue
        b = hit.iloc[0]

        def beyond(px: float, stop: float = stop, sg: int = sg) -> float:
            return BP * sg * (stop - px) / stop

        recs.append(
            {
                "symbol": r["symbol"],
                "gap_1m": beyond(float(b["open"])) >= 0,
                "bar_extreme_bp": beyond(lo if sg == 1 else hi),
                "bar_close_bp": beyond(cl),
                "m1_extreme_bp": beyond(float(b["low"] if sg == 1 else b["high"])),
                "m1_close_bp": beyond(float(b["close"])),
                "m1_open_bp": beyond(float(b["open"])),
                "tick_bp": BP * tick_size(stop) / stop,
            }
        )
    return pd.DataFrame(recs)


def overshoot_summary(d: pd.DataFrame) -> pd.DataFrame:
    cols = ["bar_extreme_bp", "bar_close_bp", "m1_extreme_bp", "m1_close_bp"]
    q = d[cols].quantile([0.5, 0.9, 0.95, 0.99]).T
    q.columns = ["p50", "p90", "p95", "p99"]
    q.insert(0, "mean", d[cols].mean())
    return q


# ---------------------------------------------------------------- part 3: latency drift
def first_minute_drift(ds: pd.DataFrame, raw: dict[str, pd.DataFrame]) -> pd.Series:
    """Signed move (bp, + = against a market entry) over the first minute after the decision."""
    out = []
    for r in ds.to_dict(orient="records"):
        m1 = raw[str(r["symbol"])]
        k = int(m1.index.get_indexer(pd.DatetimeIndex([r["decision_ts"]]))[0])
        if k < 0:
            out.append(np.nan)
            continue
        o, c = float(m1["open"].to_numpy()[k]), float(m1["close"].to_numpy()[k])
        sg = 1 if r["direction"] == "long" else -1
        out.append(BP * sg * (c - o) / o)
    return pd.Series(out, index=ds.index)


# ---------------------------------------------------------------- part 4: re-evaluation
def ci(df: pd.DataFrame) -> list[float]:
    lo, hi = day_bootstrap(df, n=2000)
    return [lo, hi]


def diff_bootstrap(
    filled: pd.DataFrame, missed: pd.DataFrame, n: int = 2000, seed: int = 0
) -> tuple[float, float]:
    """90% CI of mean(filled) - mean(missed) net R, resampling whole days jointly."""
    days = pd.Index(
        sorted(
            set(filled["decision_ts"].dt.normalize()) | set(missed["decision_ts"].dt.normalize())
        )
    )

    def per_day(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        g = df.groupby(df["decision_ts"].dt.normalize())["net_r"].agg(["sum", "count"])
        g = g.reindex(days, fill_value=0)
        return g["sum"].to_numpy(float), g["count"].to_numpy(float)

    fs, fc = per_day(filled)
    ms, mc = per_day(missed)
    idx = np.random.default_rng(seed).integers(0, len(days), size=(n, len(days)))
    d = fs[idx].sum(1) / fc[idx].sum(1) - ms[idx].sum(1) / mc[idx].sum(1)
    return float(np.percentile(d, 5)), float(np.percentile(d, 95))


def summarise(name: str, d: pd.DataFrame, n_cand: int, rr: float) -> dict[str, Any]:
    return {
        "scenario": name,
        "candidates": n_cand,
        "entered": len(d),
        "win_rate": float(d["label"].mean() * 100),
        "breakeven": 100 / (1 + rr),
        "gross_r": float(d["gross_r"].sum() / n_cand),
        "net_r": float(d["net_r"].sum() / n_cand),
        "net_r_ci90": ci(d) if len(d) == n_cand else None,
    }


def setup_frames(cfg: Config, raw: dict[str, pd.DataFrame]) -> dict[str, dict[str, Frame]]:
    nifty = raw[cfg.watchlist.index]
    out = {}
    for name, bm, *_ in SETUPS:
        tables = {s: bar_table(raw[s], nifty, bm) for s in cfg.watchlist.symbols}
        out[name] = window(tables, *SELECT)
    return out


def probe(
    cfg: Config, raw: dict[str, pd.DataFrame], all_frames: dict[str, dict[str, Frame]]
) -> dict[str, Any]:
    """Stop overshoot and first-minute drift on the market-entry candidates.

    Neither depends on the slippage value, so they can feed estimate (b) without circularity.
    """
    out: dict[str, Any] = {}
    for name, bm, dets, atr, rr in SETUPS:
        frames = all_frames[name]
        slip_a = {s: cfg.costs.slippage_pct for s in cfg.watchlist.symbols}
        ds_a = dataset(frames, setup_cfg(cfg, atr, rr), bm, dets, slip_a, ExecutionCfg())
        out[name] = {
            "overshoot": stop_overshoot(ds_a, frames, raw, bm),
            "drift": first_minute_drift(ds_a, raw),
        }
    return out


def evaluate(
    cfg: Config,
    raw: dict[str, pd.DataFrame],
    all_frames: dict[str, dict[str, Frame]],
    probes: dict[str, Any],
    slip_b: dict[str, float],
) -> dict[str, Any]:
    symbols = cfg.watchlist.symbols
    out: dict[str, Any] = {}
    for name, bm, dets, atr, rr in SETUPS:
        c = setup_cfg(cfg, atr, rr)
        frames = all_frames[name]
        market = ExecutionCfg()
        slip_a = {s: cfg.costs.slippage_pct for s in symbols}
        slip_c = {s: 2 * v for s, v in slip_b.items()}
        ds_a = dataset(frames, c, bm, dets, slip_a, market)
        ds_b = dataset(frames, c, bm, dets, slip_b, market)
        ds_c = dataset(frames, c, bm, dets, slip_c, market)
        ds_e = dataset(frames, c, bm, dets, slip_b, ExecutionCfg(target_fill="through"))
        n = len(ds_a)
        assert len(ds_b) == len(ds_c) == len(ds_e) == n
        rows = [
            summarise("(a) 0.05%/side (costs.yaml)", ds_a, n, rr),
            summarise("(b) per-symbol estimate", ds_b, n, rr),
            summarise("(c) 2x estimate", ds_c, n, rr),
            summarise("(e) (b) + target fills only if traded through", ds_e, n, rr),
        ]
        rest_bars = max(1, REST_MINUTES // bm)
        limit: dict[str, Any] = {}
        for off in (0, 1):
            ex = ExecutionCfg(
                entry_order="limit", limit_offset_ticks=off, limit_cancel_bars=rest_bars
            )
            ds_d = dataset(frames, c, bm, dets, slip_b, ex)
            got = ds_b.merge(ds_d[KEY], on=KEY, how="left", indicator=True)
            filled_mask = (got["_merge"] == "both").to_numpy()
            filled_mkt, missed_mkt = ds_b[filled_mask], ds_b[~filled_mask]
            per_cand = ds_b[KEY + ["decision_ts"]].merge(
                ds_d[KEY + ["net_r", "gross_r", "label"]], on=KEY, how="left"
            )
            per_cand[["net_r", "gross_r", "label"]] = per_cand[
                ["net_r", "gross_r", "label"]
            ].fillna(0.0)
            r = summarise(f"(d) limit at signal {'-' if off else ''}{off} tick", ds_d, n, rr)
            r["net_r_ci90"] = ci(per_cand)
            r["net_r_per_fill"] = float(ds_d["net_r"].mean())
            rows.append(r)
            limit[f"offset_{off}"] = {
                "rest_bars": rest_bars,
                "fill_rate": float(filled_mask.mean() * 100),
                "fills": int(filled_mask.sum()),
                "limit_net_r_per_fill": float(ds_d["net_r"].mean()),
                "limit_net_r_per_fill_ci90": ci(ds_d),
                "market_net_r_filled": float(filled_mkt["net_r"].mean()),
                "market_net_r_missed": float(missed_mkt["net_r"].mean()),
                "market_gross_r_filled": float(filled_mkt["gross_r"].mean()),
                "market_gross_r_missed": float(missed_mkt["gross_r"].mean()),
                "market_win_filled": float(filled_mkt["label"].mean() * 100),
                "market_win_missed": float(missed_mkt["label"].mean() * 100),
                "filled_minus_missed_ci90": diff_bootstrap(filled_mkt, missed_mkt),
                "fill_rate_by_direction": (
                    pd.Series(filled_mask, index=ds_b.index)
                    .groupby(ds_b["direction"])
                    .mean()
                    .mul(100)
                    .round(1)
                    .to_dict()
                ),
            }
        # target exits that only touched the level (would not be certain fills)
        tgt = ds_b[ds_b["outcome"] == "target"]
        touch_only = 0
        for t in tgt.to_dict(orient="records"):
            fr = frames[str(t["symbol"])]
            k = fr.index.get_loc(pd.Timestamp(t["exit_ts"]))
            level = float(t["target"])
            tick = tick_size(level)
            if t["direction"] == "long":
                touch_only += int(float(fr["high"][k]) < level + tick - 1e-9)
            else:
                touch_only += int(float(fr["low"][k]) > level - tick + 1e-9)
        ov, drift = probes[name]["overshoot"], probes[name]["drift"]
        out[name] = {
            "rows": rows,
            "limit": limit,
            "median_stop_pct": float(ds_a["stop_pct"].median()),
            "target_exits": len(tgt),
            "target_touch_only": touch_only,
            "stop_exits": int(len(ov)),
            "stop_gap_1m_pct": float(ov["gap_1m"].mean() * 100) if len(ov) else 0.0,
            "overshoot": overshoot_summary(ov).round(2).to_dict() if len(ov) else {},
            "overshoot_by_symbol": ov.groupby("symbol")[["m1_extreme_bp", "m1_close_bp"]]
            .mean()
            .round(2)
            .to_dict()
            if len(ov)
            else {},
            "drift_1m_bp": {
                "mean": float(drift.mean()),
                "ci90": [
                    float(drift.mean() - 1.645 * drift.std() / math.sqrt(drift.count())),
                    float(drift.mean() + 1.645 * drift.std() / math.sqrt(drift.count())),
                ],
                "n": int(drift.count()),
            },
        }
    return out


def round_up(x: float, step: float = 0.005) -> float:
    return math.ceil(x / step - 1e-9) * step


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg = load_config()
    symbols = cfg.watchlist.symbols
    raw = load_raw(cfg)
    pd.set_option("display.width", 250)

    sp = spreads(raw, symbols)
    bp_cols = [c for c in sp.columns if c not in ("symbol", "bucket", "days", "pairs")]
    sp_bp = sp.copy()
    sp_bp[bp_cols] = sp_bp[bp_cols] * BP
    print("\n=== Part 1: full relative spread estimates (bp), 90% day-bootstrap CI ===")
    print(sp_bp.round(2).to_string(index=False))
    half = half_spread_by_symbol(sp)

    # Stop overshoot and drift come from the market-entry datasets at the current slippage;
    # neither depends on the slippage value, so they can set (b) without circularity.
    all_frames = setup_frames(cfg, raw)
    probes = probe(cfg, raw, all_frames)
    ov_all = pd.concat([v["overshoot"] for v in probes.values()], ignore_index=True)
    drift_all = pd.concat([v["drift"] for v in probes.values()], ignore_index=True)
    close_over = ov_all.groupby("symbol")["m1_close_bp"].mean()
    latency_bp = max(0.0, float(drift_all.mean())) * LATENCY_S / 60
    est = pd.DataFrame(
        {
            "half_spread_bp": pd.Series(half) * BP,
            "half_tick_bp": sp.groupby("symbol")["tick"].mean() * BP / 2,
            "latency_bp": latency_bp,
            "stop_close_overshoot_bp": close_over.clip(lower=0),
        }
    )
    est["entry_bp"] = est["half_spread_bp"] + est["latency_bp"]
    est["stop_bp"] = est["half_spread_bp"] + est["stop_close_overshoot_bp"]
    est["slip_b_pct"] = [
        round_up(max(e, s) / 100) for e, s in zip(est["entry_bp"], est["stop_bp"], strict=True)
    ]
    slip_b = {str(s): float(v) for s, v in est["slip_b_pct"].items()}
    print("\n=== Per-symbol evidence-based slippage per side ===")
    print(est.round(3).to_string())

    res = evaluate(cfg, raw, all_frames, probes, slip_b)
    for name, r in res.items():
        print(f"\n=== {name}: selection window {SELECT[0]} .. {SELECT[1]} ===")
        print(f"median stop distance {r['median_stop_pct']:.2f}% of price")
        tab = pd.DataFrame(r["rows"])
        tab["net_r_ci90"] = tab["net_r_ci90"].map(lambda x: f"[{x[0]:+.3f}, {x[1]:+.3f}]")
        print(tab.round(3).to_string(index=False))
        print("limit entries:", json.dumps(r["limit"], indent=1, default=str))
        print(
            f"stop exits {r['stop_exits']}, 1m gap through stop {r['stop_gap_1m_pct']:.1f}%;"
            f" target exits {r['target_exits']}, touch-only {r['target_touch_only']}"
        )
        print(pd.DataFrame(r["overshoot"]).round(2).to_string())
        print("first-minute drift after decision (bp, + = adverse):", r["drift_1m_bp"])

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{stamp}_execution.json"
    path.write_text(
        json.dumps(
            {
                "spreads_bp": sp_bp.to_dict(orient="records"),
                "estimates": est.reset_index(names="symbol").to_dict(orient="records"),
                "latency_drift_bp_per_min": float(drift_all.mean()),
                "stop_overshoot_pooled": overshoot_summary(ov_all).round(2).to_dict(),
                "results": res,
            },
            indent=1,
            default=str,
        )
    )
    print(f"\nSaved: {path}")


if __name__ == "__main__":
    main()
