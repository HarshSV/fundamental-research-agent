# BUILD_PROMPT — "ZoneBoard": an original intraday F&O zone terminal

Paste everything below into Claude Code. This is MY design. It is inspired by the category of product, not a description of any competitor's backend (which is unknown).

---

## 1. Goal
Build a web terminal for Indian F&O stocks that, once per minute during NSE hours (09:15–15:30 IST), (a) scores every F&O stock for one-directional intraday strength, (b) ranks them into Bullish and Bearish boards (top 20 each), (c) detects order-block zones and liquidity levels on the top 20 per side from 5-minute candles, (d) shows market breadth and sector flow, and (e) lets a user size and journal trades.

### Non-goals
No order execution, no broker login, no personalised advice or "buy/sell" calls, no copying of any third-party text, branding, images or code, no scraping of exchange websites for live data, no auto-trading, no social/leaderboard features in v1. Original naming, visual identity and copy only.

## 2. Architecture (my design)
- **Ingestion workers** (Python 3.12, asyncio): a feed adapter interface `FeedAdapter` with implementations `ReplayFeed` (from stored files, used for dev/tests/backtests), `BrokerFeed` (licensed websocket, pluggable) and `VendorFeed`. Emits normalised ticks → 1-minute bars (OHLCV+OI). Idempotent writes, gap detection and backfill via historical API at open/restart.
- **Bar aggregator**: 1-min → 5-min bars; only *closed* bars are passed to detection.
- **Detection/ranking engine** (pure functions, no I/O, deterministic): runs on a minute tick; inputs are bars + reference data, outputs `Ranking`, `Setup[]`, `Breadth`, `SectorFlow`.
- **Time-series storage**: TimescaleDB (Postgres) hypertables for `bars_1m`, `bars_5m`, `setup_snapshots`. Reference/app data in the same Postgres.
- **Cache + pub/sub**: Redis holding the latest board snapshot, previous-minute ranks, and pub/sub channel for stream fan-out.
- **API layer**: FastAPI. REST for snapshots/journal/auth/billing; **Server-Sent Events** `/stream/board` for per-minute pushes (simpler than websockets for one-way data; websocket optional later). Per-user connection and rate limits.
- **Auth**: email magic link + Google OAuth; httpOnly session cookies with hashed server-side tokens; max N concurrent devices.
- **Billing**: Razorpay or Cashfree (hosted checkout + webhooks, signature verified, idempotent); plan = fixed-term access, no auto-renew in v1; entitlement table.
- **Frontend**: React + TypeScript + Vite, TanStack Query, lightweight-charts (candles) plus SVG overlays for zones. Light/dark theme, responsive (phone-first sheets, desktop multi-panel).
- **Ops**: Docker Compose for dev; one container per worker; Caddy or nginx TLS.

## 3. Detection logic (original, explicit, parameterised)
All parameters live in `config/detection.yaml` and are versioned; every stored setup records `params_version`.

**Definitions**
- Bars: 5-min closed candles of the current session, plus prior session's last N bars for swing context.
- Swing high (k=2): bar whose high exceeds the highs of the 2 bars on each side. Swing low symmetric. A swing is confirmed only after k later bars close.
- Opening range (OR): high/low of 09:15–09:30.
- ATR5 = mean true range of the last 14 closed 5-min bars. `body_avg` = mean absolute body of last 20 bars.

**Break of structure (BOS)**
- Bullish BOS at bar *i*: close[i] > most recent confirmed swing high (or OR high if no swing yet) AND no earlier close above it. Bearish: mirror with swing low / OR low.
- Displacement filter (all required): bar range[i] ≥ `disp_mult`×ATR5 (default 1.2) **or** the BOS bar leaves a fair-value gap (low[i+1] > high[i−1]) **or** close beyond the level by ≥ `body_avg`.

**Order block (OB)**
- Bullish OB: last *down-close* candle at or before the start of the displacement leg (search back ≤ `ob_lookback` = 10 bars, stopping at the previous swing low). Bearish: last *up-close* candle.
- Zone = [low, high] of that candle (wick-inclusive). `Z` = zone edge nearest current price direction: bullish Z = block high, bearish Z = block low (mid-point option via config `z_mode`).
- Invalidation level (`INV`): bullish = block low − `inv_buffer`×tick (default 1 tick); bearish = block high + buffer. Zone **broken** when a closed 5-min bar closes beyond INV.
- State machine: `FORMED → UNTOUCHED → RETESTED(n) → BROKEN`. A retest counts when a bar's range overlaps the zone then closes back on the trend side. Track `touch_count`; weight decays: score_zone = base × `0.7^(touch_count−1)`.
- Keep all of the day's zones; the "current" setup is the most recent non-broken zone on the stock's side.

**Liquidity levels**
- Candidates: confirmed swing highs/lows not yet closed through, equal highs/lows (two+ within `eq_tol`=0.05%), prior day high/low, day high/low, session open.
- Targets T1/T2 = nearest two candidates beyond Z in trade direction; downside ladder = next up to three levels the other way.
- `RR = (T2 − Z) / |Z − INV|` (bullish; mirror bearish). Flag `low_room` if RR < `rr_floor` (default 1.5). Never fabricate a level: if fewer than two candidates exist, leave null and `RR = null`.

**Strength and ranking**
- `move = (ltp − open) / open`; `adv = mean(|close−open|/open)` or ATR% over last 50 sessions of adjusted daily data (document which; default mean daily range%). `strength = move / adv`.
- One-sided filter: let `up = max(high_so_far − open)`, `down = max(open − low_so_far)`; for a bullish score require `up > 2×down` else score 0 (mirror for bearish). (This is a common-sense cleanliness filter; tune via backtest.)
- Rank bullish by strength desc, bearish by strength asc; percentile = share of universe weaker. Compute rank change vs previous minute.
- Picks: top 3 per side with ≤ 2 per sector, excluding event-risk (|move| > `event_mult`×adv and gap > X%, or manual flag).
- Alignment score (0–4): stock in top 20, sector sign agrees, breadth agrees (bull count vs bear count), price vs VWAP agrees.
- Do not output trade instructions; output measurements only.

**Backtest hooks**
- `engine.run(bars, params) -> Setup[]` is pure. `backtest/` replays stored 1-min history through `ReplayFeed`, then records for each setup: first-retest hit, MFE/MAE in R, outcome at T1/T2/INV/EOD, by params_version, side, alignment score, time-of-day. CLI: `python -m backtest run --from 2025-01-01 --to 2025-12-31 --params config/detection.yaml --report out/`. Report must include sample size and refuse to show hit-rates under n=30. Parameter sweeps via grid files. Guard against look-ahead: detection may only read bars closed at or before the evaluation timestamp (unit test enforces).

## 4. Data model (Postgres/Timescale)
`instrument(id, symbol, token, sector_id, lot_size, is_fno, active)`; `sector(id, name)`; `trading_day(date, status, open_time, close_time, note)`; `corp_action(instrument_id, ex_date, type, factor)`; `daily_bar(instrument_id, date, o,h,l,c,v, adj_factor)`; `bars_1m(instrument_id, ts, o,h,l,c,v, oi)` hypertable; `bars_5m(...)` hypertable; `ranking_snapshot(ts, instrument_id, side, strength, percentile, rank, rank_delta, is_pick, event_risk, rule_text)`; `setup(id, instrument_id, session_date, side, formed_ts, ob_low, ob_high, z, inv, t1, t2, rr, state, touch_count, params_version)`; `setup_event(setup_id, ts, kind)`; `market_snapshot(ts, bull_count, bear_count, leading_sector, lagging_sector)`; `app_user`, `session`, `plan`, `entitlement(user_id, plan_id, starts, ends)`, `payment(provider_ref, status, amount, raw_event)`; `journal_trade(id, user_id, instrument, side, qty, entry, exit, from_date, to_date, setup_tag, habit_tag, note)`; `audit_log`.

## 5. API routes
`GET /api/v1/market` (breadth, sectors, leading/lagging) · `GET /api/v1/board?side=bull|bear` · `GET /api/v1/stocks/{symbol}` (card + setups + levels) · `GET /api/v1/stocks/{symbol}/candles?tf=5m&date=` · `GET /api/v1/search?q=` · `GET /stream/board` (SSE) · `POST/GET/PATCH/DELETE /api/v1/journal` · `GET /api/v1/journal/summary` (calendar, by setup/tag) · `POST /api/v1/risk/size` (capital, risk %, Z, INV, lot size → qty/lots) · auth: `/auth/google`, `/auth/magic`, `/auth/logout` · billing: `POST /billing/checkout`, `POST /billing/webhook` · `GET /healthz`, `/metrics`. Every response carries `as_of` and `data_status` (`live|delayed|closed|holiday`).

## 6. Frontend screens
1. **Terminal home**: top market strip (dot plot of all stocks by day %, bull/bear counts, leading/lagging sector), sector panel (avg move + per-stock cells), Bullish and Bearish boards (20 cards each with rank, %, rank-delta, mini volume profile), picks highlighted.
2. **Setup popup / bottom sheet**: header, rank/percentile, rule text, OB range, Z, INV, T1/T2, RR, VWAP, 5-min chart with zone box, level lines, earlier zones faded, next/prev stock, copy-to-risk-calculator.
3. **Search**: Cmd/Ctrl+K palette.
4. **Risk calculator**, 5. **Journal** (form, P&L calendar heatmap, by setup/tag), 6. **Account/billing**, 7. **Learn** (own original content), 8. **Risk & disclaimer screen** — shown on first sign-in (must be accepted and logged with timestamp), linked in footer: not advice, no SEBI registration claim unless true, F&O loss statistics citing the SEBI studies, data may be delayed/wrong, past movement is not prediction.
Unknown/null values render as "—", never as 0.

## 7. Milestones and acceptance criteria
1. **Repo + replay feed + storage.** Accept: load one historical day for 200 symbols via `ReplayFeed`; 1m/5m bars match source totals; tests green.
2. **Strength & ranking engine.** Accept: golden-file test on a fixture day; corporate-action fixture shows no inflated score; one-sided filter unit-tested; rank deltas correct.
3. **Detection engine (BOS/OB/liquidity/RR).** Accept: hand-labelled 30-chart fixture set with ≥ 90% agreement on OB location; look-ahead test passes; nulls handled.
4. **API + Redis + SSE.** Accept: 1,000 concurrent SSE clients, p95 snapshot < 150 ms, minute tick-to-client < 3 s on replay.
5. **Frontend terminal + popup (desktop and mobile).** Accept: Lighthouse a11y ≥ 90; popup opens < 300 ms from cache; refresh doesn't reset scroll.
6. **Auth + billing + entitlements.** Accept: webhook replay is idempotent; expired plan loses live data; device limit enforced.
7. **Journal + risk sizing.** Accept: multi-day trades; lot-rounding matches the worked example in tests.
8. **Backtest harness + report.** Accept: reproducible report for a sample year with n shown; params versioned.
9. **Live data adapter (licensed).** Accept only after the data licence is signed (see DATA_REQUIREMENTS.md); reconnect/backfill chaos test.
10. **Hardening + launch checklist.**

## 8. Testing, observability, limits
- Tests: unit (pure engine), property tests (no look-ahead, monotonic ranks), golden days, API contract tests, Playwright E2E, load test (k6), webhook signature tests.
- Observability: structured JSON logs, Prometheus metrics (feed lag, bars missing, tick→publish latency, engine runtime, SSE clients), Sentry, alerts on feed gap > 90 s in market hours, dead-man's switch at 09:20.
- Rate limiting: per-IP and per-user token bucket at the edge and in FastAPI; SSE max 2 connections/user; login throttling; webhook allowlist.
- Security: CSP with nonces, HSTS, CSRF tokens, secrets in env/secret manager, audit log for admin.
- Compliance: disclaimers as above; no performance claims or testimonials about profits; legal review before charging.
