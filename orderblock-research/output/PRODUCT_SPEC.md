# PRODUCT_SPEC — OrderBlock (order-block.com), public surface only

Analysis date: 2026-10-13. Tags: **[OBSERVED]** seen on a public page/response, **[INFERRED]** reasoned (evidence stated), **[UNKNOWN]** not determinable publicly. All copy below is paraphrased. No login, no /app, /api or /auth calls were made; robots.txt was read first and obeyed (`Disallow: /app, /api/, /auth/`).

## 1. Overview
- [OBSERVED] A subscription web terminal for Indian F&O traders that ranks every F&O stock (200+) once a minute and shows the 20 strongest bullish and 20 strongest bearish names, each with a marked order-block zone and liquidity levels.
- [OBSERVED] Operated by "Options Oracle" (schema.org legalName, Gujarat, India); bundles a trading journal, learning videos and a moderated community.
- [OBSERVED] Positions itself as analytics software, not advice: not SEBI-registered as adviser, research analyst, PMS or broker; no trade execution; no broker login.
- [OBSERVED] Target user: intraday/short-term Indian equity-derivatives traders, full-time (faster scan) and part-time (first-hour only).
- [OBSERVED] Claims: "2000+ traders", 4.9 average / 60 reviews (landing), 4.8/5 (bio page) — self-reported, unverified. Updates every minute; board live 09:15–15:30 IST; last close shown on holidays/weekends.

## 2. Features (landing + changelog)
| # | Feature | Description (own words) | Screen |
|---|---|---|---|
| F1 | Order Block charts | Per-stock chart with the zone boxed, plus support/resistance and liquidity levels | Popup / chart sheet |
| F2 | Liquidity board | Bullish and Bearish boards, top 20 each, ranked every minute | Home/terminal |
| F3 | Market X-ray (market picture) | Every F&O stock as a dot at its day move; bull/bear counts; leading and lagging sector | Top strip |
| F4 | Breadth bar | Count of stocks up vs down | Top strip |
| F5 | Sector flow panel | Sectors ranked by average strength of constituents, with per-stock up/down cells | Side panel |
| F6 | Top picks | Three strongest per side, max two per sector, event-risk excluded | Home |
| F7 | Rank-change markers | Places moved since prior minute; highlight on entering top 10 | Board rows |
| F8 | Trading journal | Log trades (symbol, side, qty, entry, exit, from/to date, note, setup/habit tags); P&L calendar heatmap; P&L by setup | Member area |
| F9 | Learning videos | Short lessons with saved progress | Member area |
| F10 | Community | Moderated posting area | Member area |
| F11 | Guest Login | WhatsApp number + 4-digit code preview | Login |
| F12 | Light/dark theme, mobile layout | Sun/moon switch; full terminal on phones | All |
[OBSERVED] for all rows (landing, /updates, blog).

## 3. Pricing
- [OBSERVED] Single plan, "6 Months + 6 Free": ₹7,999 for 12 months (struck-through ₹28,999, "save 72%", marketed ~₹22/day). Includes terminal, liquidity, community, learning videos, journal, phone+desktop.
- [OBSERVED] Plans do not auto-renew (terms); refunds not available after purchase (refund policy); access bound to one Gmail; limited concurrent devices (terms); payments via Cashfree (UPI/cards/netbanking, checkout page).
- [UNKNOWN] Other tiers, discounts, limits per tier — only one tier is public.

## 4. Glossary
| Term | My definition | How the product/blog uses it |
|---|---|---|
| Order block (OB) | Last opposite-colour candle before a forceful move that closes beyond a recent swing high/low | Drawn from finished 5-min candles; one box per break of structure [OBSERVED] |
| Zone / Z | Area/price level carried forward from the block where price may react | Z = the level the setup is built around; shaded band extends right [OBSERVED] |
| S1 / R1 | Invalidation level just beyond the far edge of the block | Bullish: S1 below; bearish: R1 above. A 5-min close beyond it ends the setup [OBSERVED] |
| R1/R2 (bull), S1/S2 (bear) | Next levels in the direction of the move | Swing highs/lows not yet closed through, day extreme, opposing block [OBSERVED] |
| S2–S4 / R2–R4 (amber dotted) | Levels met on the way, for deeper retraces | Drawn on chart [OBSERVED] |
| R:R | Room from Z to second target ÷ risk from Z to invalidation | e.g. 1:2.7 [OBSERVED] |
| Rank / pXX · #n/N | Percentile and position on its side of the board | `p99.8 · #1/130` [OBSERVED] |
| Rule | Why a stock is or isn't a pick | PICK · BULLISH #1, NOT PICKED · sector cap / outside top 3 [OBSERVED] |
| Strength score | Directional move from open ÷ average daily move | Published formula; zero if not one-sided (>2× other side) [OBSERVED] |
| Liquidity | Untested highs/lows where stop orders cluster (equal highs/lows) | Targets placed at liquidity where in range [OBSERVED] |
| Liquidity sweep / trap | Price takes the stops then reverses from the zone | Educational concept [OBSERVED] |
| Breadth | Counts of bullish vs bearish stocks | Chooses the side to focus on [OBSERVED] |
| Sector flow | Average strength of a sector's stocks | Cells green/red per stock [OBSERVED] |
| Long/short build-up, OI | Not found as defined terms in the crawled pages (OI is mentioned in the FAQ as a liquidity-score input) | [OBSERVED] absence; OI role in score [OBSERVED] FAQ |
| VWAP | Volume-weighted average price for the day | Bull setups above, bear below [OBSERVED] |
| Conv (CONV) | Shown as a number with five dots in mockup; meaning not defined in text | [UNKNOWN] |
| Event risk | Unusually large fall flagged amber, gets no levels | [OBSERVED] |
| Contenders | The 40 glowing stocks (20 per side) | [OBSERVED] |
| Retest | Price returning to the zone; first is cleanest, later weaker | [OBSERVED] |
| FVG | 3-candle gap in a fast move; used only as proof the move was real | [OBSERVED] |

## 5. User workflow (blog playbook)
1. [OBSERVED] After ~09:20 read the market picture: bull/bear counts, leading/lagging sector.
2. Pick a side; skip the other on one-sided days.
3. Shortlist from the 20-per-side board; start with the three picks.
4. Open a stock's popup; read RANK, RULE, price vs Z, Z→S1 risk, R:R, VWAP (10-second read).
5. Wait for price to return to the zone (first retest); judge on 5-min closes.
6. Four-point alignment check: stock, sector, breadth, VWAP (4 = full attention, 3 = smaller, ≤2 pass).
7. Size: risk ≤ ~1% of capital ÷ (Z−S1) → round down to lots; set daily loss limit.
8. Log in the journal with setup and habit tags; weekly review. Re-check market at ~11:30 and 13:30.

## 6. UI spec
See section 9 (mockup-based) and the Phase 5 note there.

## 7. Changelog timeline and architectural implications
| Date | Version | Change | Implication |
|---|---|---|---|
| 30 Mar 2026 | 1.0 | Launch: Bull/Bear boards, 1-min refresh, Google sign-in | [INFERRED] OAuth + minute scheduler |
| 14 Apr | 1.1 | Fills in seconds at 9:15; backfill session if opened late | [INFERRED] per-minute bars persisted/recomputable from stored 1-min data |
| 29 Apr | 1.2 | Sector flow panel | [INFERRED] static symbol→sector map |
| 14 May | 1.3 | Corporate-action-adjusted history before range calc | [INFERRED] stored daily history + adjustment factors |
| 3 Jun | 1.4 | Trading journal | [INFERRED] relational CRUD per user |
| 24 Jun | 2.0 | Redesign; "recalculated within seconds of each minute's close" | [INFERRED] faster in-memory compute pass |
| 16 Jul | 2.1 | Rank-change markers | [INFERRED] previous-minute rank snapshot retained |
| 6 Aug | 2.2 | Videos + community | [INFERRED] video host (CSP allows Bunny/mediadelivery) |
| 27 Aug | 2.3 | Holiday/special-session (Muhurat) calendar | [INFERRED] trading-calendar table |
| 18 Sep | 2.4 | Breadth bar | derived aggregate |
| 25 Sep | 2.5 | Mobile terminal; Guest Login via WhatsApp OTP | [INFERRED] WhatsApp messaging provider |
| 26 Sep | 2.6 | Bearish board ordering, journal From/To dates | — |
| 28 Sep | 2.7 | Market-picture dot strip | — |
| 30 Sep | 2.8 | All day's zones kept on chart | [INFERRED] zones stored per day, not just latest |
| 7 Oct | 2.9 | Up to three extra levels in popup; hover/tap popup | — |
All dates/changes [OBSERVED]; implications as marked.

## 8. Tech-stack fingerprint (passive)
- [OBSERVED] Origin: `Via: 1.1 Caddy` (Caddy reverse proxy); HTTP/3 advertised (Alt-Svc); gzip; `Vary: Cookie`; public pages `Cache-Control: public, max-age=60` (HTML), 300 (JS), 3600 (robots).
- [OBSERVED] Security headers: HSTS 2 yrs + includeSubDomains, nonce-based CSP (self + jsDelivr hls.js, Google Fonts, Bunny CDN, mediadelivery/YouTube iframes, form-action to accounts.google.com), COOP same-origin, X-Frame-Options SAMEORIGIN, nosniff, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy denying camera/mic/geo/payment.
- [OBSERVED] No Set-Cookie on public GETs (cookie names/attributes for session/CSRF/theme described in privacy policy only; not observed).
- [OBSERVED] Frontend: server-rendered HTML, three deferred vanilla scripts (`core.js`, `site.js`, `a.js`) and two CSS files with content-hash `?v=` cache-busting; no Next/Nuxt/React/Vue/Svelte/htmx markers; no sourcemap references; no manifest, no service worker; Inter Tight + JetBrains Mono from Google Fonts; JSON-LD (Organization, WebSite, SoftwareApplication). [INFERRED] hand-rolled server-rendered site with vanilla JS.
- [OBSERVED] Third parties on public landing (Playwright log, hosts/types only): only order-block.com, fonts.googleapis.com, fonts.gstatic.com. No analytics, chat, error-tracking or payment scripts on public pages. Privacy policy states first-party analytics only.
- [OBSERVED] Served `core.js` contains client code for an `EventSource` (Server-Sent Events) stream and 60-second polling timers; neither was invoked on public pages and no endpoint was called. [INFERRED] the signed-in terminal uses SSE push plus minute polling (not WebSocket).
- [OBSERVED] Checkout page names Cashfree as payment gateway; Google OAuth for sign-in; WhatsApp OTP via a messaging provider (policy).
- [OBSERVED] DNS: Cloudflare nameservers; A record 13.200.188.210; no Cloudflare response headers (no cf-ray), so [INFERRED] DNS-only (not proxied) pointing to the origin. [INFERRED, medium] that IP range belongs to AWS Mumbai (ap-south-1) — not verified by WHOIS.
- [OBSERVED] TLS: Let's Encrypt (CN=YE2), cert valid 5 Sep–4 Dec 2026 (auto-renewed, 90-day).
- [UNKNOWN] Backend language/framework, database, queue, ingestion, detection and ranking code, data vendor identity. Plausible (my reasoning, not fact): Python/Go service with in-memory per-minute compute (medium); a relational DB for users/journal (high); a time-series or columnar store for 1-min bars (medium); a licensed vendor/broker websocket feed (high, because policy says "licensed data vendors and broker interfaces"); Redis-like cache (low-medium).

## 9. Screen-by-screen UI spec
**Phase 5 status:** `/input/screenshots/` was empty, so your own logged-in captures were NOT analyzed. The below comes from three public marketing mockups on the landing page (board, zones, pulse), tagged [OBSERVED-MOCKUP]. Re-run Phase 5 once you add your screenshots. Mockup values may be sample data; treat all numbers as unknown.

1. **Market picture strip (top)** [OBSERVED-MOCKUP]: horizontal axis ≈ −4% to +4%; each F&O stock a dot, red left/green right; ringed dots for picks; counts "BULLISH 130 / BEARISH 80" at right; callouts "LEADING SECTOR" and "LAGGING SECTOR" with % move.
2. **Sector panel (left column)** [OBSERVED-MOCKUP]: sector name, avg % move, row of small cells green/red per constituent; sorted by strength; vertical scale marks.
3. **Board (stock card grid)** [OBSERVED-MOCKUP]: Bullish (green) section above Bearish (red). Cards: ticker, % move, rank number 01–07, price tag on dashed line, volume-at-price horizontal histogram with the zone band highlighted; larger cards for picks (1–3) with avatar initials and five-dot indicator.
4. **Setup card / popup** [OBSERVED-MOCKUP]: header (initials badge, ticker, sector, sparkline); last price, day % and abs change; table: RANK, CONV (number + 5 dots), VWAP, OB range, Z/S1 (or Z/R1), R1/R2 (or S1/S2), R:R, RULE (PICK · BULLISH #1). Chart: candles 5-min, boxed OB, shaded zone to right, labelled R1/R2/S1, amber dotted S2–S4, dashed VWAP, faint boxes/lines for earlier setups, time axis 10:00–15:00. BULL/BEAR conveyed by green/red theming and the rule label.
5. **Inferred interactions** [INFERRED from changelog/blog, not seen in UI]: hover (desktop)/tap (mobile) opens popup; step to next stock; search any name (Ctrl+K is **[UNKNOWN]** — not stated publicly); theme toggle (changelog [OBSERVED]); 1-minute auto-refresh without scroll reset [OBSERVED in changelog].

### Data fields per component
| Component | Fields (type) | Update |
|---|---|---|
| Market picture | symbol(str), pct_change_day(float), side(enum), is_pick/contender/event_risk(bool), counts(int) | 1 min |
| Sector panel | sector(str), avg_strength(float), constituents[{symbol, up(bool)}] | 1 min |
| Board row | symbol, ltp, pct, rank, rank_delta(int), strength, sparkline[float] | 1 min |
| Popup | percentile, rank/N, rule(str), OB low/high, Z, S1/R1, R1/R2 or S1/S2, S2–S4, R:R, VWAP, conviction(0–100?), candles[OHLCV 5-min], prior zones[] | 1 min levels; 5 min OB |
| Volume profile | price_bin, volume | 1 min |

## 10. Observed / Inferred / Unknown summary
See the table at the end of the final summary message in chat and `SOURCES.md`. Key items:
| Item | Tag |
|---|---|
| Strength formula (move from open ÷ avg daily move, 2× one-sidedness filter, ~50-day average) | [OBSERVED] (disclosures) |
| OB uses finished 5-min candles; close beyond swing/first-15-min range; gap or ≥ avg-candle move required; invalid on 5-min close beyond far edge | [OBSERVED] (blog) |
| Order-block detection applied only to the top 20 per side | [OBSERVED] (blog) |
| Exact swing-lookback, "average candle" window, conviction formula, liquidity-score formula, target selection | [UNKNOWN] |
| SSE push in terminal | [INFERRED] |
| AWS Mumbai hosting | [INFERRED] |
| Backend stack, DB, vendor | [UNKNOWN] |
| Ctrl+K search, popup field list from user captures | [UNKNOWN] (no screenshots provided) |
| Reviews/user counts accuracy | [UNKNOWN] |
