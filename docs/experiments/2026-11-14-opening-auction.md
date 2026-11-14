# Experiment: fading the opening auction (hold for 5 minutes)

Date: 2026-11-14 · Branch: `exp/opening-auction` (on top of `exp/daily-signals`)
Script: `scripts/exp_opening_auction.py` · Data script: `scripts/download_open_bars.py`

## Why
`2026-11-14-daily-signals.md` found that the 200 most traded stocks fall about 0.12% from open
to close, and that for 8 large caps nearly all of the fall happens in the first minute after
the opening auction. That second observation was exploratory. This experiment tests it
directly on about 200 stocks: enter at the auction price, exit five minutes later.

## Pre-registration (committed before any 1m bar outside the 8 watchlist stocks is downloaded)

### Data and windows
- Fyers serves 1m bars for the last 12 months only (checked 2026-11-14: 2025-11-17 works,
  2025-11-10 does not). So the windows are short:
  selection 2025-12-15 .. 2026-05-31, validation 2026-06-01 .. 2026-08-31,
  holdout 2026-09-01 onward.
- 1m bars are downloaded only up to 2026-08-31 and only 09:15–09:44 is kept
  (`data/open_bars/`, separate from `data/parquet/`). Holdout bars are downloaded and read
  only if a variant passes.
- Daily signals and the universe come from the bhavcopy files, as in the daily experiment
  (top 200 by 20-day median turnover known before the open, PREV_CLOSE ≥ ₹20,
  |overnight return| ≤ 20%). Signals need 20 sessions of history, hence the 2025-12-15 start.
- This uses bhavcopy rows after 2025-06-30, which were the daily experiment's unused holdout.
  That holdout is retired; no daily variant qualified for it.

### Trade rules (all variants)
- Entry: the official OPEN (an order in the 09:00–09:07 pre-open session fills at this price).
- Exit: the open of the 09:20 one-minute bar. No stop, no target.
- Costs: `config/costs.yaml` fees on both legs plus 0.05% slippage per side, about 0.21% in
  total. Unchanged, even though the auction fill has no spread.
- A candidate is dropped if its 09:15 or 09:20 bar is missing, or if the first bar's open
  differs from the official OPEN by more than 0.1%. Dropped counts are reported.
- Up to 5 candidates per day and variant (ties: alphabetical).

### Variants (4; no others will be counted)
| Id | Signal | Pick | Side |
|---|---|---|---|
| O1 | sum of overnight returns, days t−20 .. t−1 (D4's signal) | highest 5 | short |
| O2 | day t−1 turnover ≥ 3 × its 20-day median and return ≤ −3% (D8's signal) | lowest 5 | short |
| O3 | today's gap OPEN / PREV_CLOSE − 1 ≥ +1% | highest 5 | short |
| O4 | today's gap ≤ −1% | lowest 5 | long |

O3 and O4 use the opening price itself. Live, the bot would have to act on the indicative
price shown during the pre-open session, which can differ from the final open. Their results
are therefore an upper bound and would need a separate check before being traded.

### Metrics
Per variant and window: candidates, dropped, mean gross and net return per candidate with a
day-block bootstrap 90% interval, win rate. Reported for information only: exits at the 09:16
and 09:30 bar opens, and the universe-average OPEN → 09:20 return (the benchmark).

### Pass rule
Mean net return per candidate at the 09:20 exit is positive with the 90% interval above zero
in **both** selection and validation. Only passing variants are run on the holdout, once.
