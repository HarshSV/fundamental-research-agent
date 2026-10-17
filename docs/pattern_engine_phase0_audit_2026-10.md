# Pattern Forecasting Engine - Phase 0 audit (2026-10-15)

Measured from `data/forecast/market.db` and the repository. Nothing here changes production behaviour.

## 1. Data actually available

| Item | Measured |
|---|---|
| Provider | Angel One SmartAPI `getCandleData` (forecast store). The chart's own candles come from yfinance, a separate, temporary pipeline. |
| 5m candles | 200 symbols, 1,136,771 bars, 2023-08-30 to 2026-10-14. **Only 9 symbols have >= 20,000 bars (~3 years)**: NIFTY 50 plus the pilot stocks. Median symbol has 3,575 bars (~49 sessions). |
| Daily candles | 56 symbols, 338,608 rows, 2000-01-04 to 2026-10-05 (~26 years). Today's large caps only: **survivorship bias**, no delisted names. |
| Intervals | 5m and 1d in the store (1m/15m/1h exist only in the yfinance chart feed, not persisted). |
| Quality flags (5m) | missing_bar 2,597; zero_volume 2,331; nonstandard_session_structure 239; off_session 181; abnormal_jump 9; revised_bar 5; missing_session 5. Since 2026-08-03 the 15:15-15:25 bars are missing/flat, so only 72 of 75 slots are usable. |
| Adjustment | Provider returns bonus/split-adjusted history (verified on HDFCBANK). `adjustment_status` is not stored per candle. |
| Symbol validation | 109 validated, 100 failed (mostly gappy illiquid names). |
| Live forecasts | 195 stored, 177 already evaluated against actual candles. |

## 2. Spec versus what exists

| Spec item | State |
|---|---|
| Canonical instrument/candle tables (UTC, unique key, raw vs normalised) | **Mostly present**: `instruments`, `candles`, `fetch_log`; append-only with `revised_bar` flag. Missing: ISIN, `valid_from/to`, `adjustment_status`, listing status. |
| Data validation | **Present** (`forecast/quality.py`, flags only, never repairs). |
| Pattern registry with versioned definitions | **Partial**. Chart patterns (16 daily/weekly, 16 intraday, order blocks) live only in the frontend (`patternRegistry.js`), unversioned, not persisted. 13 candlestick patterns exist in Python (`forecast/candle_patterns.py`) with parameters in one dict. |
| `pattern_occurrences` persistence | **Missing.** Occurrences are recomputed in the browser. |
| Leak-free outcome labels | **Partial.** `forecast/pattern_stats.py` does later-close outcomes for the 13 candlestick patterns, session-bounded, chronologically split. No 3-class volatility-adjusted label, no maturity status, no MFE/MAE, no barrier outcomes. |
| Feature snapshots | **Missing as a table**; `forecast/features.py` is a single point-in-time feature engine used for train/backtest/live. |
| Models | **Present** for return/range: LightGBM + numpy GRU, conformal 50/80/95% intervals, walk-forward, promotion gate. **Absent**: 3-class up/down/flat classifier per pattern. PyTorch/shap/some sklearn are blocked by this machine's policy. |
| Forecast persistence + evaluation | **Present**: `forecasts` (append-only, unique key), `forecast_evaluations`. |
| Daily metrics table | **Partial**: `tracking.monitoring_stats` computed on demand; no `model_metrics_daily`. |
| API `/api/v1/...` | Different shape today (`/api/chart/{symbol}/forecast`, `/api/forecast/monitoring`, `/api/forecast/coverage`). |
| Chart | Forecast panel (candles / bands), pattern markers (grey/blue, not outcome-coloured), order blocks. Outcome-coloured historical flags and prediction-vs-actual overlay do not exist. |
| Sentiment | None (correct for now). |

## 3. What the existing evidence already says (sets expectations)

- 5m: range forecasts validated; direction marginal at +1/+2 only (`docs/forecast_validation_2026-10.md`).
- Daily: ranges validated, **no direction edge at any horizon** (`docs/daily_validation_2026-10.md`).
- 13 candlestick patterns, 8 pilot stocks, 5m: next-candle up-rate at or below the unconditional rate (`docs/candle_pattern_stats_2026-10.md`).

So Phase 1/2 should expect most chart patterns to be indistinguishable from the base rate. The engine's value is measuring that honestly, not drawing green and red flags.

## 4. Proposed build order given the data

1. **Phase 1 on daily bars (56 symbols, 26 years)** for the 16 daily/weekly base patterns: port the detectors to Python (single implementation, versioned), persist `pattern_occurrences` at the CONFIRMATION date, label 5/15/30-bar outcomes with a volatility-based flat threshold known at signal time, with maturity status. Report unconditional vs conditional frequencies with sample sizes. Caveat: survivorship bias.
2. **Intraday patterns only for the 9 symbols with ~3 years of 5m data**, as a separate, smaller study.
3. Phase 2 (3-class LightGBM + calibration + walk-forward) only after step 1 shows any pattern beating its baseline out of sample.
4. Phases 3-4 reuse the existing `forecasts`/`forecast_evaluations` tables rather than adding parallel ones; add outcome-coloured flags last.

## 5. Decisions needed before Phase 1

- Port detectors to Python (recommended) or run the existing JS detectors under Node for labelling?
- Daily timeframe first (recommended, 26 years) or intraday first?
- Neutral threshold: k x ATR-normalised move (recommended; k to be fixed on a development period, not the test period).
