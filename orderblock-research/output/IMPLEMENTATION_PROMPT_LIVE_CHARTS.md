# Prompt for Claude Code — Add Order Block & Liquidity zones to the Navrist Live Chart

Paste everything below the line into Claude Code in the Navrist repo.

---

## Task
Add an original **Order Block (OB) + Liquidity zone overlay** to the existing Live Chart (`frontend/src/views/LiveChart.jsx`). For the selected symbol it detects the current and earlier same-session order blocks on closed 5-minute candles, draws the zone, invalidation level, liquidity targets and R:R on the chart, and lists them in the existing events feed. The concept is inspired by a competitor study (`orderblock-research/output/PRODUCT_SPEC.md`); implement only the original algorithm specified here. Do not copy any competitor text, naming, images or code.

## Hard rules (from CLAUDE.md, non-negotiable)
1. **Generic across all symbols.** The selected stock is a test case only. No ticker-specific logic, thresholds or special cases anywhere.
2. **Unknown is never zero/false.** If there is not enough history, fewer than two liquidity candidates exist, volume is missing, or a value can't be computed, the field is `null` and the UI shows "—" with a reason. Never default to 0, never fabricate a level, never draw a zone from a still-forming candle.
3. Fix/design systemically, not per stock. Do not touch the LLM-disabled state (no Groq/OpenRouter).
4. This is analytics, not advice: no buy/sell wording, no "signal"/"target hit" claims. Use neutral labels (Zone, Invalidation, Level 1/2, Room:Risk). Add the one-line disclaimer already used by the app, if present, else a short "Analytics only, not investment advice."

## Existing architecture to extend (read these first)
- `frontend/src/lib/patternRegistry.js` — single source of truth for patterns; `entry(displayName, timeframe, minBars, category, detector, definition)`; `runDetectors(timeframe, bars, meta)`; `scripts/auditPatterns.mjs` and `tests/registry.test.mjs` fail if a detector emits an unregistered type.
- `frontend/src/lib/chartPatterns.js` (`mk`, `locOf`, `patternType`, `detectChartPatterns`), `technicalAnalysis.js` (`swingPoints(candles, wing=2)`, `analyzeCandles`), `eventModel.js` (`stampEvent`, timestamp semantics: `time`, `formedAt`, `confirmedAt`), `eventReplay.js`, `patternStatus.js`, `patternCatalog.js`, `marketTime.js` (IST).
- `frontend/src/lib/rangeBoxPrimitive.js` — lightweight-charts series primitive drawing a rectangle from `startIndex..endIndex` and `rangeLow..rangeHigh`. Extend or add a sibling primitive; do not rewrite chart plumbing.
- Backend: `app.py` `/api/live-chart/{symbol}`, `/day`, `/latest`, via `tools/live_chart_yf.py` (yfinance stand-in; `warmup` bars come back for detector calculation only and are never drawn).
- Tests: `frontend/tests/*.test.mjs` run with `node --test`; `tests/test_live_chart_ticker.py` for the Python side.

## Design
### 1. Pure detector module: `frontend/src/lib/orderBlocks.js`
Pure functions, no DOM/network, deterministic. Export `detectOrderBlocks(bars5m, meta, params = DEFAULT_OB_PARAMS)` returning an array of zone objects, plus `DEFAULT_OB_PARAMS` and `OB_PARAMS_VERSION = 1`.

Inputs: closed 5-min bars `{time(unix s), open, high, low, close, volume|null}` including warmup bars for context; `meta = { sessionStart, sessionEnd, tickSize|null, prevDayHigh|null, prevDayLow|null }`. **Exclude the last bar if it is still forming** (its period end > now, using IST market clock from `marketTime.js`); the existing code should already distinguish this — reuse its rule rather than inventing one.

Definitions (all parameters in `DEFAULT_OB_PARAMS`, none hard-coded in logic):
- `swingWing = 2`: reuse `swingPoints` for confirmed swing highs/lows (confirmed only after `swingWing` later bars).
- `ATR5` = mean true range of last `atrLen = 14` closed bars; `bodyAvg` = mean |close−open| of last `bodyLen = 20` bars. If fewer bars than the window, the dependent test returns `null` and **no zone is emitted** (insufficient history is not a detection).
- **Break of structure (BOS):** bullish at bar i if `close[i]` > latest confirmed swing high (fallback: opening-range high of 09:15–09:30 once complete) and no earlier close was above that level since it was set. Bearish mirrors with swing low / OR low.
- **Displacement (any one):** `range[i] >= dispMult × ATR5` (`dispMult = 1.2`); or a fair-value gap with bar i+1 (`low[i+1] > high[i−1]`, mirror for bearish); or close beyond the broken level by `>= bodyAvg`.
- **Order block:** bullish = last down-close candle at or before the start of the displacement leg, searched back at most `obLookback = 10` bars and not past the previous swing low; bearish = last up-close candle. Zone = candle `[low, high]` (wick-inclusive).
- `Z` = zone edge nearest price (bullish: block high; bearish: block low), configurable `zMode: 'edge' | 'mid'`.
- **Invalidation (INV):** bullish: block low (minus `invBufferTicks × tickSize` only if `tickSize` is known, else no buffer); bearish: block high (plus buffer). Broken when a **closed** 5-min bar closes beyond INV.
- **State machine:** `formed → untouched → retested(n) → broken`; a retest = a later bar's range overlaps the zone and closes back on the trend side; track `touchCount` and `firstRetestTime`.
- **Liquidity levels** (candidates beyond Z in the direction of the move, and untested): confirmed swing highs/lows never closed through; equal highs/lows (≥2 within `eqTolPct = 0.05%`); prior-day high/low (only if provided in `meta`); session high/low; session open. `level1`, `level2` = nearest two; `ladderOpposite` = up to three further levels the other way. Fewer than two candidates ⇒ missing ones are `null`.
- **Room:Risk** `rr = |level2 − Z| / |Z − INV|`; `null` if `level2` or the denominator is unavailable or zero. Flag `lowRoom: true` only when `rr` is a number below `rrFloor = 1.5`.
- **VWAP:** session VWAP from bars with volume; `null` if any session bar lacks volume (don't treat missing volume as 0). `vwapSide` ∈ `above|below|null`.
- Each zone object: `{ id, side:'bull'|'bear', formedAt, confirmedAt, time, startIndex, endIndex, zoneLow, zoneHigh, z, inv, level1, level2, ladderOpposite, rr, lowRoom, state, touchCount, firstRetestTime, brokenAt, vwapSide, paramsVersion, reasons:[] }`. `reasons` lists why a field is null (e.g. `"only 1 liquidity level in range"`).
- Keep **all same-session zones** (current = most recent non-broken zone on each side); earlier ones are drawn faded and unlabeled.
- Look-ahead guard: evaluating at bar t may read only bars with `time <= t`. A zone's `confirmedAt` is the bar where the BOS closed, never earlier.

### 2. Registry + event integration
- Register patterns via `entry()` in `patternRegistry.js` (timeframe `'intraday'`, `minBars = 40`, category `'structure'`): `Bullish Order Block`, `Bearish Order Block`, `Order Block Retest`, `Order Block Broken`. Each has a one-sentence `definition` that matches the code exactly. The detector emits events through `mk`/`stampEvent` so `time`, `formedAt`, `confirmedAt` follow `eventModel.js` (marker sits on the BOS-completion bar; the zone box starts at the OB candle).
- Make sure `scripts/auditPatterns.mjs` and `tests/registry.test.mjs` still pass and now cover the new types.
- Ensure history replay (`eventReplay.js`, `/day` endpoint with warmup) produces identical zones as live polling for the same bars (determinism).

### 3. Chart rendering
- New primitive `frontend/src/lib/zoneOverlayPrimitive.js` (or extend `RangeBox`): draws, per zone, a box from the OB candle to the right edge (until `brokenAt` if broken), a shaded zone band, an invalidation line, Level 1/Level 2 lines, and optional dotted ladder lines. Current setup gets text labels (`Z`, `INV`, `L1`, `L2`, `Room:Risk`); earlier zones are drawn faded without labels. Use theme tokens from `frontend/src/theme/tokens.css` for green/red/amber (works in light and dark); clip to the visible time range; no per-frame allocations.
- Toggle chip "Order Blocks" in the existing pattern selector (default off to preserve current behaviour), plus a "Liquidity levels" sub-toggle.
- Clicking a zone or its feed row opens a small card: side, zone range, Z, INV, L1, L2, Room:Risk, state, touches, VWAP side, and the `reasons` for any "—" fields. Show the params version.
- Mobile: card becomes a bottom sheet; labels collapse to short form at narrow widths.
- Polling (`POLL_MS = 5000`) must not cause flicker: recompute zones only when a new closed 5-min bar arrives; update the live-price relationship (touch/broken) on that same boundary, not on every tick.

### 4. Backend (minimal)
- Do not change response shapes. If `prevDayHigh/prevDayLow` are not already derivable from the `/day` warmup bars, add them to the existing response as optional fields computed generically in `tools/live_chart_yf.py` (null when the prior session is unavailable). No new data vendor; the yfinance stand-in limits remain (state this limitation in the UI source note if the app already shows one).
- No OI or volume-at-price is available from this source: the feature must not display or imply them.

## Testing (required, run them)
- `frontend/tests/orderBlocks.test.mjs` (`node --test`): table-driven synthetic bar fixtures for bullish and bearish cases: basic OB; no BOS (no zone); BOS without displacement (no zone); wick-only break (no zone); retest counting; broken on close beyond INV vs wick through (not broken); forming-candle exclusion; insufficient history (no zone, not zero); fewer than two liquidity candidates (`level2 = null`, `rr = null`, not 0); missing volume (`vwap = null`); missing tickSize (no buffer, not NaN); equal-highs detection; look-ahead test (results at bar t identical when future bars are removed); same results for live-incremental vs full-replay evaluation.
- **Cross-symbol genericity test:** run the detector over fixtures from at least 5 different symbols and price scales (e.g. ₹50, ₹800, ₹3,500 stocks; use stored/mock data) with the same params and assert no symbol-specific branch (grep-style assertion that no ticker string appears in `orderBlocks.js`).
- Registry/audit tests green; `npm run build` passes; add/extend a Python test only if backend fields are added.
- Verify in the browser (use the dev server preview): load Live Chart for 3 different symbols, toggle Order Blocks, confirm zones render, null fields show "—", day replay matches live logic, light/dark and mobile widths render, no console errors.

## Acceptance criteria
1. Toggle on → current zone plus earlier session zones render correctly on 3+ different symbols with zero symbol-specific code.
2. No zone is ever drawn from an unclosed candle; values with insufficient data are `null`/"—", never 0.
3. Registry audit and all `node --test` tests pass; production build passes.
4. Live polling and History/day replay yield identical zones for the same bars.
5. UI language is neutral (no advice); disclaimer present; existing patterns, forecast panel and polling behaviour are unchanged when the toggle is off.
6. Parameters live in one `DEFAULT_OB_PARAMS` object with a version; a short `docs`/comment block in `orderBlocks.js` states each rule exactly as implemented.

## Out of scope (do not build now)
Full-market ranking board, breadth/sector panels, SSE streaming, billing, journal, backtest CLI. (A later phase can add a backtest runner reusing `detectOrderBlocks` since it is pure.) Mention in your final report anything you could not verify, and any parameter you think needs backtesting before users rely on it.

When finished: summarize files changed, test output, and any deviations. Do not commit unless asked.
