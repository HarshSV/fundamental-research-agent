# DATA_REQUIREMENTS — for your own F&O order-block terminal

Source options listed are general knowledge as of my training; **verify current terms, pricing and API limits yourself** before committing. Nothing here is about what OrderBlock uses ([UNKNOWN]; they say only "licensed data vendors and broker interfaces").

## Fields
| Field | Type | Frequency | Needed for |
|---|---|---|---|
| Instrument master (symbol, token, lot size, expiry, segment, ISIN) | ref | daily | universe, lots sizing |
| F&O eligible stock list + sector map | ref | daily/monthly | universe, sector panel |
| Trading calendar (holidays, special sessions, timings) | ref | yearly + ad hoc | live/closed state |
| 1-min OHLCV per stock (cash, ideally also nearest-month future) | ts | 1 min | strength, VWAP, 5-min aggregation |
| 5-min OHLCV (aggregated from 1-min) | ts | 5 min | OB detection |
| Daily OHLC history ≥ 60 sessions | ts | daily | avg daily move |
| Corporate actions (split, bonus, dividend, ex-date, factor) | ref | daily | price adjustment |
| Previous close (adjusted) | num | daily | % change |
| Volume (per bar) and volume-at-price (derived from bars or ticks) | ts | 1 min | profile, VWAP |
| Open interest per future/option series | ts | 1 min (optional) | build-up context, liquidity score |
| Option chain (strikes, OI, IV, LTP) | ts | 1–5 min (optional, phase 2) | option-buyer view |
| Index levels (Nifty, Bank Nifty, Fin Nifty), India VIX | ts | 1 min | context |
| Event-risk flags (large unusual move, results/news) | derived | 1 min | exclusion |
| User, subscription, payment, journal, tags, watch state | app | realtime | product |

## Source options
| Option | Gives | Caveats |
|---|---|---|
| NSE/BSE public files (bhavcopy, F&O bhavcopy with OI, participant OI, corporate action lists, holiday list) | EOD OHLC, OI, lot sizes, calendars | End-of-day only; fine for history/backfill and reference data. Site terms restrict scraping/redistribution and have anti-bot measures; read NSE data terms. |
| NSE option-chain web pages | Delayed chain | Unofficial endpoints, rate-limited and unstable; not suitable for a paid product. |
| Broker APIs: Zerodha Kite Connect, Upstox, Angel One SmartAPI, Dhan, others | Live websocket ticks (LTP/volume/OI), historical 1-min candles, instrument dumps | Licensed for **your own account's use**; most prohibit redistributing data to third parties or building a data product on a retail key. Rate limits (e.g. websocket instrument caps, historical-API throttles), daily token re-login, some charge monthly. Check each ToS for "commercial/redistribution" clauses. |
| Licensed vendor / exchange-authorised redistributor (e.g. TrueData, Global Datafeeds, Accelpix, ICICI/other data resellers, or direct NSE data licence) | Real-time feeds with redistribution rights if contracted | Cost, contract, per-user/display-fee models and exchange approval for "vendor" status; this is the compliant route for a paid multi-user terminal. |

## Licensing and redistribution caveats (not legal advice)
1. Real-time exchange data is licensed IP; NSE/BSE require redistributors to be authorised, and display/non-display fees can apply. Showing live prices to paying subscribers is redistribution.
2. A personal broker API key almost never covers serving many end users. Using one for a commercial product risks key revocation and ToS breach.
3. Derived analytics (ranks, zones) still embed licensed data; some licences restrict how much raw data you may display. Confirm with the vendor whether derived-only display is permitted.
4. Delayed (e.g. 15-min) data usually has lighter terms but defeats a minute-level product.
5. Adjusted historical prices must follow exchange corporate-action rules; keep the raw and adjusted series separately.
6. Regulatory: SEBI rules on investment advice/research analysts apply if output reads as recommendations. Get a securities-law opinion on positioning and disclaimers.
7. Store only what you are licensed to store; honour retention limits.
