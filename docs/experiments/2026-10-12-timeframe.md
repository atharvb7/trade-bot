# Experiment: 1-minute vs 5-minute detector bars

Date: 2026-10-12 · Branch: `exp/5m-timeframe` · Script: `scripts/exp_timeframe.py`
Data: Fyers 1m, 8 stocks, 2025-10-17 .. 2026-10-09 (241 clean days).

## Protocol (fixed before running)
- Selection window 2025-10-17 .. 2026-07-31: run 5 variants, pick one by net expectancy
  per trade (min 30 trades) under the spec risk rules, min-edge 3x unchanged.
- Holdout 2026-08-01 .. 2026-10-09: run the chosen variant and the 1m baseline once.
- Costs: config/costs.yaml, slippage 0.05% per side.

## Results — selection window
| Variant | Trades | Win % | ₹/trade | Net ₹ | Max DD % | Candidates | Cand. win % | Breakeven % | Net R / cand. |
|---|---|---|---|---|---|---|---|---|---|
| 1m atr1.0 rr1.5 (spec) | 10 | 30.0 | −2.96 | −29.6 | 3.0 | 58,165 | 36.2 | 40.0 | −2.44 |
| **5m atr1.0 rr1.5** | 172 | 48.8 | −0.51 | −88.3 | 16.8 | 14,475 | 37.7 | 40.0 | −1.01 |
| 5m atr1.0 rr2.0 | 328 | 33.8 | −1.15 | −376.9 | 38.3 | 14,199 | 30.0 | 33.3 | −1.04 |
| 5m atr1.5 rr1.5 | 360 | 38.6 | −1.20 | −430.3 | 43.3 | 13,904 | 32.7 | 40.0 | −0.70 |
| 5m atr1.5 rr2.0 | 419 | 34.4 | −1.04 | −435.4 | 43.9 | 13,545 | 23.5 | 33.3 | −0.71 |

Chosen: 5m atr1.0 rr1.5 (least negative).

## Results — holdout (run once)
| Variant | Trades | Win % | Net ₹ | Candidates | Cand. win % | Net R / cand. |
|---|---|---|---|---|---|---|
| 1m spec baseline | 0 | – | 0 | 13,657 | 35.4 | −2.92 |
| 5m atr1.0 rr1.5 | 10 | 20.0 | −39.9 | 3,397 | 39.9 | −1.10 |

## Where the R goes (5m atr1.0 rr1.5, per candidate)
| Component | R |
|---|---|
| Signal (win rate × payoff, ideal fills, no fees) | −0.06 |
| Slippage 0.05% × 2 on a 0.20% stop | ≈ −0.5 |
| Fees (brokerage, STT, exchange, GST, stamp) | −0.57 |
| **Net** | **≈ −1.0** |

## Conclusions
1. No variant has an edge after costs, in the selection window or in the holdout.
2. 5m bars halve the cost drag versus 1m (stops are ~0.2% of price instead of ~0.08%),
   but the signal itself is roughly breakeven before costs (ORB about +0.03R; the others negative).
3. Round-trip fees alone are ~0.1% of price, so a stop of 0.2% pays ~0.5R in fees per trade.
   Costs fall to ~0.1R only when stops are around 1% of price, i.e. much larger moves than
   these intraday setups target.
4. The slippage assumption (0.05%/side) is probably conservative for these liquid names
   (tick ₹0.05 ≈ 0.02%), but even at zero slippage, fees exceed the signal.
5. No config changes are made from this experiment. Phase 4 (ML) should run on 5m bars,
   since they are strictly better on costs, and must show positive net R out-of-sample.
