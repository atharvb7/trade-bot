# Experiment: wider stops so costs are a small fraction of risk (15-minute bars)

Date: 2026-10-12 · Branch: `exp/wide-targets` · Script: `scripts/exp_wide_targets.py`
New detector: `RangeORB` (`src/bot/detectors/orb_range.py`), with the stop at the opposite side of
the 30- or 60-minute opening range.

## Protocol (fixed before running)
6 variants on 15-minute bars, spec risk rules unchanged (min-edge 3x, 1% risk, 3 trades/day).
Chosen by mean net R per candidate on 2025-10-17 .. 2026-07-31 (≥ 100 candidates); the
chosen variant and the V1 baseline then run once on the 2026-08-01 .. 2026-10-09 holdout.
The 90% intervals come from a day-block bootstrap, because candidates on the same day are correlated.

## Selection window
| Variant | Candidates | Median stop | Gross R | Net R | Net R 90% CI | Trades | Net ₹ | Max DD % |
|---|---|---|---|---|---|---|---|---|
| V1 3 detectors, atr1, rr1.5 | 5,552 | 0.37% | −0.23 | −0.53 | [−0.56, −0.49] | 365 | −401 | 40.1 |
| V2 3 detectors, atr2, rr2 | 5,552 | 0.74% | −0.12 | −0.27 | [−0.30, −0.25] | 289 | −223 | 23.3 |
| V3 ORB-30 range, rr2 | 2,143 | 1.24% | −0.09 | −0.19 | [−0.22, −0.16] | 229 | −238 | 24.2 |
| V4 ORB-30 range, rr3 | 2,143 | 1.24% | −0.10 | −0.19 | [−0.22, −0.16] | 223 | −243 | 24.6 |
| V5 ORB-60 range, rr2 | 1,790 | 1.38% | −0.08 | −0.17 | [−0.20, −0.13] | 210 | −179 | 19.1 |
| **V6 ORB-60 range, rr3** | 1,790 | 1.38% | −0.08 | **−0.16** | [−0.20, −0.13] | 207 | −168 | 18.1 |

## Holdout (run once)
| Variant | Candidates | Net R | Net R 90% CI | Trades | Win % | Net ₹ | Max DD % |
|---|---|---|---|---|---|---|---|
| V1 baseline | 1,348 | −0.65 | [−0.72, −0.58] | 75 | 29.3 | −177 | 18.9 |
| V6 chosen | 468 | −0.17 | [−0.23, −0.12] | 57 | 49.1 | −46 | 6.7 |

## Reading
- Wider stops did what they were meant to: cost drag fell from ~1R (5m) to ~0.08R in fees plus
  ~0.07R in slippage (ORB-range). **Costs are no longer the main problem.**
- With costs small, the signal itself shows: before slippage and fees it is ≈ 0R. Every
  variant's 90% interval excludes zero on the negative side, in both windows.
- Targets of 2–3R (~2.5–4% moves) are almost never reached intraday; most trades exit at the
  15:10 square-off, which is why rr2 and rr3 behave alike.
- Long and short behave the same (−0.17R vs −0.16R), so this is not one-sided drift.

## Conclusion
Across 1m, 5m and 15m bars, ATR and structural stops, and an ML filter, simple public price and
volume setups on these 8 large-cap NSE stocks show no intraday edge in the last 12 months. No
config changes. Going live is not justified.
