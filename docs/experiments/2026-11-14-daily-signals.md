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
