# Forward paper test: news gap fade

Date: 2026-11-14 · Branch: `phase-7/paper-runner` · Runner: `src/bot/runner.py`,
`scripts/run_paper.py` · Strategy: `src/bot/strategy/news_gap.py`

## Why a forward test
`2026-11-14-announcement-events.md`: shorting a stock that gaps up 2% or more after an
out-of-hours order win or results passed selection and validation but was not confirmed on
the holdout. No unused history is left, so the only clean evidence is what happens from now on.

## What the runner does each session (fixed for the whole test)
| Time | Stage |
|---|---|
| 09:00 | Universe: 500 most traded stocks (20-session median turnover, close ≥ ₹20). Announcements since the last close, classified by the registered text rules. |
| 09:16 | Opening quotes for the event stocks. Candidate = gap (open / previous close − 1) ≥ +2%. One DecisionRecord per candidate. |
| 09:30 | Candidates in order of gap size: short, entry at the 09:30 bar's open, stop at the morning high but at least 1% above entry, target at the previous close. Gate (`rules_only`), then the risk manager with `config/risk.yaml` unchanged. |
| to 15:10 | Stop order placed right after the fill. Square-off at the 15:10 bar's open. Kill switch: `config/KILL` file or `/kill` on Telegram. |
| 15:31 | For **every** candidate, traded or not: net return of a short from the open and from 09:30 to 15:10, and the worst move against it. Stored in `DecisionRecord.features["outcome"]`. |

Fills use the paper broker: next-bar open, 0.05% slippage per side, fees from
`config/costs.yaml`.

## Differences from the backtest (known before the first paper day)
- The backtest entered at the official open; the runner enters at 09:30, because
  `no_entry_before` is 09:30 and an order in the pre-open session is not verified with the
  broker. Both entries are recorded for every candidate, so the cost of waiting is measured.
- The backtest had no stop. The runner always has one (rule 4).
- With ₹1,000 and one position at a time the account takes at most one candidate a day and
  only stocks priced under about ₹990. The verdict therefore rests on candidate-level
  outcomes, not on the account's few trades.

## Pre-registered verdict
- Primary metric: mean `short_from_entry_time_net_pct` over all candidates.
- Evaluate once, at whichever comes first: 100 candidates or 12 weeks from the first session.
- **Go to the next step** (a 1-share live test, Phase 8) only if the mean is positive with the
  day-block bootstrap 90% interval above zero, the account's paper drawdown stays under 10%,
  and no candidate closed more than 10% against the short.
- **Otherwise drop the strategy.** It is not re-tuned on the paper data.
- No setting in `config/settings.yaml: news_gap`, `risk.yaml` or `costs.yaml` changes during
  the test. A change restarts the count from zero under a new `run_id`.

## Operational notes
- The Fyers access token expires daily: run `scripts/fyers_login.py` before 09:00 each
  trading day. Without it the runner fails closed (no trades) and sends one alert.
- 1m bars come from polling Fyers history (50 requests per minute on the Standard plan), not
  a websocket. That is enough for one open position; a tick feed is a Phase 8 item.
- A paper position exists only in memory. If the process restarts while one is open, the
  trade is journalled as `orphaned_restart` with no P&L and an error is logged.
- `deploy/trade-bot-paper.service` is a systemd template for the VPS; it is not installed.
