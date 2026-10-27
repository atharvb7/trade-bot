# Experiment: execution realism (slippage, stop fills, passive limit entries)

Date: 2026-10-27 · Branch: `exp/execution-realism` · Script: `scripts/exp_execution.py`
Code: `src/bot/backtest/liquidity.py` (spread proxies), `fills.py` / `outcome.py` / `engine.py`
(limit-entry and target-through options, default off), `ExecutionCfg` in `src/bot/config.py`.
Data: Fyers 1-minute bars, 8 stocks, 2025-10-17 .. 2026-07-31 (193 sessions). Each series is
cut at 2026-07-31 right after loading. **The 2026-08-01+ holdout was not loaded or looked at.**
Raw output: `data/experiments/execution/20261027_220818_execution.json` (gitignored).

## Question
The model fills entries at the next bar's open + 0.05% and exits stops at the stop − 0.05% (per
side). Is 0.05% realistic for 1–10 share orders in these stocks? Do stops fill worse than that?
Would a passive limit entry help, or does adverse selection cancel the gain?

## Protocol (fixed before running)
1. Spread proxies per symbol and time-of-day bucket, with 90% day-block bootstrap intervals.
2. Stop fills. Take every stop exit of the two setups. Find the 1-minute bar in which the stop
   was first touched. Measure how far that minute's extreme and close went past the stop, and
   do the same for the detector bar itself.
3. Latency for market entries: the signed move over the first minute after the decision. A
   positive value means the price moved against a market entry.
4. Evidence-based slippage per symbol, (b): the larger of the entry and stop estimates, rounded
   **up** to 0.005%.
   - Entry = ½ × the largest of the three spread estimates in any 09:30–15:30 bucket, plus
     the drift over 2 s if it is adverse. 2 s covers features, ML, the 800 ms Jev timeout and
     order placement.
   - Stop = the same half-spread plus the mean amount by which the trigger minute closed past
     the stop.

   Steps 2–3 do not depend on the slippage value, so (b) is not tuned on P&L.
5. Two setups on the selection window: 5m, three detectors, atr1.0, rr1.5; and 15m RangeORB(60),
   rr3. Each runs under (a) 0.05%/side, (b), (c) 2×(b), (d) a passive limit and (e) (b) with
   targets that must trade through.
   - (d): a passive limit at the signal price, at 0 or 1 tick away from the market, resting for
     15 minutes (3 bars on 5m, 1 bar on 15m). Exits use (b).
   - Results are mean net R per candidate with a day-block bootstrap 90% CI. Missed limit
     orders count as 0 R. The denominator is always all candidates.

## 1. Spread estimates (full spread, basis points of price)
NSE tick sizes, checked in the data: ₹0.01 below ₹250 (TATASTEEL, WIPRO, and parts of ONGC and
ETERNAL) and ₹0.05 from ₹250 to ₹1,000. So the tick is 0.5–1.8 bp, not "≈ 2 bp everywhere".

| Symbol | Tick | Roll 09:30–15:30 | CS 09:30–15:30 | AR 09:30–15:30 | CS 09:15–09:30 | Half-spread used | (b) %/side |
|---|---|---|---|---|---|---|---|
| NTPC | 1.40 | 2.4–3.5 | 2.5–2.9 | 2.8–3.4 | 3.9 | 1.76 | 0.025 |
| ITC | 1.54 | 2.5–3.1 | 2.6–2.9 | 2.6–3.1 | 3.6 | 1.57 | 0.020 |
| ONGC | 1.21 | 0.0–3.5 | 2.5–3.0 | 1.8–3.2 | 5.1 | 1.76 | 0.025 |
| POWERGRID | 1.75 | 3.0–4.1 | 2.3–2.6 | 2.6–3.1 | 4.0 | 2.03 | 0.030 |
| TATASTEEL | 0.52 | 0.0–2.4 | 2.4–3.3 | 1.9–2.4 | 5.6 | 1.64 | 0.020 |
| COALINDIA | 1.18 | 0.0–2.9 | 2.7–3.1 | 1.7–2.8 | 4.8 | 1.55 | 0.025 |
| WIPRO | 0.73 | 2.1–3.0 | 2.2–3.1 | 2.2–2.5 | 5.2 | 1.55 | 0.020 |
| ETERNAL | 1.41 | 1.2–3.9 | 2.8–4.2 | 1.2–2.7 | 6.2 | 2.09 | 0.035 |

The ranges in the table are min–max across the five trading buckets. The per-bucket bootstrap
intervals are in the JSON and are tight after 09:30: CS ±0.1 bp, AR ±0.2–0.4 bp and Roll
±0.5–1 bp. Roll and AR are often undefined (reported as 0) before 10:00.

Median across symbols, by time of day (bp):

| Bucket | Roll | CS (clipped) | CS (raw) | AR | Tick |
|---|---|---|---|---|---|
| 09:15–09:30 | 2.9 | **5.0** | −0.4 | 2.2 | 1.3 |
| 09:30–10:00 | 2.8 | 3.1 | 0.3 | 2.4 | 1.3 |
| 10:00–11:00 | 2.2 | 2.6 | 0.8 | 2.4 | 1.3 |
| 11:00–13:00 | 2.5 | 2.6 | 1.2 | 2.7 | 1.3 |
| 13:00–14:30 | 2.8 | 2.7 | 1.5 | 2.9 | 1.3 |
| 14:30–15:30 | 3.0 | 2.7 | 1.2 | 2.9 | 1.3 |

**Reading.** After 09:30 the full spread proxy is about 2–3.5 bp, so the half-spread is about
1–2 bp (0.01–0.02%). The first 15 minutes are about twice as wide on CS. No entries are allowed
before 09:30, so the opening premium does not affect the bot.

On synthetic bid/ask-bounce data (`tests/test_execution.py`), Roll and AR recover a known spread
within 15%, and CS within 30% (biased low).

## 2. Stop fills
Stop exits, measured in bp past the stop (positive = worse for us). 8,762 stops on 5m and 129 on
15m:

| Measure | 5m mean | 5m p50 | 5m p90 | 5m p99 | 15m mean | 15m p50 | 15m p90 |
|---|---|---|---|---|---|---|---|
| Detector bar's extreme | 8.3 | 5.2 | 18.8 | 48.2 | 20.8 | 13.1 | 50.1 |
| Detector bar's close | 0.2 | −0.4 | 12.2 | 38.0 | 3.6 | −1.4 | 32.8 |
| **Trigger minute's extreme** | **4.7** | 2.9 | 10.9 | 26.9 | **6.8** | 4.4 | 16.3 |
| **Trigger minute's close** | **0.4** | 0.0 | 7.6 | 21.6 | −0.3 | 0.0 | 10.9 |

- 2.5% (5m) and 0.8% (15m) of stops were gapped at the 1-minute open, with a median of
  1.1 bp past the stop. Large gaps are rare.
- A stop-market order is triggered by the exchange on the last traded price and fills within
  that minute. The fill therefore lies between the minute's extreme and the stop.
  - The minute's close (about 30 s after the trigger on average) is at the stop on average.
  - The mean extreme is 4.7–6.8 bp. That is the worst trade printed in that minute.
- A realistic stop fill is the stop − (half-spread + ≈0.5 bp) ≈ 2–3 bp. A fill at the worst
  trade printed in the trigger minute averages 4.7–6.8 bp.
- **0.05% for stop exits is conservative, not optimistic.** On average it equals filling at
  the worst trade of the trigger minute. It is optimistic only in the tail: about 12% of 5m
  stops had a minute extreme > 10 bp.
- The detector bar's own extreme (8–21 bp) is a poor bound. It includes moves made long after
  the stop had already filled.

## 3. Latency for market entries
The signed move in the first minute after the decision is +0.009 bp/min (90% CI [−0.08, +0.10]
on 5m, n = 14,700). The price does not drift against the entry after the signal. A 2-second
latency therefore costs about 0. The gap from the signal close to the next open is already in
the model, because entries fill at the next open.

## 4. Re-evaluation (selection window 2025-10-17 .. 2026-07-31)
Mean net R per candidate (fees included), with a 90% day-bootstrap CI.

**5m, 3 detectors, atr1.0, rr1.5** (14,700 candidates, median stop 0.20% of price, breakeven win 40%)

| Scenario | Entered | Win % | Gross R | Net R | 90% CI |
|---|---|---|---|---|---|
| (a) 0.05%/side (costs.yaml) | 14,700 | 37.7 | −0.443 | **−1.007** | [−1.050, −0.961] |
| (b) per-symbol estimate (0.020–0.035%) | 14,700 | 37.7 | −0.222 | **−0.786** | [−0.824, −0.746] |
| (c) 2 × (b) | 14,700 | 37.7 | −0.434 | −0.997 | [−1.041, −0.952] |
| (d) limit at signal, 15 min | 14,116 | 35.5 | −0.151 | −0.692 | [−0.728, −0.656] |
| (d) limit 1 tick passive, 15 min | 13,568 | 33.9 | −0.126 | −0.644 | [−0.678, −0.609] |
| (e) (b) + target must trade through | 14,700 | 36.4 | −0.251 | −0.815 | [−0.854, −0.774] |

**15m RangeORB(60), rr3** (1,790 candidates, median stop 1.38%, breakeven win 25%)

| Scenario | Entered | Win % | Gross R | Net R | 90% CI |
|---|---|---|---|---|---|
| (a) 0.05%/side (costs.yaml) | 1,790 | 0.1 | −0.080 | **−0.163** | [−0.196, −0.131] |
| (b) per-symbol estimate | 1,790 | 0.1 | −0.040 | **−0.123** | [−0.156, −0.091] |
| (c) 2 × (b) | 1,790 | 0.1 | −0.078 | −0.162 | [−0.195, −0.130] |
| (d) limit at signal, 15 min | 1,705 | 0.1 | −0.029 | −0.109 | [−0.140, −0.078] |
| (d) limit 1 tick passive, 15 min | 1,645 | 0.1 | −0.023 | −0.100 | [−0.130, −0.070] |
| (e) (b) + target must trade through | 1,790 | 0.1 | −0.040 | −0.123 | [−0.156, −0.091] |

For both setups the "win %" column counts targets only, as before. Almost every 15m trade
ends at the 15:10 square-off, which is why its win rate is ~0.1%.

In the event-driven backtest (5m, spec risk rules, 0.05% exits), the default path reproduces
the timeframe experiment exactly: 172 trades, net −₹88.3, max DD 16.8%. With limit entries the
backtest made 169 trades, net −₹48.7, max DD 14.9%.

### Limit entries: fill rate and adverse selection
| | 5m, at signal | 5m, 1 tick | 15m, at signal | 15m, 1 tick |
|---|---|---|---|---|
| Fill rate | 96.0% | 92.3% | 95.3% | 91.9% |
| Net R of the **filled** ones if entered at market (b) | −0.830 | −0.866 | −0.131 | −0.135 |
| Net R of the **missed** ones if entered at market (b) | **+0.278** | +0.180 | +0.036 | +0.009 |
| Target win % filled / missed | 35.9 / **82.2** | 34.3 / 78.5 | 0.1 / 0.0 | 0.1 / 0.0 |
| Filled − missed, 90% CI | [−1.18, −1.03] | [−1.11, −0.98] | [−0.27, −0.07] | [−0.22, −0.07] |
| Net R per filled limit trade | −0.721 | −0.698 | −0.114 | −0.108 |

- **Adverse selection is strong and significant.** The 4–8% of signals that never trade back
  through the limit are the ones that run straight to target: 82% hit target vs 36% for the
  filled ones on 5m. Filled trades are clearly worse than missed ones.
- The limit still comes out ahead per candidate: +0.09 to +0.14R on 5m and +0.01 to +0.02R on
  15m versus market entry at (b).
  - It saves the half-spread and gets a slightly better price on every fill.
  - That gain exceeds the winners it loses, because the misses are few.
- **No scenario makes either setup positive.** Every 90% CI is below zero.

### Target fills
The current model fills a target when the bar merely touches it. On 5m, 812 of 5,546 target
exits (14.6%) only touched the level. Requiring a trade-through costs 0.03R per candidate. A
small resting order at a touched level may or may not fill, so the truth is between (b) and (e).

## Limitations
- **No quote data.** The spread proxies come from 1-minute trade OHLC. They assume a constant
  spread within a bucket and attribute all negative return autocorrelation to bid-ask bounce.
  - Short-term reversal from other traders' price impact also produces negative
    autocorrelation and inflates the proxies.
  - The proxies come out around 2–3 bp for every stock, even TATASTEEL and WIPRO, whose tick is
    0.5–0.7 bp and whose quoted spread is probably 1–2 ticks. So they are more likely upper
    bounds for a 1–10 share order than underestimates.
  - CS with negatives clipped is biased up; unclipped CS is 0.3–1.5 bp. Taking the max of three
    estimators adds more conservatism.
- Stop fills assume a stop order that turns marketable as soon as it triggers, at the exchange
  (no client-side latency). A stop-limit order with too tight a buffer can stay unfilled in a
  fast market, which is a different risk. Whether Zerodha supports SL-M for intraday equity
  needs checking against current broker docs before Phase 8.
- Limit-entry fills:
  - A limit at the signal price can be marketable at once if the close printed on the ask.
    The simulation counts that as a miss unless a later trade goes through, so the fill rate
    is pessimistic, and it is pessimistic exactly on the winners.
  - Queue position is ignored beyond the trade-through rule.
  - On the fill bar, the stop is allowed and the target is not (pessimistic).
- One period (≈9.5 months), 8 stocks. The proxies are averages, and a news day can be much
  worse than 0.05%.
- (b) uses the same window it is evaluated on. That is acceptable because it is a
  microstructure estimate, not fitted to strategy P&L, but it is still in-sample.

## Recommendation
1. **Do not change `slippage_pct` in costs.yaml now. Keep 0.05%/side.**
   - The evidence says it is conservative: about 2–3× the half-spread for entries, about 2× a
     realistic stop fill, and equal to filling at the worst trade of the trigger minute on
     stops. 2×(b) ≈ (a) in both setups.
   - Lowering it would only flatter results that are negative under every assumption. And the
     evidence is proxy-only.
   - The defensible floor for a future cut is a uniform **0.035%**, the largest per-symbol
     estimate (ETERNAL). Cut only after measured fills confirm the proxies. Do not use
     per-symbol values below that.
2. Measure real spreads before Phase 8. In paper mode, log the best bid/ask (Kite full-depth
   ticks) at every decision and at every stop trigger. Then compare effective spreads with
   the 1–2 bp half-spread estimated here, and revisit this setting.
3. Consider `execution.target_fill: through` as the backtest default for go-live evaluation.
   Touch fills are mildly optimistic (−0.03R per candidate on 5m). It is not changed here; the
   default stays `touch`, so existing results are unchanged.
4. Limit entries are a valid option (`execution.entry_order: limit`) and are mildly better
   despite strong adverse selection. They do not change the conclusion: neither setup has an
   edge after realistic costs. Do not adopt them to rescue a strategy.

**No config files were changed.** `ExecutionCfg` defaults reproduce the previous fill model
exactly.
