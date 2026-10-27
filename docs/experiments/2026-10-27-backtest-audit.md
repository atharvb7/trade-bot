# Audit: is the backtester measuring correctly?

Date: 2026-10-27 · Branch: `fix/backtest-audit` · Script: `scripts/exp_audit_rerun.py`
Tests: `tests/test_backtest_audit.py` (14 tests), plus one new test in `tests/test_detectors.py`.

Earlier experiments found no edge after costs. Before doing more strategy research, this audit
checks that the backtester measures correctly. A bug could push results either way.

**Verdict: the backtester is sound.** Five issues were found and fixed. None changes any
earlier conclusion: the biggest moves mean net R per candidate by 0.014R. One assumption that
was kept makes results look about 0.045R *better* on 5m bars (see "Conventions kept").

## 1. Engine, fills, outcome (`engine.py`, `fills.py`, `outcome.py`)

| Check | Result |
|---|---|
| Entry at next-bar open + adverse slippage (buys pay more, sells receive less, both directions) | Correct. Pinned (`test_engine_short_trade_pnl_sign_and_costs`, existing `test_fill_uses_next_bar_open_with_slippage`). |
| Stop and target both inside one bar | Stop is assumed first (the conservative choice). Pinned for longs (existing test) and shorts (new test). Replaying exits on 1m bars changed only 1 of 14,661 5m outcomes and 0 of 1,790 15m outcomes from stop to target, so this assumption costs nothing measurable. |
| Gaps through stop / target | A gap through the stop fills at the open with slippage. A gap through the target fills at the open, which is better than the target (a resting limit order fills there too). Correct. |
| Stop exits slipped; target exits not | Correct: the stop is a stop-market order, the target a limit order. Pinned. |
| Short P&L sign and cost legs | Gross = qty × (entry − exit). Fees = sell leg on the entry value (STT here) + buy leg on the exit value (stamp duty here). Correct. Pinned with hand-computed numbers. |
| Sizing: fill price vs signal price | Qty is sized on the signal close; stop and target stay at their signal-based levels. This matches the R definition (1R = signal-to-stop distance). **Fixed:** a gap at the fill could make qty × fill exceed cash (rule 10). Qty now shrinks at the fill if needed (it is never rounded up). This had no effect on either rerun. |
| Square-off at 15:10 | Correct for 1m and 5m bars (exit at the 15:10 open). **Bug (fixed):** on 15m bars the check `ts.time() >= 15:10` first fires on the 15:15 bar. Positions therefore held through the 15:00–15:15 bar and exited 5 minutes late at the 15:15 open, with stop and target hits counted until 15:15. The fix is a shared rule `must_square_off()`: a bar is held only if it closes by 15:10. 15m positions now exit at the 15:00 open. |
| Overnight carry | **Bug (fixed, latent):** if a day's data ended before the square-off bar, the engine kept the position open overnight and exited it the next morning. A pending order could also fill at the next day's open. Now any open position is closed at that day's last close (with slippage), and unfilled orders are cancelled (`cancelled_eod`). `simulate_outcome`'s matching fallback now also applies slippage. This had no effect on current numbers, because `clean_1m` keeps only complete 375-bar days. |
| Equity, daily loss, losing streak, trades/day | Equity changes only on a close, by net P&L. Start-of-day equity, trades/day and the losing streak reset each day. Pinned (`test_losing_streak_and_trade_count_reset_each_day`). |

## 2. Costs (`costs.py`, `config/costs.yaml`) vs Zerodha equity intraday

Checked against zerodha.com/charges on 2026-10-27:

| Item | Config | Zerodha page | Status |
|---|---|---|---|
| Brokerage | 0.03% or ₹20 per executed order, whichever is lower | same | OK |
| STT | 0.025%, sell side | same | OK |
| NSE transaction charge | 0.00297% | **0.00307%** | Differs (see below) |
| SEBI fee | ₹10/crore (0.0001%) | same | OK |
| Stamp duty | 0.003%, buy side | lower of 0.003% or ₹300/crore (the same rate) | OK |
| GST | 18% on brokerage + exchange + SEBI | same | OK |
| NSE IPFT | not modelled | ₹0.01/crore + GST | Negligible |

- **Exchange charge:** the page now lists 0.00307%. The October 2024 Zerodha bulletin gave
  0.00297%, and I could not find when the rate changed. The config is **not changed** (CLAUDE.md
  says to ask before changing costs). Impact is +0.000236% of notional per round trip:
  about −0.0012R per candidate at 5m (0.20% stop) and −0.0002R at 15m RangeORB. Negligible.
- **Uncertain, not modelled:** contract notes may round STT and stamp duty to the rupee. For
  ₹1,000 positions, the modelled STT (about ₹0.25) could round to ₹0 or ₹1. This barely moves
  R-based results but could matter for the ₹ figures of a ₹1,000 account. Check a real
  contract note before relying on ₹ results.
- The cost code applies each leg correctly for both directions. The brokerage cap is per
  executed order; a partial fill split into several executions is not modelled (fine at this size).

## 3. Per-candidate R (`edge.candidate_r`, `ml.dataset.build_dataset`, `simulate_outcome`)

- Denominator: 1R = |signal close − stop|, the same distance the risk manager sizes on. So
  net R × 1% of equity equals the engine's ₹ P&L. This is consistent.
- Slippage is inside gross R: entry, stop and square-off fills are slipped; target fills are not.
- Timeouts exit at the square-off open with slippage, label 0, and keep their actual P&L.
- **Bug (fixed, negligible):** fees were charged on prices rebuilt from the *signal* close
  instead of the simulated fill and exit. `Outcome` now carries `entry_price`. The dataset and
  the engine's decisions use the true fill and exit, and engine net R now equals candidate R
  exactly (`test_engine_net_r_equals_candidate_r_exactly`). Effect on the reruns: < 0.00001R
  mean (max 0.0014R on a single candidate).

## 4. Look-ahead and timing on N-minute bars

- Convention, verified end to end: bars are indexed by open time. A 15m bar labelled 09:15
  closes at 09:30. Features use bars closed by `available_at`. Detectors decide at bar close
  (`now = ts + bar_minutes`). The fill is at the next bar's open. The 09:30–14:45 window is
  applied to decision time (bar close), identically in the engine and in `build_dataset`.
  Pinned: a signal on the 15m 09:15 bar is allowed and fills at the 09:30 open; the same bars
  at 1m spacing are rejected as before 09:30.
- Prefix invariance on 15m bars (new; 1m and 5m already existed): features computed on data
  cut in the middle of a 15m bar equal the full-history features.
- Nifty 5m/15m trend is joined on close time. A shock to Nifty inside a 15m bar that is still
  open does not move any row that closed earlier (new test).
- `resample_closed` anchors bars at 09:15 and drops a partial final bar. Detectors read only
  bars ≤ i. `RangeORB` requires the signal bar to close after the range closes. No look-ahead found.
- Truncating raw data before 2026-08-01 reproduced the selection-window numbers exactly. This
  confirms independently that no later bar leaks into earlier features.

## 5. Sessions

- `clean_1m` keeps only complete 375-bar days. In this data it drops only the Muhurat session
  (2025-10-21) and a few out-of-session bars on 2026-09-07/09. The data has no other missing
  minutes. Half days would be dropped whole rather than simulated.
- Previous-day levels and gap % use the previous *trading day in the data*, so holidays are
  skipped. Pinned with a Tuesday holiday. The first bar of each day sees only its own closed
  bar plus earlier days; the opening range and VWAP reset daily.
- **Bug (fixed, detector logic):** on 5m/15m bars, `VWAPReclaim`'s 5-bar lookback for the
  first eligible bars reached into the previous session, so yesterday's stretch below
  yesterday's VWAP could trigger a reclaim today. It now looks at today's bars only. 1m bars
  were unaffected. This removed 39 of 14,700 5m candidates.
- Kept by design: EMA, RSI, ATR, realised vol, volume average and the 30-minute relative
  strength run across the overnight gap. This is causal, but the first bars' ATR (and
  therefore stop size) includes the overnight gap.
- **Data-quality finding (holdout only):** on all 48 days from 2026-08-03 onwards, every
  symbol's 15:15–15:29 bars are flat with zero volume. No days before 2026-08-01 are affected.
  This does not touch entries or exits (square-off is 15:10), but it does mean the
  "previous close" feature is the ~15:15 price on those days. The quality report should flag it.

## Conventions kept (not bugs, but they bias results)

| Convention | Direction | Size |
|---|---|---|
| Target fills on a touch (`high >= target`) | Makes results look **better** | 5m: requiring one tick (₹0.05) *through* the target lowers mean net R from −1.008 to −1.053 (−0.045R) and win rate from 37.7% to 35.8%. 15m RangeORB: no change. |
| Exits checked on N-minute bars | Either way | Replaying exits on 1m bars (exact 15:10 square-off, stop-vs-target resolved minute by minute): 5m −1.0079 vs −1.0080; 15m RangeORB −0.1684 vs −0.1773 now, and −0.1634 under the old 15:15 rule. The 1m replay is the most faithful; the new 15:00 exit is ~0.009R pessimistic, the old 15:15 exit was ~0.005R optimistic. |
| Stop assumed first inside a bar | Makes results look **worse** | Negligible (see section 1). |

## Before / after (selection window 2025-10-17 .. 2026-07-31 only; no data ≥ 2026-08-01 loaded)

Mean net R per candidate over every tradeable candidate (`build_dataset`), with the 90%
day-block bootstrap interval. "Engine" is `candidate_r` on the backtester's decisions, as in the
timeframe experiment. "Before" reproduces the published numbers exactly (14,475 / −1.01 / 172
trades; 1,790 / −0.16 / 207 trades).

| Setup | | Candidates | Gross R | Fee R | **Net R** | 90% CI | Engine cand. net R | Trades | Net ₹ | Max DD % |
|---|---|---|---|---|---|---|---|---|---|---|
| 5m, 3 detectors, atr 1.0, rr 1.5 | before | 14,700 | −0.443 | 0.564 | **−1.0066** | [−1.050, −0.961] | −1.0143 | 172 | −88.3 | 16.8 |
| | after | 14,661 | −0.444 | 0.564 | **−1.0080** | [−1.051, −0.962] | −1.0158 | 170 | −86.4 | 16.7 |
| | exits on 1m | 14,661 | −0.444 | 0.564 | −1.0079 | [−1.051, −0.962] | | | | |
| 15m RangeORB(60), rr 3 | before | 1,790 | −0.080 | 0.084 | **−0.1634** | [−0.196, −0.131] | −0.1662 | 207 | −168.4 | 18.1 |
| | after | 1,790 | −0.094 | 0.084 | **−0.1773** | [−0.206, −0.150] | −0.1788 | 207 | −183.5 | 20.2 |
| | exits on 1m | 1,790 | −0.085 | 0.084 | −0.1684 | [−0.200, −0.137] | | | | |

Where the changes come from (an intermediate-commit run and a fee-formula recomputation
separate the fixes):
- 5m: −0.0014R, all from the VWAP-reclaim lookback fix. The fee-price fix contributes < 0.00001R.
- 15m: −0.0139R, all from the square-off timing fix. The 24 stops hit between 15:00 and 15:15
  are now 15:00 timeouts. The 1m replay puts 18 of those stops before 15:10. The fee-price fix
  contributes 0.0000R.
- Overnight-carry and cash-cap fixes: no effect on these runs.

## Conclusion

The backtester's answers are right to within about ±0.05R per candidate. The largest remaining
bias is the touch-fill target assumption, and it flatters results. The earlier conclusions stand:
5m setups lose about 1R per candidate after costs, and 15m RangeORB loses about 0.17R. Every
interval is well below zero.

Recommended follow-ups, not done here:
1. Evaluate exits for N-minute strategies on 1m bars in the engine. The live runner will see
   1m bars and exit at exactly 15:10, so this keeps one code path.
2. Confirm the NSE transaction charge (0.00307% vs 0.00297%) and STT/stamp rounding from a
   real contract note, then update `config/costs.yaml` with approval.
3. Make the data-quality report flag runs of zero-volume flat bars (the 15:15–15:29 tails since August).
4. Optionally require a one-tick trade-through for target fills (a more conservative fill model).
