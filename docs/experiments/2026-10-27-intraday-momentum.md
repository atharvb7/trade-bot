# Experiment: time-of-day momentum and cross-sectional relative strength

Date: 2026-10-27 · Branch: `exp/intraday-momentum` · Script: `scripts/exp_intraday_momentum.py`
New detectors: `IntradayMomentum` and `RelativeStrength` (`src/bot/detectors/momentum.py`),
plus a look-ahead-safe cross-sectional panel (`src/bot/detectors/cross_section.py`).

## Pre-registration (committed before any result was computed)

### Data and windows
- 8 stocks (NTPC, ITC, ONGC, POWERGRID, TATASTEEL, COALINDIA, WIPRO, ETERNAL) + NIFTY_50, 1m bars.
- Only dates <= 2026-07-31 are read. The script loads only monthly parquet files up to
  2026-07 and filters to <= 2026-07-31 before any feature is computed. The holdout
  (2026-08-01 onward) is not loaded or reported by this track.
- In-sample: 2025-10-17 .. 2026-04-30. Validation: 2026-05-01 .. 2026-07-31. Both reported.
- Detector bars: 5 minutes (the configured `bar_minutes`). Decision time = close of the signal
  bar; fill = next bar open + 0.05% slippage; full fees from `config/costs.yaml` on both legs.

### Common trade rules (all variants)
- Stop: the session extreme so far (session low for a long, high for a short, through the
  signal bar), but never closer than **0.6% of price**: risk = max(distance to extreme, 0.6%).
- Target: 3 × risk (expected to be rarely reached). Most exits should be the 15:10 square-off.
- At most one signal per symbol per day (signals are evaluated at a single fixed bar).
- `r_open(t)` = close at t / open of the 09:15 bar − 1 (session open must be present).
  `r_pc(t)` = close at t / last close of the previous session − 1.
  NIFTY values are taken from NIFTY_50 bars that have closed at or before the decision time.

### Variants (8; no others will be counted)
| Id | Family | Signal at decision time | Direction |
|---|---|---|---|
| M1 | TS momentum | decide 10:15; \|r_open(10:15)\| ≥ 0.50% | sign of r_open |
| M2 | TS momentum incl. gap | decide 10:15; \|r_pc(10:15)\| ≥ 0.75% | sign of r_pc |
| M3 | TS momentum, later | decide 11:15; \|r_open(11:15)\| ≥ 0.75% | sign of r_open |
| M4 | M1 + trend-day filter | M1 and NIFTY r_open(10:15) same sign with \|·\| ≥ 0.30% | sign |
| M5 | M1 + range-day filter | M1 and \|NIFTY r_open(10:15)\| < 0.30% | sign |
| M6 | Cross-sectional RS | decide 10:15; rel = r_open(stock) − r_open(NIFTY). If NIFTY r_open ≥ +0.20%: long the max-rel stock if rel > 0 and its r_open > 0. If NIFTY r_open ≤ −0.20%: short the min-rel stock if rel < 0 and its r_open < 0. Else nothing | one stock/day |
| M7 | Cross-sectional RS, later | M6 at 11:15 | one stock/day |
| M8 | Gao-style first half hour | sign of r_pc(09:45), \|·\| ≥ 0.50%; decide 14:30, exit 15:10 | sign |

Ties in the cross-sectional rank break alphabetically by symbol. M4/M5 test whether
time-series momentum depends on the index regime (trend days vs range days); M8 is the
closest analogue of Gao, Han, Li & Zhou (2018) allowed by the 15:10 square-off.

### Metrics (per variant, per window)
Candidate level (every tradeable candidate, independent of account caps): candidates, median
stop %, win rate (net R > 0), breakeven win rate (|avg loss R| / (avg win R + |avg loss R|)),
target-hit rate, mean gross R (after slippage, before fees), mean fee R, mean net R, 90%
day-block bootstrap CI of mean net R (2,000 resamples, seed 0), per-month net R, long vs
short, and net R with all cost rates doubled.
Full rules (Backtester, spec `config/risk.yaml`, min-edge 3×, ₹1,000 start in each window,
`rules_only`): trades, win %, net ₹, max DD %, profit factor; and net ₹ with costs doubled.

### Selection rule
A variant **passes** only if all hold:
1. in-sample mean net R > 0;
2. validation 90% CI of mean net R has its lower bound > 0;
3. at least 30 validation candidates;
4. full-rules validation backtest net ₹ > 0.

If one or more pass, the one with the highest validation CI lower bound is recommended to the
lead researcher as this track's holdout candidate. If none passes, this track recommends no
holdout run. Parameters are not changed after results are seen; any later idea is labelled
exploratory and is not a candidate.

### Multiple testing
8 variants × 2 windows. With 8 roughly independent tests, the chance that at least one
validation CI excludes zero on the positive side by luck is about 1 − 0.95⁸ ≈ 34% (less here,
because the variants overlap heavily); requiring a positive in-sample mean as well reduces it.
A single pass is therefore weak evidence, not proof.

## Results

(to be filled in after the run)
