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
