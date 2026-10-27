# Experiment: mean reversion / fades (15-minute bars)

Date: 2026-10-27 · Branch: `exp/mean-reversion` · Script: `scripts/exp_mean_reversion.py`
New detectors: `src/bot/detectors/fades.py` (`VWAPFade`, `FailedORBFade`, `GapFade`, `RSI2Fade`).

## Why
Breakout and trend setups show about 0R before costs (docs/experiments/2026-10-12-*.md). If
breakouts lose slightly before costs, fading moves might gain. This experiment tests whether
fading stretched moves has a gross edge large enough to survive costs.

## Pre-registration (this section is committed before any result is computed)

### Data and windows
- 1m Fyers candles for the 8 watchlist stocks and NIFTY 50, resampled to closed 15m bars.
- Only parquet files for months up to 2026-07 are read. Rows after 2026-07-31 are dropped
  **before** any feature is computed. The 2026-08-01 .. 2026-10-09 holdout is not loaded.
- In-sample: 2025-10-17 .. 2026-04-30. Validation: 2026-05-01 .. 2026-07-31.
  Features in the validation window may use earlier (in-sample) bars as history. That is
  causal and matches what live trading would have.

### Common rules (all variants)
- 15-minute bars. Signal on a closed bar; fill at next-bar open + 0.05% slippage.
- Decision time (bar close) 09:30–14:45; square-off 15:10. Long and short.
- Exits: stop, target or the 15:10 square-off only (no other time exits).
- Costs: `config/costs.yaml` on both legs; stop and square-off exits pay slippage.
- Full-rules backtest: spec `config/risk.yaml` unchanged (1% risk, no leverage, min-edge 3x,
  3 trades/day, 1 open position, 2-loss stop, 3% daily loss), ₹1,000, `rules_only`.
- Cost-doubling stress: every percentage fee rate and the slippage multiplied by 2
  (GST stays 18% of the doubled base).

### Variants (8; no others will be run)
| ID | Detector | Signal | Target | Stop |
|---|---|---|---|---|
| V1 | `VWAPFade(1.0)` | close crosses ≥ 1.0% away from session VWAP (previous bar, same session, < 1.0%); fade toward VWAP | VWAP at signal bar | 1:1, i.e. entry ± (entry − VWAP) |
| V2 | `VWAPFade(1.5)` | same, threshold 1.5% | VWAP | 1:1 |
| V3 | `VWAPFade(1.0, confirm=True)` | earlier today the close was ≥ 1.0% from VWAP; now a reversal bar (short: close < previous bar low; long: close > previous bar high) with close still ≥ 0.6% from VWAP; first such signal per side per day | VWAP | session extreme on the stretched side (high for shorts, low for longs), risk floored at 0.6% of entry |
| V4 | `FailedORBFade(30, rr=1.0)` | 30-min opening range; previous bar closed outside the range, this bar closes back inside; first failure per side per day | 1.0R | session extreme on the failed side (the failed high/low), risk floored at 0.6% |
| V5 | `FailedORBFade(60, rr=1.0)` | same, 60-min opening range | 1.0R | same |
| V6 | `GapFade(1.0)` | open gaps ≥ 1.0% vs previous close; at the first bar closing at 09:30, if close is still ≥ 0.6% beyond previous close on the gap side, fade the gap | previous close | 1:1 |
| V7 | `RSI2Fade(10, 90, trend=True)` | RSI(2) on 15m closes crosses ≤ 10 (long) / ≥ 90 (short); long only if EMA21 > EMA50 (15m), short only if EMA21 < EMA50 | 1.0R | 2.0 × ATR(14, 15m) |
| V8 | `RSI2Fade(5, 95, trend=False)` | RSI(2) crosses ≤ 5 / ≥ 95, no trend filter | 1.0R | 2.0 × ATR(14, 15m) |

Every stop is at least ~0.6% of price by construction (1:1 stops follow a ≥ 0.6% target
distance) except V7/V8, whose 2×ATR(15m) is expected to be ~0.7% (median reported).

### Metrics per variant and window
Candidates; median stop %; win rate (target hit); nominal breakeven win rate
(mean of 1/(1 + target/stop) before costs); mean gross R (after slippage, before fees);
mean fee R; mean net R; 90% day-block bootstrap CI of net R (2,000 resamples, seed 0);
net R per calendar month; net R long vs short; net R with costs doubled.
Full-rules backtest: trades, win %, net ₹, max DD %, profit factor; and the same with costs
doubled.

### Selection rule (fixed)
1. Choose ONE variant: the highest **in-sample** mean net R among variants with ≥ 100
   in-sample candidates.
2. The chosen variant passes only if all hold:
   a. in-sample mean net R > 0;
   b. validation mean net R 90% CI lower bound > 0;
   c. validation full-rules backtest net ₹ > 0;
   d. validation mean net R with costs doubled > 0.
3. If it passes, it is recommended as this track's single candidate for the lead
   researcher's holdout run. If not, this track recommends no holdout run.
4. Any other variant that happens to meet (a)–(b) is reported as hypothesis-generating
   only, because it was not chosen in-sample.

### Multiple testing
8 variants. If none had an edge, each one-sided 90% CI would still exclude zero on the
positive side with ~5% probability, so ~1 − 0.95^8 ≈ 34% chance that at least one variant
looks "significant" on validation by luck. That is why only the in-sample choice can pass.

### Sanity checks
- Any win rate > 70% is treated as a probable bug and investigated before reporting.
- Assert that no loaded bar, feature or candidate is after 2026-07-31.
- Unit tests on hand-made candles for each detector, including a test that changing or
  removing future bars never changes the signal at bar i.

## Results
(to be filled in after the run)
