# Navrist future-bar forecasting system

Direct multi-horizon (+1..+5 candles), probabilistic forecasts on 5-minute NSE equity bars. It can
(and often does) answer **NO RELIABLE FORECAST**. Nothing here claims future prices can be known.

## Pipeline

| Stage | Module | Notes |
|---|---|---|
| Store | `forecast/store.py` | SQLite `data/forecast/market.db` (git-ignored). Append-only; a disagreeing re-fetch is flagged `revised_bar`, never overwritten. NULL = unknown, never 0. |
| Collector | `forecast/collector.py`, `backfill.py` | Angel SmartAPI `getCandleData`; 90-day chunks on a fixed grid, checkpointed in `fetch_log`, resumable. Every chunk is verified against what was requested (the API **silently truncates** ranges > ~100 days). |
| Quality | `forecast/quality.py` | Flags only, never repairs. Calendar + expected bar grid derived by consensus across reference equities (no hard-coded holiday list). A session is `verified` only with no FATAL flag. |
| Features | `forecast/features.py` | The ONLY feature code (training, backtest, live). Finite-window smoothers (no recursive EMA) so live == historical. |
| Labels | `forecast/labels.py` | Direct targets for t+1..t+5; never cross a session close / gap; valid OHLC reconstruction. |
| Baselines | `forecast/baselines.py` | persistence, recent-return, trend (+ Gaussian interval baseline). Permanent benchmarks. |
| Models | `models_gbm.py` (LightGBM), `models_gru.py` (numpy GRU) | Fixed hyperparameters. PyTorch/`shap` are blocked by this machine's Application Control policy, so Model B is numpy-only and SHAP is LightGBM's native TreeSHAP. |
| Calibration | `calibration.py`, `models_base.py` | Isotonic P(up) + conformalised quantile regression (CQR) intervals at 50/80/95%, fit on a calibration block strictly between train and test. |
| Ensemble | `ensemble.py` | Weights by grid search on the calibration block only. Regime-aware variant is measured, not assumed. |
| Regimes | `regimes.py` | trend × volatility from causal features; fixed a-priori thresholds. |
| Evidence | `evidence.py` | TreeSHAP support/oppose + agreement. Not causal proof. |
| Confidence | `confidence.py` | HIGH / MEDIUM / LOW / NO_RELIABLE_FORECAST; weighted geometric mean of independent components + hard gates. Tier monotonicity is validated OOS (`report.tier_report`). |
| Walk-forward | `walkforward.py`, `run_walkforward.py`, `evaluate.py`, `report.py` | Expanding window on whole sessions; session-block bootstrap CIs. |
| Registry | `registry.py`, `train_production.py` | Versioned artifacts + a fixed promotion gate. Failing models are `rejected`. |
| Tracking | `tracking.py` | Append-only forecasts, matched to the real candle; monitoring stats. |
| Live | `inference.py`, `live_ingest.py`, `api.py` | `GET /api/chart/{symbol}/forecast`, `GET /api/forecast/monitoring`. |
| Chart | `components/ForecastPanel.jsx`, `ForecastChart.jsx`, `lib/forecastView.js` (state mapping), `lib/forecastBoundaryPrimitive.js`, `LiveChart.jsx` | "Show Forecast" splits the area into LIVE (actual candles only) and FORECAST (summary card, NOW divider, hollow predicted candles, nested 50/80/95% bands, table); stacks below `lg`. Statuses: Generating forecast... / Forecast unavailable / Range forecast available (Directional signal uncertain) / Low-Medium-High confidence. |

## Operating it

```bash
python -m forecast.backfill --symbols RELIANCE TCS --years 3.1        # resumable, throttled
python -c "from forecast import quality, store; c=store.connect(); print(quality.run(c, ['RELIANCE'], ref_symbols=[...]))"
python -m forecast.run_walkforward --symbols RELIANCE TCS ... --min-train 300 --cal 25 --test 40
python -m forecast.report --models gbm gru ens ensr persistence recent_return trend
python -m forecast.train_production --gate-only                       # writes data/forecast/gate.json
python -m forecast.train_production --symbols RELIANCE TCS ...        # trains, registers, promotes ONLY if the gate passes
python -m pytest tests/test_forecast_core.py tests/test_forecast_system.py tests/test_forecast_gru.py
cd frontend && npm test
```

## Hard facts about the data source (measured, not assumed)

- Angel `getCandleData` 5m: history exists back to at least 2017; max ~100 calendar days per request, **older part silently dropped** when exceeded; timestamps are bar-open, IST offset included; volume included.
- Intraday history is **adjusted for bonus/splits** (verified across HDFC Bank's Aug-2025 bonus).
- Since 2026-08-03 the provider's 15:15/15:20/15:25 bars are missing or flat/zero-volume (cause unverified). Only the first 72 slots (09:15–15:10 starts) are used and a session must have all 72; forecasts are not issued where a horizon would reach past slot 71.
- Rate limiting is erratic and not penalised per rejected call: tight pacing (~1.5–3 s) with a short cool-down gave ~7 successful requests/min versus ~2/min with long back-off.

## Live freshness (why a forecast can briefly read "Updating...")
Inference only forecasts when the store holds the latest completed bar for the symbol AND the NIFTY context bar. The provider serves a
bar ~0.1 s after it closes (measured), so staleness is ours. `live_ingest` keeps every *active* symbol (requested in the last 15 min)
current: a scheduler fetches right after each 5-minute boundary and retries (3 s gap, max 25 attempts per bar, only in-session
weekdays) until the bar is stored. Measured: a real forecast is available ~10 s after the candle closes. `refreshing` in the API
response is true only while a fetch is running or still due. Withheld (stale) payloads are never persisted.

## Scaling beyond the pilot symbols (onboarding)
`forecast/onboarding.py` extends RANGE forecasts to any NSE equity without retraining, on evidence: fetch ~70 days (1-2 requests), run
quality checks, then FORWARD-validate the production pooled model on that symbol's sessions after the model's weight-training window.
A symbol is `validated` only if enough clean data exists (>=1000 rows, >=15 sessions, >=90% sessions verified, <=5% zero-volume bars),
conformal coverage at 50/80/95% is near nominal (mean within 5 pts, each horizon within 8), and the 80% interval score beats a Gaussian
baseline. Otherwise `failed` with explicit reasons (illiquid, too little data...) and the UI says why. Directional calls stay
pilot-only (direction was validated on the pilot universe alone). Triggered on demand from the forecast API on first open, and in bulk with
`python -m forecast.onboarding --all-nse` (resumable; ~4-5 symbols/min). Progress: `GET /api/forecast/coverage`. A new production model
re-validates every symbol (results are keyed by model_version).

## Known limits

- Universe = symbols present in the validation set; any other symbol returns NO RELIABLE FORECAST.
- No sector/breadth features yet (no verified source). NIFTY 50 context is used when available.
- Dividend adjustment, symbol changes and delisted symbols are not verified.
- Live path uses Angel (own session); the chart's actual candles come from yfinance, so the overlay is drawn only when the forecast's anchor candle equals the chart's last completed candle.
