# Forecast validation record - 2026-10-05

Genuine walk-forward results on real Angel One 5-minute bars. No synthetic data. Reproduce with
`python -m forecast.run_walkforward --symbols RELIANCE TCS HDFCBANK INFY ICICIBANK SBIN ITC LT --min-train 300 --cal 25 --test 40`
then `python -m forecast.report --models gbm gru ens ensr persistence recent_return trend`.

## Setup
- Universe: 8 liquid NSE equities (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, SBIN, ITC, LT) + NIFTY 50 context. Pooled model.
- Data: ~3.1 years of 5m bars (2023-08 .. 2026-10), 761-762 of 768 trading sessions verified per symbol; 6-7 sessions excluded for nonstandard session structure / missing bars. First 72 slots of each session only.
- Walk-forward: 9 expanding-window folds (min 300 training sessions, 25-session calibration block, 40-session test block, 1-session embargo). Test dates 2025-02-10 .. 2026-08-06, **207,216 out-of-sample rows**.
- Nothing fitted on test: models, isotonic calibration, conformal margins, ensemble weights, baseline sign statistics all use train/calibration blocks only. Hyperparameters fixed a priori.

## Results (pooled, out-of-sample)
Direction (base rate of "up" 48.6-49.3%):

| h | ens acc | ens Brier | persistence Brier | misclassification vs baseline (95% CI) | direction validated |
|---|---|---|---|---|---|
| +1 | 52.4% | 0.2492 | 0.2500 | -1.7 pts [-2.0, -1.4] | yes |
| +2 | 52.0% | 0.2495 | 0.2499 | -1.1 pts [-1.4, -0.8] | yes |
| +3 | 51.6% | 0.2497 | 0.2499 | -0.4 pts [-0.8, -0.1]; Brier CI includes 0 | no |
| +4 | 51.5% | 0.2498 | 0.2499 | CI includes 0 | no |
| +5 | 51.3% | 0.2499 | 0.2498 | CI includes 0 | no |

The +1/+2 edge is statistically real and economically tiny (Brier skill ~0.3%, ~2.5-3.5 points over base rate). It has not been tested against transaction costs and should not be read as a trading edge.

Return magnitude (|error| / trailing vol): ensemble beats persistence by 0.1-0.15% at every horizon (CI below 0 at h=1,2,3,4,5) - a marginal gain, driven mostly by the volatility scale.

Intervals (conformal, nominal 50/80/95): empirical coverage 50.3-50.5 / 80.2-80.4 / 95.1-95.3 at every horizon; 80% intervals 20-40% narrower than the Gaussian baseline at equal coverage. **This is the validated product claim.**

Confidence tiers (ensemble): no HIGH ever issued; ~72-79% of rows are NO_RELIABLE_FORECAST. At +1 tiers are monotone (MEDIUM 56.9% acc, LOW 53.4%, NO_RELIABLE 51.8%); at +2 monotone; at +3..+5 NOT monotone / sample too small - those horizons are capped by the gate.

Regime-aware weighting vs global weighting: indistinguishable out-of-sample (differences <= 0.0003 in Brier / 0.0001 in nmae) -> **not used in production**.

Models: LightGBM and the numpy GRU are individually near-identical to each other; the ensemble is marginally better than either on direction. Ensemble weights vary between folds (noise-level models).

## Promotion gate verdict (`registry.promotion_gate`, criteria fixed in advance)
PASS: range validated at all 5 horizons (Winkler 80% CI below 0 vs best baseline, coverage within +-3 pts), 7 of 9 folds (78%) beat the best baseline on |error|/sigma. Direction validated at +1, +2 only. Promoted model `v20261005132822`.

## Known limitations
- 8 symbols only; any other symbol returns NO_RELIABLE_FORECAST ("symbol not validated").
- Not tested: transaction costs, intraday-liquidity effects, regime shifts beyond the sample, other timeframes.
- Last 3 candles of the session (15:15+) are not forecast (provider data there is unverified).
- Live tracking has only a handful of matched forecasts so far; monitoring statistics need weeks of data to be meaningful.
