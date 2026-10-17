# Pattern classification and realised-outcome tracking ("What's happening")

Three things are kept separate everywhere in the UI and in the code:

| Concept | Meaning | Where | Colour |
|---|---|---|---|
| **Pattern bias** | The conventional technical-analysis expectation, fixed before any outcome is known. Not a prediction and not evidence the pattern worked. | `src/lib/patternClassification.js` | neutral glyphs: sky ▲ bullish, amber ▼ bearish, slate ◆ context-dependent (never green or red) |
| **Realised outcome** | What price actually did after the first detection, measured from real candles. | `src/lib/patternOutcomes.js` | green positive, red negative, grey flat, dashed sky-blue pending, dim italic not evaluable |
| **Model prediction** | **Does not exist for chart patterns**, so there is no such field. (The forecast engine predicts price ranges, not pattern success.) | - | - |

## What a count means
A chip count = number of **formation runs** detected for **this stock** in the **loaded window** (consecutive re-firings of one
formation collapse into one run). It counts detections - not successes, not distinct stocks, not "active" patterns.
Daily/weekly pattern statistics use the stock's full daily/weekly history; the chip count uses only formations inside the loaded
intraday window, and the panel says so.

## Classification registry
`PATTERN_CLASSIFICATION` is keyed by the same `id` as `PATTERN_REGISTRY` (`patternRegistry.js`, still the source of truth for which
patterns/detectors exist). A test fails if the two lists diverge, and a second test **greps the real detector source** to check
that the documented detector tone (`pos`/`neg`/`neutral`) is what `mk(...)` actually emits (24+ patterns cross-checked).

* **Bullish:** Double Bottom, Cup & Handle, Flat Base, Ascending Base, IPO Base, High Tight Flag, Three Weeks Tight, Inverse H&S,
  Triple Bottom, Rounding Bottom, Cup Base, Saucer Base, Falling Wedge*, Ascending Triangle*, Pocket Pivot, Undercut & Rally,
  Shakeout, Wyckoff Spring, Bullish Order Block. (*needs a confirming upside breakout)
* **Bearish:** Double Top, Head & Shoulders, Triple Top, Rising Wedge*, Wyckoff Upthrust, Bearish Order Block, **Descending Triangle***
  (not in the original list; mirror of Ascending Triangle), **Rounding Top** (bearish but needs structural confirmation - the detector
  only checks the arc fit; listed under "context" in the request, kept as bearish-needs-confirmation and flagged).
* **Context-dependent (never forced):**
  * *Flag, Pennant* - bullish/bearish **subtype read from the detector's pole direction**; no direction -> "direction unconfirmed".
  * *Order Block Retest* - direction from the zone side; *Order Block Broken* - an invalidation, no direction.
  * *VCP* - the detector requires an uptrend and shrinking pullbacks but never evaluates a breakout -> direction unconfirmed
    (its hard-coded `pos` tone is deliberately not trusted).
  * *Symmetrical Triangle, Rectangle* - direction depends on a breakout the detector does not evaluate.
  * *Harmonic (Gartley-like)* - the detector does not distinguish bullish from bearish completion -> no direction claimed.
* If a detector's direction **contradicts** the registry (e.g. a "Double Top" emitted with a bullish tone) the event is reported as
  `context` with `conflict: true`, never silently resolved. Unknown patterns are `unknown`.

## Outcome calculation
* **Reference bar** = the bar at which the detector first had enough data (`confirmedAt`); **reference price** = that bar's close.
  Forward candles are strictly after it.
* **Forward return** `r_h = close[ref+h] / close[ref] - 1` (simple return, no dividends). Horizons are in bars of the pattern's own
  timeframe, configurable per timeframe (`DEFAULT_CONFIG.horizons`; default 5, 15, 30 bars for intraday, daily and weekly).
* **Flat band** (known at the reference bar): `band_h = max(floor_tf, k * sigma20 * sqrt(h))`, `sigma20` = std-dev of the last 20 one-bar
  log returns up to the reference bar (intraday: same-session returns only); `k = 0.5` and floors (intraday 0.10%, daily 0.50%,
  weekly 1.00%) are configuration and were **not tuned on outcomes**. Positive: `r > band`; Negative: `r < -band`; boundary = Flat.
* **Pending** - the horizon bar does not exist yet (live data can still arrive). Never Flat.
* **Not evaluable** (excluded from statistics, reported separately): intraday horizon would cross the session close; missing candles
  in the forward window; a split-like (clean-ratio, > 40%) single-bar jump; reference bar missing. Real crashes below that are kept.
* **Dedupe:** one formation = one occurrence, referenced at its **first** detection (`collapseRuns(..., 'first')`); later re-firings never
  add occurrences or move the reference time. **Overlap:** statistics report an *independent* subset in which an occurrence whose
  forward window overlaps an earlier one is skipped.
* **Base rate:** the same rule applied to every bar of the series, shown beside each pattern rate for context.
* Rates/averages are `null` (shown "-"), never 0, when nothing is evaluable; samples under 30 independent observations are flagged.
* **Leakage:** the return reads only closes at/after the reference bar; sigma only bars at/before it; nothing feeds back into detection.
  Tests corrupt future bars to prove this, and prove that detections found on a history prefix equal the full-history detections for those bars.

## Real-data results (one stock, as of the dump)
`frontend/scripts/patternOutcomesReport.mjs` runs the production detectors and outcome code on real OHLCV
(`.audit-data/TCS`: 1,241 daily bars 2021-10 to 2026-10, 262 weekly, 5-minute bars). Its output is saved in
`docs/pattern_outcomes_TCS_real_data_2026-10.txt`. **These are single-stock historical frequencies with small samples - no pattern
is shown to be reliable, profitable or accurate by them.** Most daily patterns have fewer than 30 independent observations.

## Limitations (not hidden)
* **Client-side only.** Detection and outcomes are computed in the browser from the loaded candles; nothing is persisted server-side.
  The original detection time and reference price are preserved in each occurrence and are reproducible (deterministic) from the same
  candles, but there is no immutable audit table. Persisting occurrences needs the detectors ported to Python (see
  `pattern_engine_phase0_audit_2026-10.md`).
* **One stock at a time**, and intraday history is only the ~60-day yfinance window, so samples are small. No cross-stock statistics.
* **Prices are the provider's adjusted series**; the client cannot verify corporate-action adjustment (only a conservative split-ratio guard).
* **Detector limits are inherited:** the intraday replay re-fires often (hundreds of formations), the geometry detectors are subjective,
  and several (Wyckoff, Harmonic) are low reliability. A pattern whose confirming bar is still forming can re-evaluate when it closes.
* No predictive model, calibration or accuracy claim is made for chart patterns.
