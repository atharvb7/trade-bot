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

Run `20261027_220520` (one run, no parameter changed after it). Backtests are saved as
`data/backtests/20261027_220520_mom_<variant>_<window>`; full numbers are in
`data/experiments/intraday-momentum/20261027_220520_results.json` (both gitignored).
Data loaded up to 2026-07-31 15:25. The script asserts this and never opens later files.
Win rate is the share of candidates with net R > 0. Breakeven win rate =
|avg loss R| / (avg win R + |avg loss R|), from net R.

### In-sample 2025-10-17 .. 2026-04-30 (candidate level)
| Variant | Cand. | Median stop | Win % | BE win % | Gross R | Fee R | Net R | Net R 90% CI | Net R, costs ×2 |
|---|---|---|---|---|---|---|---|---|---|
| M1 TS open→10:15 ≥0.5% | 584 | 1.34% | 41.3 | 54.7 | −0.076 | 0.084 | −0.161 | [−0.219, −0.103] | −0.343 |
| M2 TS prev close→10:15 ≥0.75% | 427 | 1.39% | 42.2 | 52.7 | −0.053 | 0.087 | −0.139 | [−0.217, −0.063] | −0.325 |
| M3 TS open→11:15 ≥0.75% | 471 | 1.69% | 41.0 | 53.5 | −0.044 | 0.066 | −0.110 | [−0.157, −0.064] | −0.253 |
| M4 M1 + NIFTY trend day | 204 | 1.38% | 38.2 | 54.7 | −0.111 | 0.082 | −0.192 | [−0.308, −0.083] | −0.369 |
| M5 M1 + NIFTY range day | 330 | 1.29% | 41.5 | 54.3 | −0.069 | 0.087 | −0.156 | [−0.230, −0.079] | −0.344 |
| M6 XS rel. strength 10:15 | 69 | 1.89% | 36.2 | 53.8 | −0.113 | 0.065 | −0.178 | [−0.309, −0.046] | −0.318 |
| M7 XS rel. strength 11:15 | 73 | 2.37% | 41.1 | 52.7 | −0.018 | 0.055 | −0.073 | [−0.157, +0.009] | −0.192 |
| M8 Gao first 30 min → 14:30 | 564 | 1.18% | 27.5 | 60.8 | −0.091 | 0.104 | −0.195 | [−0.233, −0.157] | −0.421 |

### Validation 2026-05-01 .. 2026-07-31 (candidate level)
| Variant | Cand. | Median stop | Win % | BE win % | Gross R | Fee R | Net R | Net R 90% CI | Net R, costs ×2 |
|---|---|---|---|---|---|---|---|---|---|
| M1 | 266 | 1.27% | 38.0 | 55.2 | −0.127 | 0.090 | −0.217 | [−0.305, −0.122] | −0.411 |
| M2 | 188 | 1.25% | 36.7 | 53.1 | −0.131 | 0.096 | −0.227 | [−0.336, −0.117] | −0.433 |
| M3 | 194 | 1.69% | 34.0 | 53.2 | −0.108 | 0.067 | −0.175 | [−0.248, −0.106] | −0.321 |
| M4 | 68 | 1.37% | 36.8 | 48.9 | −0.061 | 0.086 | −0.147 | [−0.312, +0.048] | −0.333 |
| M5 | 166 | 1.19% | 33.7 | 57.5 | −0.209 | 0.091 | −0.299 | [−0.414, −0.179] | −0.496 |
| M6 | 33 | 2.01% | 36.4 | 42.3 | −0.003 | 0.063 | −0.066 | [−0.271, +0.132] | −0.202 |
| M7 | 33 | 2.27% | 42.4 | 48.6 | +0.009 | 0.059 | −0.050 | [−0.192, +0.089] | −0.178 |
| M8 | 260 | 1.08% | 29.6 | 64.5 | −0.101 | 0.109 | −0.210 | [−0.256, −0.166] | −0.446 |

Exits: 75–96% of candidates end at the 15:10 square-off, 4–24% at the stop, and the 3R
target is hit by ≤ 2.1% (as designed). No candidate or backtest win rate is above 70%.

### Full-rules backtest (₹1,000 start in each window, spec risk rules, min-edge 3×)
| Variant | IS trades | IS win % | IS net ₹ | IS max DD % | IS PF | IS net ₹ ×2 | Val trades | Val win % | Val net ₹ | Val max DD % | Val PF | Val net ₹ ×2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | 130 | 40.8 | −97.1 | 10.4 | 0.71 | −233.4 | 63 | 39.7 | −99.0 | 13.2 | 0.50 | −167.1 |
| M2 | 122 | 43.4 | −70.8 | 7.1 | 0.78 | −222.6 | 59 | 37.3 | −103.2 | 12.6 | 0.40 | −165.0 |
| M3 | 126 | 43.7 | −108.8 | 11.1 | 0.58 | −242.4 | 59 | 40.7 | −46.3 | 7.4 | 0.67 | −106.1 |
| M4 | 50 | 34.0 | −63.1 | 7.4 | 0.56 | −122.7 | 21 | 52.4 | −17.9 | 3.6 | 0.66 | −46.0 |
| M5 | 79 | 43.0 | −41.2 | 5.7 | 0.79 | −143.2 | 41 | 31.7 | −76.7 | 9.9 | 0.46 | −128.1 |
| M6 | 60 | 35.0 | −81.1 | 8.4 | 0.49 | −145.7 | 30 | 36.7 | −17.2 | 3.6 | 0.74 | −43.8 |
| M7 | 55 | 34.5 | −53.4 | 5.4 | 0.46 | −104.2 | 29 | 44.8 | +0.1 | 1.5 | 1.00 | −30.6 |
| M8 | 129 | 34.1 | −98.5 | 9.9 | 0.43 | −247.1 | 61 | 37.7 | −66.0 | 6.6 | 0.37 | −162.5 |

### Long vs short and by month
Long and short are both negative in every variant and window except M7 validation short
(+0.11R on 12 candidates). Month by month, 69 of 80 variant-months are below zero; the
others are scattered (January 2026 is the only month where most variants, 5 of 8, were
positive) and none persists. Validation July 2026 was the worst month for every TS variant.

### Selection rule outcome
**No variant passes.** Every in-sample mean net R is negative (rule 1 fails for all 8), and
no validation CI lower bound is above zero (rule 2 fails for all 8). M6 and M7 also have only
33 validation candidates, close to the 30 minimum, so their wide CIs say little.

## Reading
- Costs are small, as intended: median stops are 1.1–2.4% of price, so fees are 0.06–0.10R
  and slippage (0.05% per side) is roughly 0.04–0.09R. Costs are no longer what decides this.
- The signal itself is about zero or slightly negative. Adding the approximate slippage cost
  back (0.1% / median stop), M1–M3 and M8 are between about −0.05R and 0R before costs in
  both windows (M5 validation about −0.13R): the morning move on these 8 large caps does not
  carry into the afternoon, and does not reverse strongly either.
- The NIFTY regime split does not help: trend-day (M4) and range-day (M5) filters are both
  negative in both windows, so the published market-level effect does not show up in these
  single stocks over this year with a 15:10 exit.
- Cross-sectional relative strength (M6, M7) is the least bad, with gross R close to zero
  in validation, but in-sample net R is negative and the samples are small (≈ 70 and 33
  candidates). That is consistent with noise, not an edge.
- Doubling costs makes every variant clearly negative (−0.18R to −0.50R).

## Multiple testing
8 variants were pre-registered and 8 were run, in 2 windows, once. No other variants or
parameter values were tried. Since nothing passed, there is no selection to correct for. If
one had passed, the ≈ 34% family-wise false-positive chance noted above would still apply.

## Conclusion
Time-of-day momentum (open or previous-close anchored, 10:15/11:15/Gao-style 14:30 entries),
NIFTY regime filters and one-stock-per-day cross-sectional relative strength show no
after-cost edge on these 8 NSE stocks between 2025-10-17 and 2026-07-31. With wide stops,
costs are only about 0.1–0.2R, and the signal before costs is about zero. **This track
recommends no holdout run** and no config changes. Going live is not justified on this
evidence. These detectors stay in the codebase (tested, look-ahead-safe) for later
cross-sectional work, but no variant is enabled.
