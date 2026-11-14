# Experiment: company announcements (order wins, results), traded open to close

Date: 2026-11-14 · Branch: `exp/opening-auction` · Script: `scripts/exp_announcement_events.py`
Data: NSE corporate announcements for all companies (`scripts/download_announcements.py`,
`data/raw/announcements/`), plus the bhavcopy files used by the daily experiment.

## Why
Every earlier experiment used price and volume only. Announcements are different information:
contract wins, results, deals. The exchange publishes each one with a timestamp, so the bot
could know about it before the next open. The question is whether the stock still moves in a
predictable direction *after* the open, once the news is already in the opening price.

## Pre-registration (committed before any return is computed for an event)

### Data and windows
- Announcements 2019-10 .. 2025-06 only; later months are not downloaded.
- Selection 2019-11-01 .. 2023-12-31, validation 2024-01-01 .. 2025-06-30, holdout 2025-07-01
  onward (the announcement data for it does not exist on disk).
- Universe: top **500** stocks by 20-day median turnover known before the open (events matter
  more outside the largest names), PREV_CLOSE ≥ ₹20, |overnight return| ≤ 20%.

### Timing
An announcement belongs to trading day t if its broadcast time is after 15:30 of the previous
session and before 09:00 of day t (weekends and holidays included). Announcements made between
09:00 and 15:30 of a session are ignored here: trading them needs 1m bars.

### Event sets (text rules fixed here, case-insensitive)
- **Order win**: the category contains `order` or `contract`, or the summary text matches
  `bagging|receipt of (an? )?(order|contract|letter of)|letter of (award|acceptance|intent)|`
  `(awarded|secured|received|bags|bagged|wins|won)\b.{0,40}\b(order|contract)|order win`.
- **Results**: the category is `Financial Result Updates`, or it is `Outcome of Board Meeting`
  and the text contains `financial result`.

| Set | Events on day t |
|---|---|
| S1 | order win |
| S2 | order win and gap (OPEN / PREV_CLOSE − 1) ≥ +2% |
| S3 | results and gap ≥ +2% |
| S4 | results and gap ≤ −2% |

Every event in a set is a candidate (one per stock per day, no daily cap).

### Trade rules
Entry at the official OPEN of day t, exit at the official CLOSE, no stop or target. Costs as in
the daily experiment (fees both legs + 0.05% slippage per side, about 0.21%). Each set is
evaluated long and short, giving 8 tests.

### Metrics and pass rule
Candidates, mean gross and net return per candidate, day-block bootstrap 90% interval, win
rate, and the universe-average intraday return on the same days as a benchmark. A set and side
passes if the mean net return is positive with the 90% interval above zero in **both**
selection and validation. Only a passing test is taken to the holdout.

### Known limits
- S2–S4 use the opening price itself (same caveat as O3/O4 in the opening-auction test).
- The text rule will miss some order wins and catch some unrelated filings. It is fixed here
  so it cannot be tuned on returns.
- The top-500 universe includes stocks where intraday shorting may not be available.

## Selection and validation results (run once, 2026-11-14)
47,566 announcements were classified (41,925 results, 5,641 order wins).
Raw output: `data/experiments/events/20261114_173426_selection.json`.

### Selection, 2019-11-01 .. 2023-12-31
| Set | Side | Cands | Days | Gross % | Net % | Net 90% CI | Win % | Benchmark % |
|---|---|---|---|---|---|---|---|---|
| S1 | long | 403 | 314 | −0.587 | −0.793 | [−1.049, −0.540] | 31.5 | −0.162 |
| S1 | short | 403 | 314 | +0.587 | +0.382 | [+0.129, +0.639] | 61.0 | −0.162 |
| S2 | long | 132 | 122 | −1.252 | −1.457 | [−1.953, −0.954] | 23.5 | −0.078 |
| S2 | short | 132 | 122 | +1.252 | **+1.047** | [+0.543, +1.544] | 70.5 | −0.078 |
| S3 | long | 1,140 | 390 | −0.726 | −0.932 | [−1.173, −0.695] | 33.4 | −0.237 |
| S3 | short | 1,140 | 390 | +0.726 | **+0.521** | [+0.284, +0.763] | 60.0 | −0.237 |
| S4 | long | 883 | 361 | −0.172 | −0.378 | [−0.639, −0.133] | 41.6 | −0.257 |
| S4 | short | 883 | 361 | +0.172 | −0.034 | [−0.280, +0.227] | 52.2 | −0.257 |

### Validation, 2024-01-01 .. 2025-06-30
| Set | Side | Cands | Days | Gross % | Net % | Net 90% CI | Win % | Benchmark % |
|---|---|---|---|---|---|---|---|---|
| S1 | long | 1,047 | 284 | −0.293 | −0.499 | [−0.679, −0.317] | 38.0 | −0.220 |
| S1 | short | 1,047 | 284 | +0.293 | +0.087 | [−0.094, +0.268] | 53.0 | −0.220 |
| S2 | long | 171 | 120 | −0.788 | −0.993 | [−1.423, −0.594] | 32.2 | −0.101 |
| S2 | short | 171 | 120 | +0.788 | **+0.583** | [+0.183, +1.013] | 62.0 | −0.101 |
| S3 | long | 448 | 135 | −0.983 | −1.188 | [−1.561, −0.806] | 34.6 | −0.304 |
| S3 | short | 448 | 135 | +0.983 | **+0.778** | [+0.395, +1.152] | 59.8 | −0.304 |
| S4 | long | 379 | 125 | +0.435 | +0.228 | [−0.320, +0.765] | 49.1 | −0.372 |
| S4 | short | 379 | 125 | −0.435 | −0.641 | [−1.179, −0.092] | 43.3 | −0.372 |

**S2 short and S3 short pass.** A stock that gaps up 2% or more on an order win or on results
tends to fall from its opening price to the close. S1 short passes selection only; S4 fails.

## Holdout protocol (committed before the holdout data is downloaded)
- Window 2025-07-01 .. 2026-11-13, run once, for S2 short and S3 short only.
- A test is confirmed if its mean net return per candidate is positive with the 90% interval
  above zero.
- Diagnostics reported with it, because a 60–70% win rate needs explaining before it is
  believed (none of these changes the verdict):
  1. Share of candidates whose close is within 0.1% of the day's high, and their mean return.
     A short in a stock locked at its upper price band cannot be covered, and the penalty for
     failing to deliver is not in the cost model.
  2. Results restricted to the top 200 by turnover, where intraday shorting is routinely
     available.
  3. Net return with the worst 5% of candidates' losses doubled (tail stress).
  4. Net return with costs doubled.
