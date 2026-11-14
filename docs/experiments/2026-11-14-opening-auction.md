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

## Results (run once, 2026-11-14)
1m bars were downloaded for 356 of the 362 universe stocks (Fyers does not know HEG, HFCL,
LTIM, MOREPENLAB, SETFGOLD and STLTECH under those names). Coverage is 96–97% of universe
stock-days. Raw output: `data/experiments/opening_auction/20261114_180017_selection.json`.
The last two columns are the net return at the 09:16 and 09:30 exits, for information only.

### Selection, 2025-12-15 .. 2026-05-31 (universe mean OPEN → 09:20: −0.053%)
| Id | Side | Cands | Dropped | Gross % | Net % | Net 90% CI | Win % | 09:16 | 09:30 |
|---|---|---|---|---|---|---|---|---|---|
| O1 | short | 471 | 79 | +0.113 | −0.093 | [−0.338, +0.171] | 43.7 | +0.042 | −0.092 |
| O2 | short | 164 | 12 | +0.391 | +0.186 | [−0.377, +0.954] | 47.6 | +0.227 | +0.492 |
| O3 | short | 407 | 61 | +0.243 | +0.037 | [−0.164, +0.225] | 48.9 | +0.055 | +0.061 |
| O4 | long | 362 | 19 | +0.037 | −0.169 | [−0.402, +0.078] | 48.3 | −0.237 | −0.122 |

### Validation, 2026-06-01 .. 2026-08-31 (universe mean OPEN → 09:20: −0.028%)
| Id | Side | Cands | Dropped | Gross % | Net % | Net 90% CI | Win % | 09:16 | 09:30 |
|---|---|---|---|---|---|---|---|---|---|
| O1 | short | 297 | 28 | +0.039 | −0.167 | [−0.325, −0.014] | 40.7 | −0.178 | −0.056 |
| O2 | short | 79 | 3 | +0.097 | −0.109 | [−0.373, +0.154] | 44.3 | −0.094 | −0.096 |
| O3 | short | 265 | 15 | −0.025 | −0.231 | [−0.384, −0.075] | 43.4 | −0.188 | −0.282 |
| O4 | long | 226 | 17 | +0.093 | −0.114 | [−0.309, +0.067] | 46.0 | −0.115 | −0.138 |

### Verdict
**No variant passes**, in either window. The holdout bars (2026-09-01 onward) were not
downloaded.

- The drop after the opening auction is real but small: 3–5 bp on average across 200 stocks
  in the first five minutes, against a round-trip cost of about 21 bp.
- It is not much larger in the stocks the signals pick. The best gross figure that holds in
  both windows is about +0.1%, half the cost.
- So the lead from the daily experiment does not become a trade. It remains useful as a rule
  for entries: a buy in the first minutes pays a small premium on average.
