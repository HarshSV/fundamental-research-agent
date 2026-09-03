I'm building an AI-powered equity research tool called Navrist, and I want your help thinking through the team I need to hire. Here's exactly what it is and where it's headed — read this fully before answering.

## What Navrist is

Navrist is an internal fundamental equity research terminal for Indian listed companies, built for a professional trading/investment firm (also called Navrist). It's phase 1 of a larger AI-agent suite planned for later. It is explicitly NOT a generic stock screener or a "chat with your portfolio" toy — the design principle is "progressive disclosure, headline first, evidence one click away," and every number shown must be traceable back to the exact filing, page, and formula it came from. This is an internal research tool, not investment advice, used by people who need to trust the numbers.

## What it actually does today

1. **Fundamental Ratios** — a sector-aware ratio dashboard. Given a ticker, it pulls audited financial statements (income statement, balance sheet, cash flow — standalone and consolidated) primarily from Screener.in, with NSE/BSE and other fallbacks. It computes 50+ financial ratios (liquidity, efficiency, profitability, returns, leverage, valuation), tiers them by sector relevance (Core / Secondary / Different-Definition-Needed / Not-Applicable, based on a sector applicability matrix), and every ratio card shows its formula, source, confidence score, and a "how we calculated this" drawer.

2. **Qualitative Analysis** — AI-reasoned business analysis, organized into ~21 planned topics (I'm building them one at a time). Topic A, "Company strategy & business model," is done and covers 6 sub-points: business model clarity (single product vs portfolio, recurring vs cyclical revenue), competitive moat (brand/distribution/cost leadership/network effects/switching costs, each rated), revenue model quality (transactional vs recurring vs annuity, contract dynamics), product lifecycle stage (growth/maturity/commoditisation/decline, benchmarked vs industry growth), pricing power (ability to pass through cost inflation), and margin sustainability (structurally defensible margins vs one-off tailwinds — this one uses REAL computed EBITDA margin history, not just LLM guessing, with the LLM only judging causality). Each sub-point has: an AI-generated finding grounded in real data, a visual (donut chart, bar chart, trend line, or a "spectrum" indicator depending on the metric type — all fully hoverable), a formula, and a Primary/Secondary/Tertiary source citation trail (e.g. Annual Report → Investor Presentation → Screener.in, or CRISIL → ICRA → Screener peer comparison).

3. **Ask Navrist** — a floating Groq-backed chatbot for company-specific Q&A, currently general-purpose. I'm planning to extend it into genuine event-grounded reasoning: if someone asks "why did TCS stock fall," the system should detect the actual price-move window from real price history, retrieve real evidence for that window (news, concall commentary, sector-wide movement to separate stock-specific vs market-wide causes), and have the LLM answer ONLY from that retrieved evidence — never a plausible-sounding guess from its training data. This is scoped but not yet built; it's blocked on picking a news/event data source.

## Tech stack

- **Backend:** FastAPI (`app.py`) wrapping a LangGraph orchestration pipeline (`agent/stock_agent.py`) — three sequential nodes: fetch market data → LLM qualitative analysis → peer synthesis. JWT auth (single shared password today, admin-provisioned accounts planned).
- **Data sourcing:** Screener.in is the primary source (one HTML scrape replaces what used to be 6+ serial API calls). NSE/BSE scrapers for segment data, corporate announcements, XBRL filings. Angel One and yfinance exist as fallbacks only, used sparingly and deliberately — not the primary path.
- **LLM:** Groq (llama-3.3-70b primary, llama-3.1-8b-instant fallback for rate-limit resilience). No vector DB yet — retrieval is deliberately kept to keyword/section-based grounding over ingested documents (concall transcripts, filings) rather than embeddings, for now.
- **Database:** Supabase (Postgres) — precomputing ratios/financials there instead of recomputing on every request is an in-progress performance initiative.
- **Frontend:** React + Vite (recently migrated off a no-build-step CDN/Babel setup), Tailwind with a CSS-variable-driven design system so components theme automatically between light and dark mode. Custom hand-built SVG chart components (no charting library) — donut, trend line, bar, diverging bar, "spectrum" indicators — all designed to be hoverable across their entire area, not just at data points.

## Current state / known constraints

- Performance has been a real problem — full report generation used to take 8-9 minutes due to serial I/O (repeated yfinance calls, repeated Angel One re-authentication, sequential PDF downloads). This is actively being fixed: session caching, deduping redundant calls, parallelizing independent I/O, and a report-level cache.
- The qualitative analysis LLM schema had to be split into two focused calls instead of one giant one — a single oversized prompt/schema was causing the model to truncate output or confuse field shapes.
- Everything is being built with a strong bias toward correctness and traceability over cleverness — because this is used for real investment research, a wrong number or a hallucinated causal story is a real problem, not a cosmetic bug.
- This is a small/early-stage team. I'm the AI engineer building this from scratch. I've already scoped hiring a Backend/Data Engineer (owns the scraping/data pipeline, financial data correctness) and I'm considering a more junior, versatile "founding engineer" type who can eventually grow into AI/product work (prompt design, RAG, pattern detection across companies) rather than a narrow senior specialist, given this is a startup and budget/team size is small. Frontend and DevOps/infra are being handled in-house for now.

---

I need to hire more people. Based on everything above — what roles should I actually look for, and why?
