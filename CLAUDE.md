# Intraday trading bot with Jev decision layer

Placeholders (fill before Phase 1): **[BROKER]** = Zerodha (Kite Connect), **[WATCHLIST]** = NTPC, ITC, ONGC, POWERGRID, TATASTEEL, COALINDIA, WIPRO, ETERNAL (low-priced so ₹1,000 can buy ≥1 share; re-check prices in Phase 2).
Starting capital ₹1,000. Timeframes 1-min and 5-min. NSE cash session, Asia/Kolkata.
Build ONE phase at a time. After each phase: run tests, show acceptance results, wait for approval. Ask before assuming anything about broker APIs, Jev API fields, or costs. Never paste/print API keys.

## Role and overview
Senior quant developer / Python engineer. Build a personal, autonomous intraday system for Indian equities (NSE cash) with a full analysis dashboard, single user. It scans a watchlist on 1m/5m candles, detects setups, scores with a trained ML model, sends final judgment to TypeSafe AI's Jev model, passes every approved signal through a strict risk manager, and places orders via the broker API. Every decision, including rejections, is logged.
Goal: positive expectancy after all costs, proven out-of-sample, controlled drawdown. A backtest win rate above 70% is a probable bug (leakage, overfitting, missing costs) — investigate.

## Non-negotiable rules (override everything else; if a request conflicts, stop and ask)
1. Paper mode is default. Live only when TRADING_MODE=live AND a confirmation flag file exists. Log a warning banner on every live start.
2. Risk manager is the only path to the broker. No module other than execution/ may import broker order functions. Add a test enforcing this.
3. Fail closed. Any error, timeout, stale data (no tick for 60 s), or missing Jev answer = no new trade. Existing positions keep their stop-loss orders.
4. Every entry gets a broker stop-loss order immediately after fill. If the stop cannot be placed, exit at market.
5. No look-ahead. Features at bar t use only data closed at or before t. Labels use future bars but never leak into features. Add tests.
6. Costs always modelled: brokerage, STT, exchange charges, SEBI fee, stamp duty, GST, slippage. One config file (costs.yaml).
7. Secrets in .env via python-dotenv; .env in .gitignore. Never log/print keys or tokens.
8. Pin versions of every dependency and of the Jev model where the API allows.
9. Follow broker and SEBI retail-algo rules (static IP, order-rate limits, required registration). Check current broker docs; stay under rate limits.
10. No leverage in v1. Position value never exceeds available cash.

## Stack
Python 3.11+ (uv or poetry, pinned). pandas, numpy, pandas-ta (or tested hand-written indicators). LightGBM, scikit-learn. Custom event-driven backtester (vectorbt for quick research only). TypeSafe `typesafe-sdk` (verify against official docs). [BROKER] official SDK behind a BrokerAdapter interface. asyncio, APScheduler. SQLite via SQLAlchemy (logs/trades), Parquet (candles). Streamlit + Plotly. Telegram bot API. pydantic-settings, YAML config, .env secrets. pytest, ruff, mypy, pre-commit. Hosting: Mumbai-region Linux VPS, 1 vCPU, 1–2 GB, systemd.

```
trading-bot/
  CLAUDE.md  .env.example
  config/     settings.yaml costs.yaml risk.yaml watchlist.yaml jev_questions.yaml
  data/       raw/ parquet/ (gitignored)
  src/bot/
    data/       broker feed, historical loader, candle builder, data-quality checks
    features/   indicator and feature engine
    detectors/  orb.py vwap_reclaim.py trend_pullback.py
    ml/         dataset builder, labeller, trainer, model registry, inference
    jev/        client wrapper, state builder, question specs, response parser
    decision/   gate logic combining detector, ML, Jev
    risk/       risk manager, position sizing, kill switch
    execution/  broker adapter interface, paper broker, live broker adapter
    backtest/   event-driven engine, cost model, metrics, walk-forward runner
    storage/    SQLAlchemy models and repositories
    alerts/     Telegram notifier
    runner.py   live/paper main loop
  dashboard/  Streamlit app, one file per page
  tests/
  scripts/    download_history.py train_model.py run_backtest.py replay_jev.py
```

## Pipeline (candidate must pass every stage in order)
Runs on every closed 1-min bar per watchlist symbol, in parallel via asyncio.
1. Data feed: websocket ticks -> 1m/5m candles; quality checks reject gaps, duplicates, stale feed.
2. Feature engine: closed bars only.
3. Detectors emit Candidate (symbol, setup, direction, entry, ATR stop and target). No candidate = nothing else runs.
4. ML: calibrated probability target hits before stop.
5. Jev: compact pre-computed state, typed questions; only called when a candidate exists.
6. Decision gate: combines outputs vs config thresholds; records which gate passed/failed.
7. Risk manager: sizing, account limits, veto.
8. Execution: entry, then stop-loss and target; track fills.
9. Storage and alerts: every stage writes to SQLite; important events to Telegram.
One DecisionRecord per candidate collects every stage's output incl. rejections and reasons (backbone of dashboard). Latency budget: features+ML < 50 ms, Jev < 800 ms hard timeout, order placement < 1 s; log per-stage timing.

## Data, features, detectors, ML
Data: ≥12 months 1-min history for watchlist and Nifty 50 index, Parquet partitioned by symbol/month. Handle holidays, half days, corporate actions. Data-quality report per symbol (missing bars, outliers).
Features (closed bars only): price vs VWAP %, VWAP slope; RSI(14) and 3-bar slope; EMA 9/21/50 relationships; ATR(14) % of price, realised vol; volume vs 20-bar avg, surge flag; opening range (first 15 min) high/low and distances; Nifty trend on 5m and 15m, relative strength vs Nifty; time-of-day bucket, minutes to close; previous day high/low/close distances; gap at open %.
Detectors (one file each, unit tests on hand-made candles): (1) opening range breakout after first 15 min with volume confirmation; (2) VWAP reclaim/rejection; (3) pullback to EMA21 in established trend. Output direction, entry, stop = ATR multiple (config, start 1.0×), target = reward:risk (config, start 1.5).
ML: dataset from every historical candidate. Label 1 if target hit before stop within same session, else 0 (timeouts at square-off = 0, record their P&L). LightGBM, time-based splits only, never random shuffle. Calibrate (isotonic/Platt) on a separate validation window. Registry saves model + feature list + training window + metrics + version id. Report AUC, Brier, calibration curve, feature importance.

## Jev decision layer
Jev (TypeSafe AI) is non-generative "System One": takes state (text/JSON) and typed questions (choice, score, noul), returns structured answers with probabilities and confidence. It does no arithmetic — compute every number in code. Jev confirms or vetoes; never originates trades, sizes, or sets prices.
State: only decision-relevant, named JSON fields, rounded. Example fields: symbol, setup, proposed_direction, price_vs_vwap_pct, rsi_14, rsi_trend, volume_vs_avg, nifty_trend_15m, relative_strength_vs_nifty, atr_pct, ml_prob_win, news_sentiment, minutes_to_close.
Questions (config/jev_questions.yaml, versioned, never hard-coded):
- action (choice): long = signals align for upside; short = align for downside; stay_out = conflict/unclear edge.
- quality (score): "Weak, conflicting signals" / "Acceptable" / "Strong, signals aligned".
- trap (noul): "Do the signals suggest a false breakout or an exhausted move?"
News sentiment: separate cached Jev call per headline (bullish/bearish/neutral/irrelevant), refreshed every few minutes from RSS and NSE corporate announcements; latest per symbol feeds the state.
Client wrapper: key from TYPESAFE_API_KEY in .env; hard timeout 800 ms, one retry only if time remains, else fail closed; pin model version if supported and log returned version every call; log full state, questions version, answers, probabilities, confidence, latency in DecisionRecord; MockJev for tests and offline backtests.
Gate (thresholds in config, tuned on validation only):
```
passes = candidate is not None
  and ml_prob >= ml_min_prob (0.60)
  and jev.action.choice == candidate.direction
  and jev.action.confidence >= jev_min_conf (0.70)
  and jev.quality.score >= jev_min_quality (1.5)
  and jev.trap.noul < jev_max_trap (0.35)
```
Config switch decision.mode: rules_only | rules_ml | rules_ml_jev.

## Risk manager and execution (config/risk.yaml; checks in order, record first blocking rule)
Risk per trade 1% equity (stop distance × qty). Max position value 100% available cash, no leverage. Max daily loss 3% of start-of-day equity then stop for the day. Max 3 trades/day. Max 1 open position. Stop day after 2 consecutive losses. No entries before 09:30 or after 14:45 IST. Forced square-off 15:10 IST. Minimum edge: target distance > 3× estimated round-trip costs. Kill switch: file flag, dashboard button, Telegram command; flattens all and stops loop.
Qty < 1 share: skip and log reason; never round up.
Execution: BrokerAdapter (place_order, cancel_order, modify_order, positions, orders, funds, subscribe_ticks). PaperBroker first (fills at next-bar open + slippage, same cost model as backtester). Then [BROKER] adapter. Limit/marketable-limit entries, stop-loss immediately after fill, reconcile with broker every minute and on restart, token-bucket rate limiter.

## Backtesting and validation
Event-driven; reuses the exact feature/detector/ML/decision/risk code as live (one code path); only data source and broker differ. Fills next-bar open + slippage (start 0.05%), full costs on both legs, square-off 15:10.
Walk-forward: rolling train/validate/test (e.g. 6m/1m/1m), retrain ML per fold, tune thresholds on validate only, report test only.
Jev replay: scripts/replay_jev.py caches responses on disk keyed by (state hash, questions version, model version).
Compare rules_only, rules_ml, rules_ml_jev on same folds in one report.
Metrics per variant: trades, win rate, avg win/loss, expectancy after costs, profit factor, max drawdown, Sharpe, exposure time, cost as % of gross profit, breakdown by setup, symbol, time of day.
Sanity checks: shuffled-label test (collapses to random), cost-doubling stress, no feature timestamp later than decision timestamp.
Jev stays only if rules_ml_jev beats rules_ml on OOS expectancy after costs without worse max drawdown.

## Dashboard (Streamlit + Plotly; reads SQLite and backtest files; mode selector + date filter on every page; live pages auto-refresh 5 s)
Pages: Overview (equity, P&L gross/net, open position, bot status, daily-loss used vs limit, kill switch); Trades (journal, candle chart with VWAP/EMAs/entry/stop/target/exit, full DecisionRecord); Decision funnel (candidates → ML → Jev → risk → filled, top rejection reasons, rejected table with hypothetical outcome); Jev analytics (calibration, agreed vs vetoed, score distributions, latency histogram, timeouts/errors, model versions); ML analytics (calibration, AUC/Brier over time, importance, drift); Performance (equity, drawdown, expectancy, win rate, PF, Sharpe, P&L by setup/symbol/weekday/time, costs); Backtest lab (saved runs, launch new, compare three variants, per-fold); Logs and settings (events, read-only config, config history).
Security: bind to localhost (SSH tunnel) or password protect; kill switch asks confirmation; never show keys/tokens.

## Phases (approval required between each)
1. Foundations: setup, config, .env.example, storage models, logging, CI. Done: pytest, ruff, mypy pass; DB created from clean checkout.
2. Data and features: download, candle builder, quality report, feature engine. Done: look-ahead tests pass; no unexplained gaps.
3. Detectors and backtester: 3 detectors, cost model, backtester, rules_only results. Done: hand-made cases trigger right detector; report shows all metrics after costs.
4. ML: dataset, labeller, walk-forward, calibration, registry, rules_ml results. Done: shuffled-label test collapses; calibration curve reported.
5. Jev layer: client + timeout + MockJev, state builder, questions config, replay cache, news sentiment, rules_ml_jev results, three-way report. Done: timeout test fails closed; comparison complete.
6. Dashboard: all eight pages on backtest data. Done: Performance metrics match backtest report.
7. Paper trading: live feed, runner, PaperBroker, risk, kill switch, Telegram, systemd on VPS. Done: 4 weeks paper, no unhandled errors, every decision visible.
8. Live with ₹1,000: broker adapter, reconciliation, stop-loss checks. Done: kill switch tested live with 1-share position and paper targets met.
Go-live targets (OOS and paper): positive expectancy after costs, max drawdown < 10%, ≥ 50 trades, chosen mode beats simpler variants.
