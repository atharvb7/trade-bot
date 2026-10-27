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
Run once, as pre-registered: `20261027_220409` (8 variants, no reruns or parameter changes).
Backtest runs are in `data/backtests/20261027_220409_meanrev_*`, and the full JSON is in
`data/experiments/mean-reversion/20261027_220409_results.json`. No loaded bar or candidate
is dated after 2026-07-31 (the script asserts this).

### Candidate-level edge, in-sample 2025-10-17 .. 2026-04-30
Win = target hit. BE = nominal breakeven win rate before costs. Gross R is after slippage
and before fees. "×2" means every fee rate and the slippage are doubled.

| Variant | Cand. | Median stop | Win % | BE % | Gross R | Fee R | Net R | Net R 90% CI | Net R ×2 | Long n / R | Short n / R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 VWAP fade 1.0% | 421 | 1.12% | 19.0 | 50 | −0.16 | 0.09 | −0.25 | [−0.33, −0.16] | −0.42 | 225 / −0.22 | 196 / −0.29 |
| V2 VWAP fade 1.5% | 100 | 1.66% | 10.0 | 50 | −0.23 | 0.06 | −0.29 | [−0.41, −0.16] | −0.41 | 51 / −0.21 | 49 / −0.38 |
| V3 VWAP fade confirm | 121 | 0.60% | 21.5 | 46 | −0.25 | 0.15 | −0.40 | [−0.54, −0.25] | −0.68 | 69 / −0.36 | 52 / −0.45 |
| V4 failed ORB-30 | 590 | 0.60% | 27.5 | 50 | −0.13 | 0.16 | −0.29 | [−0.35, −0.23] | −0.58 | 313 / −0.37 | 277 / −0.20 |
| V5 failed ORB-60 | 508 | 0.60% | 23.8 | 50 | −0.15 | 0.16 | −0.31 | [−0.37, −0.25] | −0.61 | 280 / −0.35 | 228 / −0.26 |
| **V6 gap fade 1.0%** | 124 | 1.86% | 23.4 | 50 | +0.01 | 0.07 | **−0.06** | [−0.20, +0.07] | −0.18 | 61 / −0.07 | 63 / −0.05 |
| V7 RSI(2) 10/90 + trend | 1,324 | 0.75% | 23.1 | 50 | −0.12 | 0.15 | −0.27 | [−0.31, −0.22] | −0.55 | 678 / −0.27 | 646 / −0.27 |
| V8 RSI(2) 5/95 | 1,637 | 0.77% | 24.9 | 50 | −0.13 | 0.15 | −0.27 | [−0.31, −0.23] | −0.54 | 849 / −0.27 | 788 / −0.28 |

### Candidate-level edge, validation 2026-05-01 .. 2026-07-31
| Variant | Cand. | Median stop | Win % | Gross R | Fee R | Net R | Net R 90% CI | Net R ×2 | Long n / R | Short n / R |
|---|---|---|---|---|---|---|---|---|---|---|
| V1 | 172 | 1.09% | 15.1 | −0.18 | 0.10 | −0.28 | [−0.37, −0.19] | −0.45 | 87 / −0.29 | 85 / −0.26 |
| V2 | 33 | 1.63% | 15.2 | −0.04 | 0.06 | −0.10 | [−0.26, +0.08] | −0.22 | 17 / +0.00 | 16 / −0.22 |
| V3 | 44 | 0.60% | 22.7 | −0.07 | 0.16 | −0.23 | [−0.47, +0.01] | −0.52 | 21 / −0.26 | 23 / −0.20 |
| V4 | 297 | 0.60% | 32.0 | −0.05 | 0.16 | −0.21 | [−0.29, −0.14] | −0.49 | 166 / −0.30 | 131 / −0.10 |
| V5 | 254 | 0.60% | 31.1 | −0.11 | 0.16 | −0.27 | [−0.36, −0.17] | −0.55 | 143 / −0.38 | 111 / −0.12 |
| **V6** | 51 | 1.40% | 27.5 | +0.07 | 0.08 | **−0.02** | [−0.22, +0.17] | −0.16 | 26 / −0.06 | 25 / +0.03 |
| V7 | 641 | 0.72% | 22.5 | −0.11 | 0.15 | −0.26 | [−0.32, −0.20] | −0.54 | 291 / −0.33 | 350 / −0.21 |
| V8 | 792 | 0.73% | 28.2 | −0.07 | 0.15 | −0.22 | [−0.27, −0.17] | −0.49 | 421 / −0.28 | 371 / −0.16 |

### Net R per month (stability)
| Variant | 25-10 | 25-11 | 25-12 | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 | 26-07 |
|---|---|---|---|---|---|---|---|---|---|---|
| V1 | −0.72 | −0.34 | −0.60 | −0.26 | −0.21 | −0.15 | −0.24 | −0.30 | −0.29 | −0.22 |
| V2 | −0.27 | −0.57 | +0.26 | −0.46 | −0.44 | −0.09 | −0.17 | −0.15 | −0.06 | −0.09 |
| V3 | −0.66 | −0.40 | −0.51 | −0.64 | −0.23 | −0.22 | −0.41 | −0.29 | −0.27 | −0.11 |
| V4 | −0.15 | −0.30 | −0.33 | −0.22 | −0.38 | −0.26 | −0.31 | −0.22 | −0.28 | −0.14 |
| V5 | −0.21 | −0.38 | −0.34 | −0.25 | −0.30 | −0.26 | −0.39 | −0.35 | −0.39 | −0.07 |
| V6 | −0.27 | +0.11 | −0.66 | −0.17 | −0.21 | −0.15 | +0.19 | −0.22 | −0.05 | +0.26 |
| V7 | −0.47 | −0.23 | −0.40 | −0.24 | −0.19 | −0.27 | −0.22 | −0.32 | −0.27 | −0.22 |
| V8 | −0.32 | −0.34 | −0.33 | −0.43 | −0.26 | −0.12 | −0.15 | −0.27 | −0.22 | −0.19 |

Out of 80 variant-months, 4 are positive. V6 is positive in 3 of its 10 months.

### Full-rules backtest (₹1,000, spec risk rules, min-edge 3x, `rules_only`)
| Variant | IS trades | IS win % | IS net ₹ | IS max DD % | IS PF | IS ×2 net ₹ | Val trades | Val win % | Val net ₹ | Val max DD % | Val PF | Val ×2 net ₹ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 | 153 | 41.8 | −185 | 20.7 | 0.61 | −148 | 77 | 37.7 | −185 | 18.8 | 0.40 | −38 |
| V2 | 55 | 30.9 | −112 | 12.1 | 0.34 | −153 | 23 | 39.1 | −3 | 2.3 | 0.94 | −24 |
| V3 | 85 | 30.6 | −169 | 17.1 | 0.38 | −52 | 35 | 48.6 | −36 | 5.5 | 0.64 | −13 |
| V4 | 111 | 37.8 | −202 | 21.4 | 0.44 | −29 | 58 | 43.1 | −81 | 8.9 | 0.56 | +1 |
| V5 | 102 | 37.3 | −174 | 17.9 | 0.42 | −4 | 52 | 42.3 | −42 | 7.3 | 0.73 | −13 |
| V6 | 56 | 50.0 | +18 | 4.0 | 1.15 | −31 | 32 | 59.4 | +5 | 2.4 | 1.08 | −4 |
| V7 | 208 | 42.3 | −274 | 27.4 | 0.52 | −134 | 97 | 45.4 | −106 | 11.4 | 0.62 | −38 |
| V8 | 229 | 41.9 | −235 | 25.7 | 0.64 | −164 | 119 | 46.2 | −131 | 14.4 | 0.65 | −67 |

With doubled costs, the min-edge 3x rule blocks most candidates, so ×2 backtests take far
fewer trades. That is why some ×2 losses are smaller than the base-cost losses. The
candidate-level "Net R ×2" column is the like-for-like stress.

### Selection (as pre-registered)
- In-sample choice (highest net R, ≥ 100 candidates): **V6 gap fade 1.0%** (−0.061R).
- (a) in-sample net R > 0: **fail** (−0.061).
- (b) validation 90% CI lower bound > 0: **fail** ([−0.224, +0.171]).
- (c) validation backtest net ₹ > 0: pass (+₹5 on 32 trades; this is noise).
- (d) validation net R with costs ×2 > 0: **fail** (−0.164).
- **Result: FAIL.** No other variant meets (a) and (b). This track recommends **no holdout run**.

### Sanity checks
- No candidate win rate is above 70%; the highest is 32%. Backtest "win %" (net ₹ > 0)
  is higher than the candidate target-hit rate because many 15:10 timeouts close small
  winners.
- Unit tests: 21 detector tests, including truncating or scrambling every bar after i on
  real feature tables built from synthetic data. Each detector fires at least once there,
  and its signal never changes.
- Data: only parquet months up to 2026-07 were read. Rows after 2026-07-31 were dropped
  before `bar_table`, and the script asserts no bar or candidate is past the cutoff.

## Reading
- **Fading is not the mirror image of breaking out.** Breakouts showed ≈ 0R gross. These
  fades are also ≈ 0R once slippage is added back. Approximate slippage cost =
  (0.05% + 0.05% × non-target exits) / stop%: about 0.08R for V1, 0.14R for V4/V5 and 0.12R
  for V7/V8. Adding that back puts in-sample gross R before slippage at about −0.18R (V2),
  −0.10R (V3), −0.08R (V1), ≈ 0R (V4, V5, V7, V8) and +0.05R (V6). That is consistent with intraday price being close to a random walk at these
  horizons for these 8 large caps.
- **The pre-registered structural stops are mostly the 0.6% floor** (median stop exactly
  0.60% for V3, V4 and V5). The failed extreme is usually closer than 0.6%, so in practice
  these were fixed 0.6% stops. At 0.6%, fees alone cost ~0.16R, so they cannot win unless
  the gross edge is clearly positive. It is not.
- **Most trades end at the 15:10 square-off** (42–73% timeouts). Targets 1–1.9% away
  (VWAP, previous close) are rarely reached the same day. Their hit rate is far below the
  50% that a 1:1 fade needs.
- **V6 gap fade is the only variant near zero.** It is still not positive: gross ≈ +0.01R
  in-sample and +0.07R in validation, with fees of ~0.07–0.08R, on small samples (124 / 51
  candidates, ~1 per stock per month). Its months swing from −0.66R to +0.26R, and doubling
  costs makes it clearly negative. Its full-rules backtests are positive by a few rupees
  (+₹18 and +₹5), which is within noise.
- Long and short behave similarly in every variant, so the losses are not one-sided drift.

## Multiple testing
8 variants tried, run once, nothing else. Even before any correction, none has a positive
net R CI in either window. In-sample, 7 of 8 CIs lie entirely below zero. In validation,
5 of 8 do; the other three (V2, V3, V6) have small samples and wide CIs that span zero.
After allowing for 8 tries, the evidence for an edge is weaker still.

## Conclusion
Simple intraday fades (VWAP stretch, failed opening-range breakout, opening gap, RSI(2)
extremes) on 15-minute bars show no edge after costs on these 8 NSE large caps between
2025-10 and 2026-07. Their gross edge is about zero, like the breakout setups, so the
negative net result is mostly costs. The pre-registered rule selects V6 (gap fade), and V6
fails 3 of 4 checks. **Recommendation: no holdout run for this track and no config
changes.** The gap fade is the only idea worth revisiting, and only with more data (longer
history or more symbols) to reach a meaningful sample. It would need a fresh
pre-registration, not a retune on these results.

## Note after merge (2026-10-27)
These numbers were produced on the backtester before the fixes in
`docs/experiments/2026-10-27-backtest-audit.md`. On 15-minute bars the main fix (square-off at
the 15:00 open instead of the 15:15 open) lowered net R by about 0.014R for RangeORB(60), so the
results above, if anything, slightly flatter these variants. The conclusion is unchanged.
