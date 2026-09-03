# Qualitative Visualization — Manual-Upload Payload Audit

Scope: **manual document/PDF upload flow only** (`POST /api/v1/documents/analyse` →
`POST /api/v1/document-analysis/run` → `tools/document_analysis_engine.run_qualitative_analysis`
→ `tools/qualitative_engine.compute_*` under `tools/manual_mode.manual_mode()` → `tools/qualitative_db.write_qualitative`
→ `GET /api/v1/qualitative/{symbol}/{task_id}` → `frontend/src/views/DocumentAnalysis.jsx` → `frontend/src/components/QualCharts.jsx`).
No XBRL, automated web-research, or external-API ingestion code was read for logic changes and **none was modified**.

## 1–2. The 221 metrics and their assigned visualization

The full title → visualization mapping is `frontend/src/components/QualChartMapping.js` (221 entries,
one per Excel spec row). Not reproduced here field-by-field to avoid duplicating that file — open it
directly for the authoritative list. Section 4 below documents where the *assigned* visualization does
or doesn't match what manual-upload data can actually produce.

## 3–6. Renderable / partial / evidence-only / mismatch, by section

This is organized by section (B–U) rather than by individual row, because — confirmed by reading the
actual `compute_*` functions, not the Excel intent — **the real payload shape is overwhelmingly uniform
within each section**, and a per-row table would just repeat the same shape 10–20 times. Where a section
has real exceptions, they're called out.

### Common envelope (every sub-point)
`subpoint_id, title, available, rationale, pathway_results` (list of `{pathway_id, source, result, note}`,
almost always length 1 — sourcing metadata, not chartable data), plus `confidence_tag`/`retrieved_at`
merged in by `write_qualitative`/`read_qualitative`.

### Status semantics actually implemented (confirmed correct, no code change needed)
- `SINGLE_SOURCE`/`MULTI_SOURCE` → `VERIFIED` — a real value was found in the uploaded document(s).
- `SEARCH_INCONCLUSIVE`/`NOT_FOUND` → `NOT_DISCLOSED` — the uploaded document(s) were searched and the
  fact simply isn't in them. **This is the default, near-universal "not found" branch.**
- `DATA_MISSING`/`EXTERNAL_DATA_REQUIRED` → `DATA_MISSING` — the specific document type this sub-point
  needs (Corporate Governance Report, BRSR/ESG Report, Investor Presentation/Earnings Call Transcript,
  Corporate Actions History, Shareholding Pattern filing, etc.) was **never uploaded at all**. Distinct
  from `NOT_DISCLOSED` and correctly kept that way in the frontend status gate.
- `NOT_APPLICABLE` — sector-gated (S-series) or business-model-scoped rows.
- `INSUFFICIENT_DATA`, `NEEDS_REVIEW`/`CONFLICT_UNRESOLVED` — used sparingly, correctly distinct states.
- No code path anywhere in the traced range converts a missing/not-disclosed value to `0`/`false`.
  Confirmed by direct reading of ~180 compute_fn bodies across 4 independent traces.

### B — Management quality (20 sub-points, B.1.1–B.6.4)
Richest section for real structured data. Several sub-points carry genuine arrays:
- **B.1.1** (Past successes/failures): `initiatives` list + `successful_count`/`execution_score`.
- **B.1.2** (Management tenure): `executives: [{role, tenure_years}]` + `average_tenure_years`/`tenure_score`.
- **B.1.3** (Strategy relevance): `strategic_priorities`, `matched_areas` — named lists.
- **B.5.1** (Milestone execution): `years_covered` list + ratio/score.
- **B.5.3** (Strategic consistency): `theme_trend` — real per-year series.
- Everything else in B (pay structure, vesting, long-term orientation, leadership depth, succession,
  disclosure/communication quality, execution credibility, culture) is `*_count`/`*_pct`/`*_score` scalar
  pairs — genuinely chartable as comparison bars, progress bars, or rating bars, not composition unless a
  real pct pair exists.
- **Classification: A** (renderable) for all 20, using the shape-detection cascade already in
  `QualCharts.jsx` (`findWholeBreakdown`, `findCountComparison`, `find5PointScore`, etc.) — no chart type
  is hardcoded from the Excel spec; it's derived from whichever real fields are present.
- **Confirmed mismatch fixed:** B.2.2 "Equity ownership" only returns a single
  `management_ownership_pct` + `ownership_score` — **not** a promoter/public pair. The Excel spec's
  suggested 100%-stacked composition bar cannot be built from this payload without inventing the
  complement. Reassigned to a single-value progress bar (`QualChartMapping.js`).

### C — Governance / capital allocation (31 sub-points, C.1.1–C.8.4)
- Real arrays: **C.1.2/C.2.3** (`trend: [{quarter, promoter_pct/pledge_pct}]` — genuine quarterly
  time series), **C.3.1** (`matched_types` list), **C.6.1** (`years_covered`), **C.6.2**
  (`switch_by_year`), **C.7.3** (`buyback_years`), **C.7.4** (`years_paid`), **C.8.4** (`by_event`).
- Everything else is scalar count/pct/score pairs — chartable as comparison/progress/rating bars.
- **Classification: A** for all 31.
- `DATA_MISSING` with a real `required_document` fires only on **C.5.1** ("Corporate Governance
  Report") and **C.8.2** ("Corporate Actions History (BSE/NSE) - AGM/Postal Ballot Scrutinizer's
  Report") — both correctly surfaced via `payload.required_document` and the existing upload-button
  flow in `DocumentAnalysis.jsx`.

### D — Insider activity / pledging (17 sub-points, D.1.1–D.6.2)
- Real arrays: **D.2.3** (`repeat_buyers` — named list), **D.5.1** (`evidence_sentences`), **D.6.1**
  (`trend: [{quarter, pledge_pct}]` — genuine time series), **D.6.2** (`evidence` list).
- Everything else is scalar count/pct/score.
- **Classification: A** for all 17. **D.3.2** (Dilution) is the only sub-point in this range with a
  reachable `DATA_MISSING`/`required_document` ("Corporate Actions History (BSE/NSE)").

### E — Customer/supplier/accounting quality (18 sub-points, E.1.1–E.7.4)
- Real arrays: **E.4.1** and **E.5.1** (`trend`: 2-point YoY receivables/inventory series — genuinely
  chartable as a line, matches the Excel spec's line-chart recommendation exactly).
- Everything else (concentration %, ageing %, classification strings, count pairs) is scalar.
- **Classification: A** for all 18. No `DATA_MISSING`/`required_document` anywhere in this section —
  every E-series sub-point either finds a value in the AR or resolves to `NOT_DISCLOSED`.

### F — Competition / moat (11 sub-points, F.1.1–F.6.2)
- **Real named-list fields with no numeric weight**: F.1.1 `competitor_names`, F.1.3
  `strength_dimensions`, F.2.1 `barrier_dimensions`, F.4.1 `regulatory_barrier_dimensions`, F.4.2
  `trade_barrier_dimensions`, F.5.1 `presence_dimensions`, F.5.2 `import_dimensions`. Each is paired
  with its own `*_score`.
- **Confirmed bug found and fixed:** none of these named-list fields were recognized by any existing
  shape detector — they silently fell through to the generic evidence-text card, discarding real
  disclosed evidence (which competitors were named, which specific barriers were cited, etc.). Added
  `findNamedList` + `TagList` component (`QualCharts.jsx`); the expanded card now shows the score
  **and** the full named list together, never fabricating a percentage/count that was never disclosed.
- **F.3.2** (Price-war evidence): `op_margin_series` — a real up-to-8-point margin timeline, matches
  the Excel spec's line-chart recommendation.
- **Classification: A** for all 11 (was previously **D** for the 7 named-list ones — now fixed).

### G — Channel / distribution (7 sub-points, G.1.1–G.4.2)
- **G.1.1** "Channel mix" only returns `channels_identified` (named list) + `channel_mix_score` — **no
  per-channel percentage**. The Excel spec's 100%-stacked composition bar cannot be built without
  inventing shares. With the `findNamedList` fix above, this now renders as score + named channel list
  instead of a fabricated composition — same fix class as F.
- **G.1.2, G.2.1, G.3.1, G.3.2, G.4.2** have a reachable `DATA_MISSING` / `required_document`
  ("Investor Presentation or Earnings Call Transcript").
- **Classification: A/B** — A for score+evidence rendering; B (partial) whenever `DATA_MISSING` fires
  and the card correctly shows the "upload X" prompt rather than treating it as `NOT_DISCLOSED`.

### H–J — IP/tech, supply chain, regulatory/litigation/tax (31 sub-points)
**No array/list field exists anywhere in this range.** Every payload is a scalar `bool`/`int score`/enum
string. Confirmed by direct function-body reads across all ~31 sub-points.
- **Classification: A**, but the *renderable form* is always a single rating/risk bar, binary status
  card, or category badge — never a bar/timeline/composition, regardless of what the row's Excel-suggested
  visual implies. The existing shape-detection cascade already degrades correctly to these forms; no
  sub-point in this range needed a mapping change because the strict-branch failure path in `QualChart`
  already falls through to the same scalar-aware `AutoChart` cascade.
- Reachable `DATA_MISSING`: H.1.2, H.2.1, H.3.1, H.3.2, H.4.1, H.4.2, I.1.1, I.1.3, I.2.2, I.2.3, I.3.1
  (all → "Investor Presentation or Earnings Call Transcript"), J.5.2 (→ "BRSR/ESG Report").

### K, L — Macro/regulatory sensitivity, leverage/covenants (14 sub-points)
Scalar-only, same pattern as H–J. **One real code-quality note (backend, informational only — not
changed per scope rule):** every K/L sub-point except M.1.1/M.3.1 contains a dead `confidence_tag ==
"DATA_MISSING"` string reference in its rationale-building code that can never actually be assigned —
`confidence_tag` there is only ever `SEARCH_INCONCLUSIVE` or `SINGLE_SOURCE`. This doesn't cause a
frontend bug (the frontend only acts on the tag that's actually written), but it means these
`required_document` labels are cosmetic dead code. **Not touched — backend logic, out of this task's
scope; flagging only per the "report what's missing" instruction.**
- **Classification: A** for all 14 (scalar rating/risk-bar rendering).

### M — M&A / capital allocation framework (6 sub-points)
Scalar-only. `DATA_MISSING` is reachable only on **M.1.1** and **M.3.1** (→ "Corporate Actions History
(BSE/NSE)"). **Classification: A** for all 6.

### N–R — ESG/social, disclosure quality, group structure, management/financial-engineering red flags (63 sub-points)
Scalar-only across the board — confirmed no array field in this entire range. `DATA_MISSING` is common
here and mostly BRSR/ESG-Report- or Corporate-Actions-gated; correctly distinguished from `NOT_DISCLOSED`.
One stub worth flagging: **P.1.2** ("Disclosure consistency and timeliness") always returns
`SEARCH_INCONCLUSIVE` — its underlying filing-date source isn't wired into this workflow at all, so it
will show `NOT_DISCLOSED` for every company, always. Correct behavior for the frontend (an honest
"not disclosed" is right, since the code genuinely never finds a date) — not a frontend bug, but worth
knowing this row will never show data via manual upload.
**Classification: A** for all 63 (scalar rendering).

### S — Industry-specific applicability (16 sub-points, S.1.1–S.5.3)
Confirmed genuine applicability-gated: `is_sector_applicable(...)` decides `NOT_APPLICABLE` before any
scoring runs. Sector buckets: S.1 = banks/financials, S.2 = pharma, S.3 = auto, S.4 = IT/tech services,
S.5 = consumer/FMCG. **For any single company, ~12 of these 16 will correctly show `NOT_APPLICABLE`** —
this is expected, not a bug. The remaining ~4 (matching sector) render as scalar score cards.
**Classification: A** for all 16 — the applicability-status-card-first behavior the Excel spec calls for
is already correctly implemented (`binary_applicable` vizId → status gate → chart only if applicable).

### T, U — Tariff/currency sensitivity, management-risk disclosure quality (14 sub-points)
Scalar-only. U-series `DATA_MISSING` gated on Investor Presentation/Earnings Call Transcript/Corporate
Governance Report depending on sub-point. **Classification: A** for all 14.

### Category D — cannot be satisfied by manual upload at all, ever
Sub-points whose Excel-declared `primary_source` is a live market-data feed (`peer_universe`,
`crisil_scraper`, `commodity`, `screener`) are pre-filtered by
`document_analysis_engine._requires_external_source` **before the compute_fn is even called** and
permanently write `EXTERNAL_DATA_REQUIRED` → `DATA_MISSING` with a `required_document` describing an
external data feed no PDF upload can satisfy (peer-company market data, CRISIL rationale report,
commodity price data, peer screening data). This is correct, intentional behavior — the frontend already
shows these as `DATA_MISSING` status cards, not fabricated charts, and no code change was made or is
needed here. (The exact subset of the 221 rows affected wasn't enumerated line-by-line in this pass —
identifying it exhaustively requires cross-referencing each task's `primary_source` in the task registry,
which is a backend-only lookup outside this session's remaining scope; flagging as a known limitation of
this report rather than guessing.)

## 7. Files changed
- `frontend/src/components/QualCharts.jsx` — added `findNamedList` detector + `TagList` component;
  wired into `AutoChart`'s fallback cascade so named-category-list payloads (competitor names, channel
  types, barrier dimensions, etc.) render instead of silently collapsing to generic evidence text; score
  + named-list combo shown together in expanded view. Added `full` prop to every chart primitive
  (`StackedBar`, `ComparisonBars`, `RatingBar5`, `ProgressBar`, `EvidenceCard`, `Timeline`,
  `LineChartMini`, `VerticalBarChart`) so the expanded card shows all data with no artificial fixed-size
  clipping, while the collapsed row keeps its compact one-glance preview.
- `frontend/src/components/QualChartMapping.js` — corrected 24 chart-type assignments where the Excel
  spec's suggested visual didn't match what real manual-upload payload data actually supports (see
  section 3–6 above for the confirmed B.2.2 fix; the other 23 were corrected in an earlier pass against
  the Excel spec text itself, prior to this backend-payload audit).
- `frontend/src/views/DocumentAnalysis.jsx` — expanded qualitative cards now render the full-size chart
  (via the new `full` prop) above the evidence text, instead of text-only.

## 8. Confirmation: no unrelated ingestion pipeline touched
Only the three frontend files above were edited. `tools/qualitative_engine.py`,
`tools/document_analysis_engine.py`, `tools/manual_document_pipeline.py`, `tools/qualitative_db.py`,
`tools/manual_mode.py`, and `app.py` were **read only**, for the purpose of tracing real payload shapes —
no backend/XBRL/automated-ingestion/API code was modified.

## 9. Testing status
- `npx vite build` — clean, no errors, both times (before and after this pass).
- **Live browser verification was not completed.** The app's dev server requires an access password
  (`Restricted access` gate) that wasn't available in this session — I did not attempt to guess or
  bypass it. If you can supply it, or unlock the app another way, I can drive a real manual-upload
  qualitative card through the browser and confirm the rendering directly.
