# Experiment: daily cross-sectional signals, traded open to close

Date: 2026-11-14 · Branch: `exp/daily-signals` · Script: `scripts/exp_daily_signals.py`
Data: NSE full bhavcopy (`scripts/download_bhavcopy.py`), every listed security, 2019-11 onward.

## Why
Seven earlier experiments found no edge in price-and-volume patterns on 1m–15m bars of 8 large
caps. Those tests share three limits: 8 stocks, 12 months, and signals that come from the same
intraday bars they trade. This experiment changes all three: about 200 stocks per day chosen
point-in-time (no survivorship bias), 7 years, and signals taken from *previous days*, so the
order can go into the 09:00–09:07 pre-open session and fill at the official opening price.
The trade is still intraday (exit before the close), so rules 1–10 in CLAUDE.md are unchanged.

## Pre-registration (committed before any result is computed)

### Data and windows
- EQ series only. `PREV_CLOSE` is the exchange's corporate-action-adjusted base price, so
  overnight return = OPEN / PREV_CLOSE − 1 and intraday return = CLOSE / OPEN − 1 need no
  further adjustment.
- Selection: 2019-11-01 .. 2023-12-31. Validation: 2024-01-01 .. 2025-06-30.
- Holdout: 2025-07-01 onward. The script drops these rows right after loading unless
  `--holdout` is passed, and that flag is used once, only for variants that pass (below).

### Universe (point-in-time, known before the open of day t)
- Rank stocks by median daily turnover over days t−20 .. t−1; keep the top 200.
- Require 20 prior trading days and PREV_CLOSE ≥ ₹20.
- Drop a stock-day if |overnight return| > 20% (listing days, data errors).

### Trade rules (all variants)
- Signal uses data up to and including day t−1 only.
- Entry at the official OPEN of day t, exit at the official CLOSE of day t. No stop, no target.
- Costs: `config/costs.yaml` fees on both legs plus 0.05% slippage per side (unchanged, even
  though an auction fill has no spread). Round trip is about 0.21% of price.
- Each day the 5 stocks with the most extreme signal are the candidates (ties: alphabetical).

### Variants (8; no others will be counted)
| Id | Signal on days ≤ t−1 | Pick | Side |
|---|---|---|---|
| D1 | sum of intraday returns, last 20 days | highest 5 | long |
| D2 | same | lowest 5 | short |
| D3 | sum of overnight returns, last 20 days | lowest 5 | long |
| D4 | same | highest 5 | short |
| D5 | close-to-close return of day t−1 | lowest 5 | long |
| D6 | same | highest 5 | short |
| D7 | day t−1 turnover ≥ 3 × its 20-day median and return ≥ +3%; rank by return | highest 5 | long |
| D8 | day t−1 turnover ≥ 3 × its 20-day median and return ≤ −3%; rank by return | lowest 5 | short |

D1–D4 follow Lou, Polk & Skouras (2019), who find that intraday returns persist and that
stocks with high overnight returns have low intraday returns. D5–D6 are short-term reversal.
D7–D8 are continuation after a high-volume move.

### Metrics
Per variant and window: candidates, mean gross and net return per candidate (%), 90% interval
from a day-block bootstrap (2,000 resamples of whole days), win rate, and the same for the
top 1 and top 20 as secondary columns. The universe-average intraday return is reported as the
benchmark, because a long-only result can simply be market drift.

### Pass rule
A variant passes if its mean net return per candidate (top 5) is positive with the 90% interval
above zero in **both** selection and validation. Only passing variants are run on the holdout.
With 8 variants, one false pass in a single window is expected about 5% × 8 of the time, which
is why both windows are required.

### Known approximations (checked in the results section)
- The exit is the official close (the volume-weighted price of 15:00–15:30), while the bot
  squares off at 15:10. The gap between the two is measured on the 1m data of the 8 watchlist
  stocks (≤ 2026-07-31).
- The opening price is taken as fillable. The first 1m bar's open is compared with it.
- Intraday shorting in the cash market is assumed available for every EQ stock.

## Results (run once, 2026-11-14)
Data: 1,846 bhavcopy files; 1,422 sessions from 2019-10-01 to 2025-06-30 were loaded. The
archive repeats the previous session's file on holidays, so dates are read from the file
(fixed and tested before the run). Raw output: `data/experiments/daily/20261114_170648_selection.json`.

### Selection, 2019-11-01 .. 2023-12-31 (universe mean intraday return −0.118% per day)
| Id | Side | Cands | Gross % | Net % | Net 90% CI | Win % | Top-1 net % | Top-20 net % |
|---|---|---|---|---|---|---|---|---|
| D1 | long | 5,160 | −0.257 | −0.463 | [−0.573, −0.353] | 40.1 | −0.598 | −0.356 |
| D2 | short | 5,160 | +0.170 | −0.036 | [−0.133, +0.061] | 53.1 | +0.032 | −0.027 |
| D3 | long | 5,160 | −0.051 | −0.257 | [−0.331, −0.177] | 40.1 | −0.368 | −0.265 |
| D4 | short | 5,160 | +0.421 | **+0.215** | [+0.109, +0.318] | 56.0 | +0.581 | +0.052 |
| D5 | long | 5,160 | −0.279 | −0.485 | [−0.585, −0.381] | 38.2 | −0.539 | −0.413 |
| D6 | short | 5,160 | +0.194 | −0.011 | [−0.117, +0.093] | 53.8 | +0.018 | −0.001 |
| D7 | long | 3,759 | −0.192 | −0.398 | [−0.518, −0.275] | 40.2 | −0.558 | −0.412 |
| D8 | short | 1,350 | +0.411 | +0.205 | [−0.004, +0.414] | 55.3 | +0.224 | +0.218 |

### Validation, 2024-01-01 .. 2025-06-30 (universe mean intraday return −0.131% per day)
| Id | Side | Cands | Gross % | Net % | Net 90% CI | Win % | Top-1 net % | Top-20 net % |
|---|---|---|---|---|---|---|---|---|
| D1 | long | 1,850 | −0.203 | −0.409 | [−0.613, −0.217] | 41.9 | −0.484 | −0.358 |
| D2 | short | 1,850 | +0.237 | +0.031 | [−0.125, +0.189] | 53.6 | +0.010 | +0.018 |
| D3 | long | 1,850 | −0.089 | −0.295 | [−0.434, −0.163] | 40.1 | −0.578 | −0.286 |
| D4 | short | 1,850 | +0.256 | +0.050 | [−0.136, +0.236] | 53.2 | +0.249 | +0.036 |
| D5 | long | 1,850 | −0.285 | −0.491 | [−0.670, −0.313] | 38.4 | −0.866 | −0.358 |
| D6 | short | 1,850 | +0.267 | +0.061 | [−0.119, +0.273] | 53.7 | −0.172 | +0.045 |
| D7 | long | 1,261 | −0.246 | −0.451 | [−0.706, −0.221] | 38.9 | −0.243 | −0.635 |
| D8 | short | 547 | +0.288 | +0.082 | [−0.257, +0.421] | 55.9 | +0.548 | −0.186 |

### Verdict
**No variant passes.** D4 passes selection but its validation interval includes zero. The
holdout (2025-07-01 onward) was not run for any variant.

### What the tables show
- The 200 most traded stocks lose about 0.12% from open to close on an average day, in both
  windows. Every long variant loses and every short variant has a positive gross return
  (+0.17% to +0.42%). Most of the short "signal" is this market-wide drift, not stock selection.
- The round-trip cost of about 0.21% absorbs nearly all of it. Net results for shorts sit
  between −0.04% and +0.22%, and only D4 in selection is clearly above zero.

### Approximation check (8 watchlist stocks, 1m data, 2025-10-17 .. 2026-07-31, 1,536 stock-days)
Only OPEN, CLOSE and PREV_CLOSE of these 8 symbols were read from the later bhavcopy files.
No signal or variant was computed on them.

| Leg | Mean (bp) | Median (bp) | t (day means) |
|---|---|---|---|
| First 1m bar's open vs official OPEN | −0.01 | 0.00 | −0.3 |
| Previous close → OPEN (overnight) | +7.4 | +2.4 | +1.7 |
| OPEN → 09:16 | **−7.8** | −4.4 | **−3.3** |
| OPEN → 09:30 | −6.3 | −7.3 | −1.9 |
| 09:30 → 15:10 | −1.7 | −5.3 | −0.4 |
| 15:10 → official CLOSE | −1.0 | −1.5 | −2.2 |
| OPEN → official CLOSE | −8.9 | −9.6 | −1.5 |

- The official OPEN is the price of the first 1m bar, and exiting at 15:10 instead of the
  close costs a short about 1 bp. Both approximations hold.
- The intraday loss is not spread over the day. For these 8 large caps nearly all of it
  happens in the first minute after the opening auction; from 09:30 to 15:10 the mean is
  indistinguishable from zero. This is exploratory (not pre-registered) and covers 8 stocks.

### What this means for the bot
1. Buying at or near the open is the worst entry found so far. The existing no-entry-before-09:30
   rule is supported by the data.
2. The one lead worth a new pre-registered test is the opening-auction premium: sell in the
   09:00–09:07 pre-open session, buy back within minutes. For large caps the 8 bp move is below
   the ~11 bp fees, so it only matters if it is several times larger in the stocks D4 and D8
   select. Testing that needs 1m bars for about 200 stocks, which the daily files cannot give.
3. Open questions before any such test is trusted: whether the broker accepts intraday sell
   orders in the pre-open session, and how rule 4 (a stop on every entry) applies to a trade
   that lasts minutes.
