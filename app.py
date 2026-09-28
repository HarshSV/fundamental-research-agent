import os
import re
import sys

# Fix TLS trust BEFORE any HTTPS call. On Windows behind a TLS-inspecting
# firewall/AV (common in India) this makes requests + curl_cffi (yfinance/NSE)
# verify against the machine's own trusted roots. No-op on the Linux cloud box.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import tools.ssl_bootstrap  # noqa: E402  (must run before requests/yfinance/Angel)

import asyncio
import concurrent.futures
import threading
import requests
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.stock_agent import app as app_graph
from tools.pdf_generator import StockReportGenerator
import auth


app = FastAPI(
    title="AI Agent Orchestration Backend",
    description="FastAPI Web Server wrapping LangGraph stock research orchestration layer.",
    version="1.0.0"
)

# Configure CORS Middleware settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits requests from Next.js frontends and other local ports
    allow_credentials=True,
    allow_methods=["*"],  # Permits all standard methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Permits all request headers
)

# Ensure runtime directories exist before mounting (a fresh clone has neither,
# and StaticFiles raises at startup if its directory is missing).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(_BASE_DIR, "exports"), exist_ok=True)
os.makedirs(os.path.join(_BASE_DIR, "logs"), exist_ok=True)

# Mount exports directory to serve PDF reports static files
app.mount("/exports", StaticFiles(directory=os.path.join(_BASE_DIR, "exports")), name="exports")
app.mount("/frontend", StaticFiles(directory=os.path.join(_BASE_DIR, "frontend-dashboard")), name="frontend")

# Mount the Vite production build's hashed assets (JS/CSS/images) when present.
# The build (npm run build in ./frontend) emits to ./frontend/dist with an /assets
# folder; the served index.html references those with absolute /assets/* URLs.
_STATIC_DIR = os.path.join(_BASE_DIR, "frontend", "dist")
_STATIC_ASSETS = os.path.join(_STATIC_DIR, "assets")
if os.path.isdir(_STATIC_ASSETS):
    app.mount("/assets", StaticFiles(directory=_STATIC_ASSETS), name="assets")

# Static dictionary of top 100+ Indian stocks with symbol and name
_REGISTRY_READY = threading.Event()

STOCK_REGISTRY = [
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Limited"},
    {"symbol": "INFY", "name": "Infosys Limited"},
    {"symbol": "SBIN", "name": "State Bank of India"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Limited"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Limited"},
    {"symbol": "ITC", "name": "ITC Limited"},
    {"symbol": "LT", "name": "Larsen & Toubro Limited"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited"},
    {"symbol": "AXISBANK", "name": "Axis Bank Limited"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Limited"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Limited"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Limited"},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Limited"},
    {"symbol": "NTPC", "name": "NTPC Limited"},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Limited"},
    {"symbol": "TITAN", "name": "Titan Company Limited"},
    {"symbol": "COALINDIA", "name": "Coal India Limited"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Limited"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Limited"},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation Limited"},
    {"symbol": "WIPRO", "name": "Wipro Limited"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Limited"},
    {"symbol": "TECHM", "name": "Tech Mahindra Limited"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Limited"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Limited"},
    {"symbol": "BAJAJ-AUTO", "name": "Bajaj Auto Limited"},
    {"symbol": "LTIM", "name": "LTIMindtree Limited"},
    {"symbol": "CIPLA", "name": "Cipla Limited"},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited"},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Limited"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Limited"},
    {"symbol": "TATACONSUM", "name": "Tata Consumer Products Limited"},
    {"symbol": "HINDALCO", "name": "Hindalco Industries Limited"},
    {"symbol": "BRITANNIA", "name": "Britannia Industries Limited"},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Limited"},
    {"symbol": "NESTLEIND", "name": "Nestle India Limited"},
    {"symbol": "GRASIM", "name": "Grasim Industries Limited"},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp Limited"},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Limited"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank Limited"},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Limited"},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Limited"},
    {"symbol": "SBILIFE", "name": "SBI Life Insurance Company Limited"},
    {"symbol": "HDFCLIFE", "name": "HDFC Life Insurance Company Limited"},
    {"symbol": "UPL", "name": "UPL Limited"},
    {"symbol": "SHRIRAMFIN", "name": "Shriram Finance Limited"},
    {"symbol": "ADANIGREEN", "name": "Adani Green Energy Limited"},
    {"symbol": "ADANIPOWER", "name": "Adani Power Limited"},
    {"symbol": "ZOMATO", "name": "Zomato Limited"},
    {"symbol": "TRENT", "name": "Trent Limited"},
    {"symbol": "DMART", "name": "Avenue Supermarts Limited"},
    {"symbol": "TATAPOWER", "name": "Tata Power Company Limited"},
    {"symbol": "IOC", "name": "Indian Oil Corporation Limited"},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Limited"},
    {"symbol": "DLF", "name": "DLF Limited"},
    {"symbol": "VBL", "name": "Varun Beverages Limited"},
    {"symbol": "SIEMENS", "name": "Siemens Limited"},
    {"symbol": "RECLTD", "name": "REC Limited"},
    {"symbol": "PFC", "name": "Power Finance Corporation Limited"},
    {"symbol": "UNIONBANK", "name": "Union Bank of India"},
    {"symbol": "IDFCFIRSTB", "name": "IDFC First Bank Limited"},
    {"symbol": "IRFC", "name": "Indian Railway Finance Corporation Limited"},
    {"symbol": "JIOFIN", "name": "Jio Financial Services Limited"},
    {"symbol": "YESBANK", "name": "YES Bank Limited"},
    {"symbol": "PNB", "name": "Punjab National Bank"},
    {"symbol": "BANKBARODA", "name": "Bank of Baroda"},
    {"symbol": "CANBK", "name": "Canara Bank"},
    {"symbol": "GAIL", "name": "GAIL (India) Limited"},
    {"symbol": "BEL", "name": "Bharat Electronics Limited"},
    {"symbol": "NHPC", "name": "NHPC Limited"},
    {"symbol": "SAIL", "name": "Steel Authority of India Limited"},
    {"symbol": "NMDC", "name": "NMDC Limited"},
    {"symbol": "GMRINFRA", "name": "GMR Airports Infrastructure Limited"},
    {"symbol": "IOB", "name": "Indian Overseas Bank"},
    {"symbol": "BANKINDIA", "name": "Bank of India"},
    {"symbol": "CENTRALBK", "name": "Central Bank of India"},
    {"symbol": "UCOBANK", "name": "UCO Bank"},
    {"symbol": "IDBI", "name": "IDBI Bank Limited"},
    {"symbol": "INDUSTOWER", "name": "Indus Towers Limited"},
    {"symbol": "LICI", "name": "Life Insurance Corporation of India"},
    {"symbol": "IRCTC", "name": "Indian Railway Catering and Tourism Corporation Limited"},
    {"symbol": "LODHA", "name": "Macrotech Developers Limited"},
    {"symbol": "PHOENIXLTD", "name": "The Phoenix Mills Limited"},
    {"symbol": "PRESTIGE", "name": "Prestige Estates Projects Limited"},
    {"symbol": "GODREJPROP", "name": "Godrej Properties Limited"},
    {"symbol": "OBEROIRLTY", "name": "Oberoi Realty Limited"},
    {"symbol": "SOBHA", "name": "Sobha Limited"},
    {"symbol": "BRIGADE", "name": "Brigade Enterprises Limited"},
    {"symbol": "COLPAL", "name": "Colgate-Palmolive (India) Limited"},
    {"symbol": "MARICO", "name": "Marico Limited"},
    {"symbol": "DABUR", "name": "Dabur India Limited"},
    {"symbol": "GODREJCP", "name": "Godrej Consumer Products Limited"},
    {"symbol": "JUBLFOOD", "name": "Jubilant FoodWorks Limited"}
]

_NSE_NAMES_CACHE = os.path.join(_BASE_DIR, "cache", "nse_company_names.json")
_NSE_NAMES_TTL = 7 * 24 * 3600  # refresh weekly


def load_nse_company_names() -> dict:
    """
    Map every listed NSE symbol -> its full company name using NSE's public
    EQUITY_L.csv. This gives proper "preview names" (e.g. MAFATIND ->
    "Mafatlal Industries Limited") for the whole universe, not just the curated
    top-100. Cached on disk for a week; best-effort (returns {} on failure).
    """
    import json as _json
    import time as _time
    # Serve fresh-enough disk cache first.
    try:
        if os.path.exists(_NSE_NAMES_CACHE) and _time.time() - os.path.getmtime(_NSE_NAMES_CACHE) <= _NSE_NAMES_TTL:
            with open(_NSE_NAMES_CACHE, "r", encoding="utf-8") as fh:
                cached = _json.load(fh)
                if cached:
                    print(f"[HTTP] Loaded {len(cached)} NSE company names from cache.")
                    return cached
    except Exception:
        pass

    import csv as _csv
    import io as _io
    urls = [
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://www1.nseindia.com/content/equities/EQUITY_L.csv",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/csv,*/*",
    }
    names = {}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200 or not resp.text:
                continue
            reader = _csv.DictReader(_io.StringIO(resp.text))
            for row in reader:
                sym = (row.get("SYMBOL") or "").strip().upper()
                nm = (row.get("NAME OF COMPANY") or "").strip()
                if sym and nm:
                    names[sym] = nm
            if names:
                print(f"[HTTP] Fetched {len(names)} NSE company names from {url}.")
                break
        except Exception as e:
            print(f"[HTTP WARNING] NSE names fetch failed from {url}: {e}")

    if names:
        try:
            os.makedirs(os.path.dirname(_NSE_NAMES_CACHE), exist_ok=True)
            with open(_NSE_NAMES_CACHE, "w", encoding="utf-8") as fh:
                _json.dump(names, fh)
        except Exception:
            pass
    return names


def load_scrip_master_async():
    global STOCK_REGISTRY
    try:
        print("[HTTP] Loading active NSE equity scrips from Angel One OpenAPIScripMaster...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            scrip_master = response.json()
            # Filter for NSE EQ instruments
            nse_symbols = {}
            for inst in scrip_master:
                if inst.get('exch_seg') == 'NSE' and inst.get('symbol', '').endswith('-EQ'):
                    sym = inst.get('name', '').strip().upper()
                    if sym:
                        nse_symbols[sym] = True
            
            # Full company names for the whole NSE universe (proper "preview names").
            nse_names = load_nse_company_names()

            # Merge with top 100+ stock names
            existing_symbols = {item['symbol'].upper(): item for item in STOCK_REGISTRY}

            merged_registry = []
            # Keep existing symbols with curated company names first
            for sym, item in existing_symbols.items():
                merged_registry.append(item)
                if sym in nse_symbols:
                    del nse_symbols[sym]

            # Add all other NSE symbols, with their full company name when known
            # (falls back to the symbol itself if NSE names were unavailable).
            for sym in sorted(nse_symbols.keys()):
                merged_registry.append({"symbol": sym, "name": nse_names.get(sym, sym)})

            STOCK_REGISTRY = merged_registry
            named = sum(1 for it in merged_registry if it["name"] != it["symbol"])
            print(f"[HTTP] Autocomplete registry enriched dynamically with {len(STOCK_REGISTRY)} NSE symbols "
                  f"({named} with full company names).")
    except Exception as e:
        print(f"[HTTP WARNING] Dynamic scrip master load failed: {e}")
    finally:
        # Unblock any search/resolve requests that were waiting on the full
        # universe - even on failure, so we don't hang forever on just the
        # curated ~100-stock list (better degraded than stuck).
        _REGISTRY_READY.set()

def warm_live_scraper_async():
    """Log in to Angel + prime the scrip-master cache in the background at startup,
    so the first user who asks Ask Navrist for a live price doesn't pay that cold-
    start cost on their request (that was a big chunk of the perceived latency)."""
    try:
        scraper = get_live_scraper()
        # A throwaway resolve forces the scrip-master load/cache now.
        scraper._resolve_symbol("RELIANCE")
        print("[HTTP] Live-quote scraper warmed (Angel session + scrip master primed).")
    except Exception as e:
        print(f"[HTTP WARNING] Live scraper warmup failed (will lazy-init on demand): {e}")


@app.on_event("startup")
def startup_event():
    # Every `/api/v1/*` ratio endpoint runs via `asyncio.to_thread`, which
    # shares ONE process-wide default ThreadPoolExecutor (Python's default
    # size is only min(32, cpu_count+4)). The Overview page fires 20-30 of
    # these in parallel on load; a single slow "AI research" call (Groq
    # qualitative analysis, several minutes, especially on a rate-limit
    # fallback) occupies one of those same threads for its whole duration.
    # Once concurrent load saturates the pool, every ratio tile queues
    # behind it and the page looks fully hung - not just slow - even though
    # nothing has crashed. Raising the pool size is a stopgap (the real fix
    # is the perf rework already planned) so ratio fetches always have a
    # free thread regardless of what else is running.
    asyncio.get_event_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=64))
    threading.Thread(target=load_scrip_master_async, daemon=True).start()
    threading.Thread(target=warm_live_scraper_async, daemon=True).start()
    threading.Thread(target=_precompute_loop, daemon=True).start()
    threading.Thread(target=_ratio_precompute_once, daemon=True).start()

@app.get("/api/search-symbols")
def search_symbols(q: str = "", _: dict = Depends(auth.require_session)):
    """Ranked autocomplete: symbol-starts-with (what a ticker search means)
    ranks above name-starts-with, which ranks above a bare substring match
    anywhere. The OLD version only checked "query in symbol/name" with no
    ranking at all - typing "U" matched every company whose NAME contained
    a "u" anywhere (e.g. "Reliance INdUstries", "Tata ConsUltancy") and
    returned them in raw registry order, so RELIANCE/TCS/HINDUNILVR/LT/
    SUNPHARMA (the curated list's first few entries) always won regardless
    of query, never actual U-prefixed companies like UPL/ULTRACEMCO."""
    query = q.strip().upper()
    if not query:
        return []
    # Wait for the full NSE universe to load (background fetch at startup)
    # before searching, so an early query doesn't silently miss everything
    # outside the curated ~100-stock seed list. Bounded so a slow/failed
    # fetch still serves the curated list rather than hanging the request.
    _REGISTRY_READY.wait(timeout=15)
    starts_symbol, starts_name, contains = [], [], []
    for item in STOCK_REGISTRY:
        sym = item["symbol"].upper()
        name = item["name"].upper()
        if sym.startswith(query):
            starts_symbol.append(item)
        elif name.startswith(query):
            starts_name.append(item)
        elif query in sym or query in name:
            contains.append(item)
    results = starts_symbol + starts_name + contains
    return results[:10]

# Define request schemas
class ResearchRequest(BaseModel):
    symbol: str

class ReportRequest(BaseModel):
    ticker: str = None
    symbol: str = None

class LoginRequest(BaseModel):
    password: str


# --- Authentication endpoints ---------------------------------------------
@app.post("/api/auth/login")
def login(request: LoginRequest):
    """Validate the shared site password and return a JWT session token."""
    if not auth.verify_site_password(request.password):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    token = auth.create_access_token()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_hours": auth.ACCESS_TOKEN_EXPIRE_HOURS,
    }

@app.get("/api/auth/me")
def read_me(_: dict = Depends(auth.require_session)):
    """Confirm the supplied session token is valid (used on app load)."""
    return {"authenticated": True}

def resolve_symbol_from_registry(query_symbol: str) -> str:
    cleaned = query_symbol.strip().upper()
    if not cleaned:
        return cleaned

    # Same startup race as search_symbols: wait for the full universe so a
    # request that lands before the background load finishes still resolves
    # a name like "Gopal Snacks" to its symbol instead of falling through to
    # the raw, unresolved input further down.
    _REGISTRY_READY.wait(timeout=15)

    # Check if there is an exact symbol match in STOCK_REGISTRY
    for item in STOCK_REGISTRY:
        if item["symbol"].upper() == cleaned:
            return item["symbol"]
            
    # Check for direct shorthand aliases
    aliases = {
        "SBI": "SBIN",
        "ICICI": "ICICIBANK",
        "HDFC": "HDFCBANK",
        "AXIS": "AXISBANK",
        "KOTAK": "KOTAKBANK",
        "BAJAJ": "BAJFINANCE",
        "L&T": "LT",
        "JUBILANT": "JUBLFOOD",
    }
    if cleaned in aliases:
        print(f"[Symbol Resolver] Mapped shorthand '{cleaned}' to alias: {aliases[cleaned]}")
        return aliases[cleaned]

    # Check if the query matches the name or symbol in registry. Whole-word
    # match only (not raw substring): a raw `cleaned in name` check let an
    # unrelated manual-upload symbol (e.g. a synthetic slug like
    # "PRIMEFRESHLIM" minted for a company with no registry match, see
    # tools/manual_document_pipeline.py's _slug_symbol) accidentally collide
    # with a completely different company whenever it happened to appear as
    # a substring of that company's symbol/name - silently routing every
    # later qualitative/document-analysis lookup for the uploaded company to
    # the wrong ticker's cached data. Whole-word boundaries keep genuine
    # partial-name lookups (e.g. "TATA MOTORS" typed without "LTD") working
    # while ruling out mid-word/mid-token accidents.
    cleaned_pattern = rf"\b{re.escape(cleaned)}\b"
    for item in STOCK_REGISTRY:
        sym = item["symbol"].upper()
        name = item["name"].upper()
        if cleaned == sym or cleaned == name or re.search(cleaned_pattern, sym) or re.search(cleaned_pattern, name):
            print(f"[Symbol Resolver] Auto-resolved query '{cleaned}' to: {sym}")
            return sym
            
    return cleaned

@app.get("/")
def read_root():
    """Serve the dashboard SPA at the site root so the deployed domain shows the app.

    Prefers the Vite production build (./static/index.html). Falls back to the legacy
    single-file dashboard (./frontend-dashboard/index.html) when the build is absent,
    so a fresh checkout without `npm run build` still serves the old app.
    """
    from fastapi.responses import FileResponse
    built_index = os.path.join(_STATIC_DIR, "index.html")
    legacy_index = os.path.join(_BASE_DIR, "frontend-dashboard", "index.html")
    # index.html must never be cached: it's the only file that maps to the
    # build's content-hashed /assets/index-<hash>.js. A cached copy keeps
    # pointing at a stale hash, so a rebuilt frontend appears unchanged in
    # the browser no matter how many times it's rebuilt. The hashed assets
    # themselves are immutable and stay cacheable.
    _no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    if os.path.exists(built_index):
        return FileResponse(built_index, headers=_no_cache)
    if os.path.exists(legacy_index):
        return FileResponse(legacy_index, headers=_no_cache)
    return {"status": "online", "description": "Dashboard file not found; API is running."}

@app.get("/api/health")
def health_check():
    """Lightweight liveness probe for load balancers / uptime monitors."""
    return {"status": "online", "service": "navrist-research-terminal"}

# Reuse a single Angel scraper across live-quote polls so we don't re-login (TOTP)
# on every request. Lazily created and thread-safe.
_live_scraper = None
_live_scraper_lock = threading.Lock()

def get_live_scraper():
    global _live_scraper
    if _live_scraper is None:
        with _live_scraper_lock:
            if _live_scraper is None:
                from tools.angel_scraper import AngelDataScraper
                _live_scraper = AngelDataScraper()
    return _live_scraper

@app.get("/api/quote")
def live_quote(symbol: str = "", _: dict = Depends(auth.require_session)):
    """Real-time LTP/OHLC for the dashboard's live-price ticker (cheap, pollable)."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    try:
        q = get_live_scraper().fetch_live_quote(sym)
    except Exception as e:
        return {"symbol": sym, "ltp": None, "source": "unavailable", "error": str(e)}
    ltp = q.get("ltp")
    prev_close = q.get("close")
    change = change_pct = None
    if ltp is not None and prev_close:
        try:
            change = round(ltp - prev_close, 2)
            change_pct = round((ltp - prev_close) / prev_close * 100, 2)
        except Exception:
            pass
    q["change"] = change
    q["change_pct"] = change_pct
    return q

@app.get("/api/live-chart/{symbol}")
def live_chart_candles(symbol: str, interval: str = "5m", period: str | None = None, _: dict = Depends(auth.require_session)):
    """OHLCV candles for the live-charts view (lightweight-charts). Sourced
    from yfinance polling ONLY as a stand-in until Axis Direct's RAPID API
    (tools/axis_feed_ws.py) or ICICI Breeze is provisioned - swap the
    provider call below, response shape stays the same."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    from tools.live_chart_yf import get_candles
    candles = get_candles(sym, interval=interval, period=period)
    if candles is None:
        return {"symbol": sym, "candles": [], "source": "unavailable"}
    return {"symbol": sym, "candles": candles, "source": "yfinance"}

@app.get("/api/live-chart/{symbol}/day")
def live_chart_day_candles(symbol: str, date: str, interval: str = "5m", _: dict = Depends(auth.require_session)):
    """Full trading-day (9:15-3:30 IST) candles for one calendar date - the
    History view's data source. `date` is 'YYYY-MM-DD'. Returns an empty
    list (source="unavailable") for a non-trading day or a date beyond
    yfinance's intraday retention window for the given interval - never a
    substituted nearby day."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    from tools.live_chart_yf import get_candles_for_date
    candles = get_candles_for_date(sym, date, interval=interval)
    if candles is None:
        return {"symbol": sym, "date": date, "candles": [], "source": "unavailable"}
    return {"symbol": sym, "date": date, "candles": candles, "source": "yfinance"}

@app.get("/api/live-chart/{symbol}/latest")
def live_chart_latest(symbol: str, _: dict = Depends(auth.require_session)):
    """Polling ticker (LTP/change) for the top of the live-chart view."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    from tools.live_chart_yf import get_latest
    latest = get_latest(sym)
    if latest is None:
        return {"symbol": sym, "ltp": None, "source": "unavailable"}
    latest["symbol"] = sym
    return latest

@app.post("/api/research")
async def research_endpoint(request: ResearchRequest, _: dict = Depends(auth.require_session)):
    """
    POST endpoint that accepts a stock symbol, executes the LangGraph
    orchestration workflow, and returns the final dictionary payload.
    """
    incoming_symbol = resolve_symbol_from_registry(request.symbol)
    if not incoming_symbol:
        raise HTTPException(status_code=400, detail="Stock symbol must not be empty.")
        
    print(f"\n[HTTP POST /api/research] Request received for symbol: {incoming_symbol}")
    
    # Initialize the workflow state schema
    initial_state = {
        'symbol': incoming_symbol,
        'raw_financial_data': {},
        'business_score': 0,
        'qualitative_analysis': {},
        'peer_synthesis_data': {},
        'verdict': 'PENDING'
    }
    
    try:
        print(f"[HTTP] Invoking LangGraph workflow for ticker: {incoming_symbol}...")
        final_state = await asyncio.to_thread(app_graph.invoke, initial_state)
        print(f"[HTTP] Workflow completed successfully for symbol: {incoming_symbol}")
        
        # Log to CSV Database (Skip saving PDF on disk)
        try:
            from tools.db_logger import StockDatabaseLogger
            StockDatabaseLogger.log_research(final_state)
        except Exception as db_err:
            print(f"[HTTP WARNING] Database logging failed: {db_err}")
            
        return final_state
    except Exception as e:
        print(f"[HTTP ERROR] Workflow execution failed for {incoming_symbol}: {e}")
        return {
            "error": f"Workflow execution failed: {str(e)}",
            "symbol": incoming_symbol,
            "verdict": "ERROR"
        }

# --- Report cache -----------------------------------------------------------
# The full pipeline (multi-source scrape + several LLM calls) is expensive, so a
# repeat lookup of the same symbol used to redo everything. This disk cache makes
# repeat lookups return INSTANTLY (like Screener serving a pre-computed page).
# 6h TTL keeps data reasonably fresh; delete cache/reports/<SYMBOL>.json to force
# a rebuild for one stock.
_REPORT_CACHE_DIR = os.path.join(_BASE_DIR, "cache", "reports")
_REPORT_CACHE_TTL = 6 * 3600


def _report_cache_path(symbol: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (symbol or "").upper())
    return os.path.join(_REPORT_CACHE_DIR, f"{safe}.json")


def _read_report_cache(symbol: str):
    import json as _json
    import time as _time
    try:
        p = _report_cache_path(symbol)
        if os.path.exists(p) and _time.time() - os.path.getmtime(p) <= _REPORT_CACHE_TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return _json.load(fh)
    except Exception as e:
        print(f"[HTTP] report cache read skipped for {symbol}: {e}")
    return None


def _write_report_cache(symbol: str, state: dict):
    import json as _json
    try:
        os.makedirs(_REPORT_CACHE_DIR, exist_ok=True)
        with open(_report_cache_path(symbol), "w", encoding="utf-8") as fh:
            _json.dump(state, fh, default=str)
    except Exception as e:
        print(f"[HTTP] report cache write skipped for {symbol}: {e}")


# --- Precompute (background) -------------------------------------------------
# On-demand generation (below) still has real LLM/data-fetch latency baked in -
# there's no way around that for a symbol nobody's asked for yet. But the
# common case is a small, predictable set of symbols (the default watchlist)
# that get opened over and over. Precomputing those in the background means
# whoever opens RELIANCE/TCS/etc. gets the instant cache-hit path instead of
# waiting through the live pipeline. Mirrors frontend/src/views/Landing.jsx's
# DEFAULT_WATCHLIST - keep these two lists in sync if either changes.
_PRECOMPUTE_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK',
                         'LT', 'ITC', 'SBIN', 'BHARTIARTL', 'MARUTI']
# Re-run just under the cache TTL so a symbol's cache never actually expires
# under normal operation - the background refresh always lands first.
_PRECOMPUTE_INTERVAL_SECONDS = int(_REPORT_CACHE_TTL * 0.8)

# {"symbol", "name"} pairs for the ratio precompute worker (tools/precompute_worker.py),
# built from the same watchlist symbols + the names already in STOCK_REGISTRY.
_PRECOMPUTE_WATCHLIST_COMPANIES = [
    {"symbol": sym, "name": next((c["name"] for c in STOCK_REGISTRY if c["symbol"] == sym), sym)}
    for sym in _PRECOMPUTE_WATCHLIST
]


def _precompute_watchlist_once():
    """One pass: (re)generate any watchlist symbol whose cache is missing or
    stale. Sequential on purpose - this runs against the same free-tier LLM
    keys real user traffic uses, so hammering all 10 symbols in parallel would
    just compete with (and slow down) whoever's actually using the app."""
    for symbol in _PRECOMPUTE_WATCHLIST:
        if _read_report_cache(symbol) is not None:
            continue  # still fresh - nothing to do
        try:
            print(f"[precompute] Generating {symbol}...")
            state = app_graph.invoke({
                'symbol': symbol,
                'raw_financial_data': {},
                'business_score': 0,
                'qualitative_analysis': {},
                'peer_synthesis_data': {},
                'verdict': 'PENDING',
            })
            _write_report_cache(symbol, state)
            print(f"[precompute] {symbol} cached.")
        except Exception as e:
            print(f"[precompute] {symbol} failed (will retry next cycle): {e}")


def _precompute_loop():
    import time as _time
    # Small initial delay so this doesn't compete with the scrip-master /
    # live-scraper warmup already happening on startup.
    _time.sleep(30)
    while True:
        _precompute_watchlist_once()
        _time.sleep(_PRECOMPUTE_INTERVAL_SECONDS)


def _ratio_precompute_once():
    """
    Seeds Supabase's `ratio_values` table (via tools/precompute_worker.py)
    with the Annual-Report-sourced ratios for the default watchlist, so the
    Fundamental Ratios tab reads from the DB (near-instant) instead of doing
    a live PDF download+parse per ratio. Runs ONCE per process start, not in
    a loop - unlike qualitative analysis, audited annual-report figures don't
    go stale on an hours timescale, and the worker is resumable (skip_done)
    so re-running it on every restart is cheap: already-done (symbol,
    ratio_no) pairs are skipped via Supabase's `refresh_jobs` table.
    """
    import time as _time
    # Stagger well after the LLM report precompute (30s) and its own first
    # cycle so this doesn't compete for network/CPU with that at startup.
    _time.sleep(90)
    try:
        from tools.precompute_worker import run as run_ratio_precompute
        print("[ratio_precompute] Seeding Supabase ratio_values for the default watchlist...")
        run_ratio_precompute(_PRECOMPUTE_WATCHLIST_COMPANIES, workers=1)
        print("[ratio_precompute] Done.")
    except Exception as e:
        print(f"[ratio_precompute] Skipped/failed (falls back to live PDF parsing as before): {e}")


@app.get("/api/v1/qualitative/{symbol}")
def get_qualitative_all(symbol: str, _: dict = Depends(auth.require_session)):
    """Read-only: every persisted qualitative_values row for this symbol,
    straight from the DB. Does NOT trigger /generate-report or recompute
    anything - if nothing has been computed yet for this symbol, this
    returns an empty list rather than kicking off a live research run."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    from tools.supabase_client import get_client
    from tools.qualitative_db import to_user_facing_status, _QUALITATIVE_LOGIC_VERSION
    from tools.qualitative_task_registry import TASK_BY_ID
    sb = get_client()
    try:
        r = sb.table("qualitative_values").select("*").eq("symbol", sym).execute()
        results = []
        for row in (r.data or []):
            # A subpoint_id no longer in the active registry (e.g. renamed/
            # removed in a past refactor, orphaned in the DB) must never
            # reach the frontend as a card with no title/rationale - it
            # isn't one of the current 242 batch-enabled KPIs at all.
            if row.get("subpoint_id") not in TASK_BY_ID:
                continue
            payload = row.get("payload") or {}
            # A row written before the current logic version is stale by
            # definition (see qualitative_db.read_qualitative's identical
            # check) - this endpoint previously read straight from the DB,
            # bypassing that check entirely, so a stale pre-fix result
            # could still be served to the frontend even after a logic fix
            # shipped. Dropped here rather than served with a misleading
            # "up to date" status; the next full/partial recompute
            # (force=True) will overwrite it.
            if payload.get("_logic_version") != _QUALITATIVE_LOGIC_VERSION:
                continue
            row = dict(row)
            row["internal_status"] = row.get("confidence_tag")
            row["confidence_tag"] = to_user_facing_status(row.get("confidence_tag"))
            results.append(row)
        return {"symbol": sym, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@app.get("/api/v1/qualitative/runs/{run_id}")
def get_qualitative_run_status(run_id: int, _: dict = Depends(auth.require_session)):
    """Read-only: a batch run's progress - run-level status plus a
    per-job-status breakdown (e.g. {"COMPLETED": 1240, "PENDING": 1233,
    ...}), for the "1,240/2,473 companies completed" style progress UI.

    Registered BEFORE /api/v1/qualitative/{symbol}/{task_id}: FastAPI/
    Starlette matches path routes in registration order, and both routes
    have the same two-segment shape (/qualitative/X/Y), so this literal
    "runs" route must come first or a request like /qualitative/runs/1
    gets swallowed by the generic {symbol}/{task_id} route instead
    (confirmed by testing - this ordering is load-bearing, not stylistic)."""
    from tools.supabase_client import get_client
    sb = get_client()
    try:
        run = sb.table("qualitative_research_runs").select("*").eq("run_id", run_id).limit(1).execute()
        if not run.data:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
        jobs = sb.table("qualitative_research_jobs").select("status").eq("run_id", run_id).execute()
        breakdown = {}
        for j in (jobs.data or []):
            breakdown[j["status"]] = breakdown.get(j["status"], 0) + 1
        return {"run": run.data[0], "job_status_breakdown": breakdown, "jobs_total": len(jobs.data or [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@app.get("/api/v1/qualitative/{symbol}/{task_id}")
def get_qualitative_task(symbol: str, task_id: str, _: dict = Depends(auth.require_session)):
    """Read-only: the persisted qualitative_values row for one
    (symbol, task_id), e.g. GET /api/v1/qualitative/HINDUNILVR/E.1.1.
    Returns available=False (not a fabricated result) if nothing has been
    computed yet."""
    sym = resolve_symbol_from_registry(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    from tools.qualitative_engine import read_qualitative
    payload = read_qualitative(sym, task_id)
    if payload is None:
        return {"symbol": sym, "task_id": task_id, "available": False}
    return {"symbol": sym, "task_id": task_id, **payload}


# --- Upload Documents (Annual Report + NSE/BSE XBRL) -----------------------
# Alternative to the automatic BSE/NSE fetch: the user uploads their own
# Annual Report (required) and NSE/BSE XBRL filing (optional), clicks
# Analyse, and the EXISTING Fundamental (all 68) and Qualitative (A-U)
# engines run exactly as they do for an automatically-fetched company -
# both uploads are wired into the same shared caches those engines already
# read from (cache/ar_pdfs+ar_text for the AR, tools/nse_xbrl.py's manual
# override for the XBRL), so no per-ratio/per-subpoint changes are needed.
# See tools/manual_document_pipeline.py.

@app.post("/api/v1/documents/analyse")
async def documents_analyse_endpoint(
    annual_report: UploadFile = File(...),
    xbrl: UploadFile = File(None),
    shareholding_pattern: UploadFile = File(None),
    additional_filings: list[UploadFile] = File(None),
    insider_trading_filings: list[UploadFile] = File(None),
    corporate_actions_filings: list[UploadFile] = File(None),
    corporate_governance_report: UploadFile = File(None),
    brsr_esg_report: UploadFile = File(None),
    investor_presentation: UploadFile = File(None),
    earnings_call_transcript: UploadFile = File(None),
    credit_rating_report: UploadFile = File(None),
    other_supporting_documents: list[UploadFile] = File(None),
    symbol: str = Form(""),
    _: dict = Depends(auth.require_session),
):
    """Upload Annual Report (required) + NSE/BSE XBRL + Shareholding
    Pattern filing (both required-for-Fundamental but not enforced here -
    the frontend gates Analyse on them) + the optional Qualitative
    supporting documents (Corporate Governance Report, BRSR/ESG Report,
    Investor Presentation, Earnings Call Transcript, Credit Rating Report,
    Other Supporting Documents) and analyse. None of the qualitative
    documents are required, and none block analysis if missing - each is
    saved and tagged with its document_type (tools/manual_document_pipeline.py:
    QUALITATIVE_DOCUMENT_TYPES) purely for the coverage summary at this
    stage; wiring them into individual A-U compute_fn's is separate,
    larger follow-up work, not done by this endpoint. If `symbol` isn't
    given, the company is detected from the Annual Report itself. Returns
    the resolved symbol so the frontend can open the existing full
    dashboard (Fundamental all-68 + Qualitative A-U) for it - this
    endpoint does not compute ratios itself, it only wires the uploaded
    documents into the sources those existing engines read from."""
    ar_content = await annual_report.read()
    if not ar_content:
        raise HTTPException(status_code=400, detail="Annual Report is required.")
    xbrl_content = await xbrl.read() if xbrl is not None else None
    shareholding_content = await shareholding_pattern.read() if shareholding_pattern is not None else None

    qualitative_documents = {}
    single_qual_slots = {
        "corporate_governance_report": corporate_governance_report,
        "brsr_esg_report": brsr_esg_report,
        "investor_presentation": investor_presentation,
        "earnings_call_transcript": earnings_call_transcript,
        "credit_rating_report": credit_rating_report,
    }
    for doc_type, upload in single_qual_slots.items():
        if upload is not None:
            content = await upload.read()
            if content:
                qualitative_documents[doc_type] = (upload.filename, content)
    if other_supporting_documents:
        for i, f in enumerate(other_supporting_documents):
            content = await f.read()
            if content:
                key = "other_supporting_document" if i == 0 else f"other_supporting_document_{i}"
                qualitative_documents[key] = (f.filename, content)
    # Insider Trading / Regulation 7(2) and Corporate Announcements /
    # Corporate Actions each get their own real document_type (previously
    # both silently landed in `additional_filings` below, which never
    # tagged a document_type NOR ever extracted their text - confirmed
    # real: those files sat at status='uploaded' forever, invisible to
    # both the Document Coverage panel and every qualitative compute_fn
    # that searches this document type's cached text, even though the
    # user had genuinely uploaded them).
    if insider_trading_filings:
        for i, f in enumerate(insider_trading_filings):
            content = await f.read()
            if content:
                key = "insider_trading_disclosures" if i == 0 else f"insider_trading_disclosures_{i}"
                qualitative_documents[key] = (f.filename, content)
    if corporate_actions_filings:
        for i, f in enumerate(corporate_actions_filings):
            content = await f.read()
            if content:
                key = "corporate_actions" if i == 0 else f"corporate_actions_{i}"
                qualitative_documents[key] = (f.filename, content)

    from tools.manual_document_pipeline import analyse_documents
    result = analyse_documents(
        annual_report.filename, ar_content,
        xbrl_filename=(xbrl.filename if xbrl is not None else None), xbrl_content=xbrl_content,
        shareholding_filename=(shareholding_pattern.filename if shareholding_pattern is not None else None),
        shareholding_content=shareholding_content,
        symbol=(resolve_symbol_from_registry(symbol) or symbol.strip().upper() or None) if symbol else None,
        qualitative_documents=qualitative_documents,
    )
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    if result.get("annual_report", {}).get("error"):
        raise HTTPException(status_code=422, detail=result["annual_report"]["error"])

    if additional_filings:
        sym = result["symbol"]
        from tools.manual_document_pipeline import save_upload
        for f in additional_filings:
            content = await f.read()
            if content:
                try:
                    save_upload(sym, f.filename, content, display_name=f"Additional Filing: {f.filename}")
                except Exception as e:
                    print(f"[documents_analyse] additional filing '{f.filename}' not stored: {e}")

    return result


@app.post("/api/v1/documents/{symbol}/add-supporting")
async def add_supporting_document_endpoint(
    symbol: str,
    required_document: str = Form(...),
    file: UploadFile = File(...),
    _: dict = Depends(auth.require_session),
):
    """Adds ONE supporting document to an ALREADY-analysed company, then
    re-runs the qualitative engine (force=True on every sub-point) so any
    Data Missing card whose required_document this satisfies gets
    recomputed immediately - lets the user fill one specific gap straight
    from the dashboard's per-card Upload button instead of re-submitting
    the entire Upload Documents flow. `required_document` is the exact
    free-text label shown on the card (set per-KPI in qualitative_engine.py)
    - resolved server-side to one of tools.manual_document_pipeline.
    QUALITATIVE_DOCUMENT_TYPES via map_required_document_to_type, so the
    frontend never needs its own copy of that mapping."""
    from tools.manual_document_pipeline import save_upload, process_supporting_document, map_required_document_to_type
    document_type = map_required_document_to_type(required_document)
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        doc_id = save_upload(sym, file.filename, content, document_type=document_type)
        extraction = process_supporting_document(doc_id)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Upload failed: {e}")
    if extraction.get("error"):
        raise HTTPException(status_code=422, detail=extraction["error"])

    from tools.document_analysis_engine import run_qualitative_analysis
    try:
        qual_result = run_qualitative_analysis(sym)
    except Exception as e:
        print(f"[add_supporting_document] {sym}: qualitative re-run failed: {e}")
        qual_result = {"error": str(e)}
    return {"symbol": sym, "document_type": document_type, "extraction": extraction, "qualitative": qual_result}


@app.post("/api/v1/document-analysis/run")
async def document_analysis_run_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Runs the NEW document-analysis engine (tools/document_analysis_engine.py)
    for a symbol already analysed via /api/v1/documents/analyse - Fundamental
    (own broad extraction over the uploaded AR/XBRL) + Qualitative (the
    existing A-U framework's own compute_fn's). Separate from the old
    per-ratio fetching pipeline entirely."""
    sym = resolve_symbol_from_registry((request or {}).get("symbol", "")) or (request or {}).get("symbol", "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    name = (request or {}).get("name")
    from tools.document_analysis_engine import run_full_analysis
    try:
        return run_full_analysis(sym, name)
    except Exception as e:
        # Never report success on an empty/failed analysis - surface the
        # real cause (e.g. a migration not yet applied) so the frontend
        # shows an actual error instead of "Analysis Complete" with nothing in it.
        print(f"[document_analysis] [RUN] {sym}: FAILED - {e}")
        raise HTTPException(status_code=422, detail=f"Document analysis failed: {e}")


@app.get("/api/v1/qualitative-framework")
def qualitative_framework_endpoint(_: dict = Depends(auth.require_session)):
    """Static: {task_id: {title, section, visualization_rule}} for every
    defined A-U sub-point - lets the frontend label/group qualitative
    results and pick a chart type without duplicating the Python-only
    registry. Never changes at runtime; cheap to compute per request."""
    from tools.qualitative_task_registry import TASK_REGISTRY
    return {
        t["task_id"]: {"title": t["title"], "section": t["section"], "visualization_rule": t.get("visualization_rule")}
        for t in TASK_REGISTRY if t["defined"]
    }


@app.get("/api/v1/document-analysis/{symbol}")
def document_analysis_get_endpoint(symbol: str, _: dict = Depends(auth.require_session)):
    """Fundamental results from the NEW document-analysis engine, grouped by
    category. Qualitative results are read via the existing
    /api/v1/qualitative/{symbol} endpoint - same table, unchanged."""
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    from tools.document_analysis_engine import get_fundamental_results
    return {"symbol": sym, "fundamental": get_fundamental_results(sym)}


@app.get("/api/v1/documents/coverage/{symbol}")
def documents_coverage_endpoint(symbol: str, _: dict = Depends(auth.require_session)):
    """Which qualitative supporting-document categories were actually
    uploaded for this symbol (see tools/manual_document_pipeline.py:
    QUALITATIVE_DOCUMENT_TYPES), and which are still missing - a real query
    against uploaded_documents, never a guess. Lets the frontend show a
    document coverage summary alongside the Qualitative tab."""
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    from tools.manual_document_pipeline import get_document_coverage
    return {"symbol": sym, "coverage": get_document_coverage(sym)}


@app.post("/api/v1/manual/upload-auto")
async def manual_upload_auto_endpoint(file: UploadFile = File(...), _: dict = Depends(auth.require_session)):
    """Upload with no company chosen up front - the Annual Report already
    says who it's for, so we detect the company name from the document
    itself and resolve (or register) its symbol automatically."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    from tools.manual_document_pipeline import save_upload_auto
    result = save_upload_auto(file.filename, content)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.post("/api/v1/manual/upload")
async def manual_upload_endpoint(
    symbol: str = Form(...),
    file: UploadFile = File(...),
    _: dict = Depends(auth.require_session),
):
    """Uploads the Annual Report and parses it (wires it into the shared AR
    cache). Synchronous for simplicity - a single PDF parse is seconds, not
    minutes. Does not extract anything yet; the user searches for specific
    metrics afterward via /api/v1/manual/{symbol}/search."""
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol required.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    from tools.manual_document_pipeline import save_upload, process_document
    try:
        document_id = save_upload(sym, file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = process_document(document_id)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return {"symbol": sym, "document_id": document_id, **result}


@app.post("/api/v1/manual/{symbol}/search")
def manual_search_endpoint(symbol: str, request: dict, _: dict = Depends(auth.require_session)):
    """Searches the latest processed Annual Report for one metric (e.g.
    {"query": "EBIT"}) and records the result - the interactive step
    behind the MANUAL panel's search box. Returns status='not_found'
    rather than fabricating a value when the term isn't in the document."""
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    query = (request or {}).get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query required.")
    from tools.manual_document_pipeline import search_document
    result = search_document(sym, query)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.get("/api/v1/manual/{symbol}/searches")
def manual_search_history_endpoint(symbol: str, _: dict = Depends(auth.require_session)):
    """Every metric searched so far for this company's uploaded document -
    powers the sidebar list of searched items (EBIT, PAT, PBT, ...)."""
    sym = resolve_symbol_from_registry(symbol) or symbol.strip().upper()
    from tools.manual_document_pipeline import get_search_history
    return {"symbol": sym, "rows": get_search_history(sym)}


@app.post("/generate-report")
@app.post("/api/v1/generate-report")
async def generate_report_endpoint(request: ReportRequest, _: dict = Depends(auth.require_session)):
    """
    POST /generate-report endpoint that accepts 'ticker' or 'symbol' in the body,
    runs the agent flow (which fetches data via AngelDataScraper with yfinance fallback),
    generates a PDF report, and returns the final workflow state payload.
    """
    raw_symbol = request.ticker or request.symbol or ""
    incoming_symbol = resolve_symbol_from_registry(raw_symbol)
    if not incoming_symbol:
        raise HTTPException(status_code=400, detail="Stock ticker/symbol must not be empty.")
        
    print(f"\n[HTTP POST /generate-report] Request received for symbol: {incoming_symbol}")

    # Fast path: serve a fresh cached report instantly instead of re-running the
    # whole pipeline (this is what makes a repeat lookup feel Screener-fast).
    cached = _read_report_cache(incoming_symbol)
    if cached is not None:
        print(f"[HTTP] Serving cached report for {incoming_symbol} (instant).")
        return {
            "status": "success",
            "message": "Research complete (cached).",
            "pdf_path": None,
            "data": cached,
        }

    # Initialize the workflow state schema
    initial_state = {
        'symbol': incoming_symbol,
        'raw_financial_data': {},
        'business_score': 0,
        'qualitative_analysis': {},
        'peer_synthesis_data': {},
        'verdict': 'PENDING'
    }
    
    try:
        print(f"[HTTP] Invoking LangGraph workflow for ticker: {incoming_symbol}...")
        final_state = await asyncio.to_thread(app_graph.invoke, initial_state)
        print(f"[HTTP] Workflow completed successfully for symbol: {incoming_symbol}")
        
        # Cache the completed report so the next lookup of this symbol is instant.
        _write_report_cache(incoming_symbol, final_state)

        # Log to CSV Database (Skip saving PDF on disk)
        try:
            from tools.db_logger import StockDatabaseLogger
            StockDatabaseLogger.log_research(final_state)
        except Exception as db_err:
            print(f"[HTTP WARNING] Database logging failed: {db_err}")

        return {
            "status": "success",
            "message": "Research complete.",
            "pdf_path": None,
            "data": final_state
        }
    except Exception as e:
        print(f"[HTTP ERROR] Report generation failed for {incoming_symbol}: {e}")
        return {
            "status": "error",
            "message": f"Report generation failed: {str(e)}",
            "symbol": incoming_symbol,
            "verdict": "ERROR"
        }

@app.post("/api/v1/download-pdf")
async def download_pdf_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """
    POST /api/v1/download-pdf endpoint that accepts the stock research state data,
    compiles the PDF document dynamically in-memory, and streams it back.
    """
    try:
        from tools.pdf_generator import StockReportGenerator
        from fastapi.responses import StreamingResponse
        import io
        
        bio = io.BytesIO()
        StockReportGenerator.build_pdf_report(request, bio)
        bio.seek(0)
        
        symbol = request.get("symbol", "report")
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{symbol}_{ts}.pdf"
        headers = {
            'Content-Disposition': f'inline; filename="{filename}"'
        }
        return StreamingResponse(bio, media_type="application/pdf", headers=headers)
    except Exception as e:
        print(f"[HTTP ERROR] Dynamic PDF generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Dynamic PDF generation failed: {str(e)}")


# Short-TTL cache so the model calling get_stock_quote twice in one turn (or two
# users asking the same ticker seconds apart) is instant instead of re-hitting the
# scraper. Keyed by symbol; entries expire after _QUOTE_TTL seconds.
_quote_cache = {}
_quote_cache_lock = threading.Lock()
_QUOTE_TTL = 15  # seconds


def _registry_name_for(sym: str) -> str:
    """Look up the verbatim NSE company name for a resolved symbol, from the same
    STOCK_REGISTRY the autocomplete/symbol-resolver use. Returns '' if unknown -
    callers must NOT fall back to guessing a name from the model's own training
    data, which is exactly the bug this fixes (see _quote_for_llm)."""
    up = (sym or "").strip().upper()
    for item in STOCK_REGISTRY:
        if item["symbol"].upper() == up:
            return item["name"]
    return ""


def _quote_for_llm(args: dict) -> dict:
    """Live-quote tool exposed to Ask Navrist. Resolves a ticker/name to its NSE
    symbol and returns the real last-traded price + change, reusing the same
    scraper the dashboard ticker uses. Bounded by a hard timeout so a slow/hanging
    data source can never stall the chat for minutes - it degrades to 'unavailable'
    instead. Returns a compact dict the model can read.

    Critically, also returns the VERBATIM registry company name for the resolved
    symbol. Without this the model had only a bare ticker (e.g. "MWL") and would
    fill in a company name from its own training data - which for thinly-traded
    NSE tickers is frequently wrong (confirmed: "MWL" hallucinated as "Megan
    Media/Holdings" instead of the real Mangalam Worldwide Ltd). The system
    prompt now requires the model to use ONLY this field, never its own memory,
    for the company name."""
    import time as _t
    raw = (args or {}).get("symbol", "") or ""
    sym = resolve_symbol_from_registry(raw)
    if not sym:
        return {"error": "No symbol provided."}
    registry_name = _registry_name_for(sym)

    # Serve a fresh cached quote if we have one.
    with _quote_cache_lock:
        hit = _quote_cache.get(sym)
        if hit and (_t.time() - hit[0]) < _QUOTE_TTL:
            return hit[1]

    # Fetch under a hard wall-clock timeout. The scraper itself "never raises",
    # but the underlying HTTP calls can still be slow; this caps the worst case.
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            q = ex.submit(lambda: get_live_scraper().fetch_live_quote(sym) or {}).result(timeout=18)
    except concurrent.futures.TimeoutError:
        return {"symbol": sym, "company_name": registry_name or None, "available": False,
                "reason": "The live-price source is responding slowly right now. Please try again in a moment or check NSE."}
    except Exception as e:
        return {"symbol": sym, "company_name": registry_name or None, "available": False, "reason": f"Live quote unavailable: {e}"}
    ltp = q.get("ltp")
    prev_close = q.get("close")
    if ltp is None:
        return {"symbol": sym, "company_name": registry_name or None, "available": False,
                "reason": "No live price returned (market may be closed or symbol illiquid)."}
    change = change_pct = None
    if prev_close:
        try:
            change = round(ltp - prev_close, 2)
            change_pct = round((ltp - prev_close) / prev_close * 100, 2)
        except Exception:
            pass
    result = {
        "symbol": sym,
        # Verbatim NSE registry name - the ONLY source of truth for the company
        # name the model may state. None (not a guess) when the registry doesn't
        # have it, so the model is told to refer to the ticker only.
        "company_name": registry_name or None,
        "available": True,
        "currency": "INR",
        "last_price": ltp,
        "previous_close": prev_close,
        "change": change,
        "change_percent": change_pct,
        "day_high": q.get("high"),
        "day_low": q.get("low"),
        "day_open": q.get("open"),
        "source": q.get("source", "live"),
        "as_of": q.get("timestamp") or q.get("as_of"),
    }
    with _quote_cache_lock:
        _quote_cache[sym] = (_t.time(), result)
    return result


def _price_move_evidence_for_llm(args: dict) -> dict:
    """Event-grounded reasoning tool for Ask Navrist ("why did X move"). Detects
    flagged price-move windows purely from price history (no news source yet -
    see memory "event-grounded-reasoning-scope"), then attaches any concall
    commentary that falls near each window as evidence. Returns empty `moves`
    or empty per-window `concall_evidence` when there's genuinely nothing to
    show - the system prompt requires the model to say "no evidence found"
    rather than invent a cause in that case. Never raises."""
    raw = (args or {}).get("symbol", "") or ""
    sym = resolve_symbol_from_registry(raw)
    if not sym:
        return {"error": "No symbol provided."}
    registry_name = _registry_name_for(sym)

    try:
        from tools.move_detection import detect_significant_moves
        from tools.event_evidence import evidence_for_window, news_for_window
        moves = detect_significant_moves(sym)
    except Exception as e:
        return {"symbol": sym, "company_name": registry_name or None,
                "available": False, "reason": f"Move detection failed: {e}"}

    if not moves:
        return {"symbol": sym, "company_name": registry_name or None,
                "available": True, "moves": [],
                "note": "No single-day or sustained moves beyond threshold in the last ~6 months."}

    for m in moves:
        ev = evidence_for_window(sym, m["date_from"], m["date_to"], name=registry_name or None)
        m["concall_evidence"] = ev.get("calls", []) if ev.get("available") else []
        if not ev.get("available"):
            m["concall_evidence_note"] = ev.get("reason", "Concall data unavailable.")

        news = news_for_window(sym, m["date_from"], m["date_to"], name=registry_name or None)
        m["news_evidence"] = news.get("headlines", []) if news.get("available") else []
        if not news.get("available"):
            m["news_evidence_note"] = news.get("reason", "News unavailable.")

    return {"symbol": sym, "company_name": registry_name or None, "available": True, "moves": moves}


def _news_sentiment_for_llm(args: dict) -> dict:
    """General news-sentiment tool for Ask Navrist (not tied to a specific
    flagged move - for "how is sentiment on X" / "any recent news" questions).
    Scrapes Moneycontrol/ET/LiveMint via Google News RSS + Groq-scores each
    headline. Never raises."""
    raw = (args or {}).get("symbol", "") or ""
    sym = resolve_symbol_from_registry(raw)
    if not sym:
        return {"error": "No symbol provided."}
    registry_name = _registry_name_for(sym)
    try:
        from tools.news_sentiment import get_news_sentiment
        result = get_news_sentiment(sym, registry_name or None)
    except Exception as e:
        return {"symbol": sym, "company_name": registry_name or None,
                "available": False, "reason": f"News sentiment failed: {e}"}
    return {"symbol": sym, "company_name": registry_name or None, **result}


@app.post("/api/v1/ask-navrist")
async def ask_navrist_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """"Ask Navrist" chat - company-aware conversational assistant with live
    market-data, news-sentiment, and price-move-evidence tools, plus persistent
    memory of the user's prior questions (keyed by a client-generated
    session_id, since this app has no per-user login - see chat_memory.py).
    Runs off the event loop so a slow completion (or a tool fetch inside the
    tool loop) never blocks other requests."""
    try:
        from tools.ask_navrist import ask_navrist
        from tools.chat_memory import memory_block, save_message

        session_id = (request.get("session_id") or "").strip()
        symbol = (request.get("symbol") or "").strip() or None
        msgs = request.get("messages", [])
        mem = await asyncio.to_thread(memory_block, session_id) if session_id else ""

        result = await asyncio.to_thread(
            ask_navrist,
            msgs,
            request.get("context", "") or "",
            None,
            {
                "get_stock_quote": _quote_for_llm,
                "get_price_move_evidence": _price_move_evidence_for_llm,
                "get_news_sentiment": _news_sentiment_for_llm,
            },
            mem,
        )

        # Persist this turn (fire-and-forget-ish; never blocks the reply on failure).
        if session_id and msgs:
            last_user = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), None)
            if last_user:
                await asyncio.to_thread(save_message, session_id, "user", last_user, symbol)
            reply = result.get("reply")
            if reply and not result.get("error"):
                await asyncio.to_thread(save_message, session_id, "assistant", reply, symbol)

        return result
    except Exception as e:
        print(f"[HTTP ERROR] Ask Navrist failed: {e}")
        return {"reply": "Something went wrong handling that message. Please try again.", "error": True}


@app.post("/api/v1/concall-summary")
async def concall_summary_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Summarize ONE month's concall transcript on demand (for the per-month tabs)."""
    try:
        from tools.concall_summary import summarize_concall
        return summarize_concall(request.get("symbol", ""), request.get("url"), request.get("date", ""))
    except Exception as e:
        print(f"[HTTP ERROR] Concall summary failed: {e}")
        return {"available": False, "reason": f"Error: {e}"}


@app.post("/api/v1/concall-intelligence")
async def concall_intelligence_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Deep concall tracking (#2/#5): extract EVERY past call, build a sentiment
    timeline + walk-the-talk guidance-vs-outcome scorecard. Runs off the event loop;
    the frontend calls this AFTER the core report so the page stays fast."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"available": False, "reason": "Symbol required."}
    try:
        from tools.concall_intelligence import build_concall_intelligence
        return await asyncio.to_thread(
            build_concall_intelligence, sym,
            request.get("name"), request.get("financials_context", ""),
        )
    except Exception as e:
        print(f"[HTTP ERROR] Concall intelligence failed for {sym}: {e}")
        return {"available": False, "reason": f"Error: {e}"}


@app.post("/api/v1/business-evolution")
async def business_evolution_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Business Evolution (#4): then-vs-now + a categorized list/timeline of business
    changes (acquisitions, divestitures, new businesses, JVs, expansion, tech,
    management/strategy). Runs off the event loop; the frontend calls it after the core."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"available": False, "reason": "Symbol required."}
    try:
        from tools.business_evolution import build_business_evolution
        return await asyncio.to_thread(
            build_business_evolution, sym,
            request.get("name"), request.get("description", ""),
        )
    except Exception as e:
        print(f"[HTTP ERROR] Business evolution failed for {sym}: {e}")
        return {"available": False, "reason": f"Error: {e}"}


# Note: A.1-A.4 no longer have standalone /api/v1/qualitative/aN routes - they're
# computed inside build_executive_summary (agent/stock_agent.py) and shipped as
# part of ai_summary.qualitative_topics, rendered by the SAME Qualitative Analysis
# tab/format as every other topic (see frontend QualitativeTopics/QualitativeSubpoint).


@app.post("/api/v1/ratio/{ratio_key}")
async def generic_ratio_endpoint(ratio_key: str, request: dict, _: dict = Depends(auth.require_session)):
    """Universal ratio endpoint (spec §1.1/§55): resolves company + fiscal
    year, then routes through `tools.ratio_calculation_engine.
    calculate_ratio` - the ONE calculation path that reads canonical facts
    from `tools.fundamental_fact_store` (single extraction per symbol/year)
    and applies the registry's formula. No ratio-specific branching lives
    in this endpoint; every formula decision lives in the engine/registry.

    Falls back to the legacy `nse_xbrl.fetch_X` wrapper ONLY when the engine
    reports the ratio as not-yet-wired (`missing_dependency` present) AND a
    legacy strategy-A fetcher exists for it - e.g. COGS-based Inventory
    Turnover, which the canonical fact store doesn't extract yet (see
    `tools.ratio_calculation_engine.MISSING_DEPENDENCY`). This is
    compatibility behaviour, not a second independent calculation path: the
    legacy fetcher is used as-is, never re-implemented here."""
    from tools.fundamental_ratio_registry import BY_RATIO_KEY
    from tools.ratio_calculation_engine import calculate_ratio
    spec = BY_RATIO_KEY.get(ratio_key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown ratio_key '{ratio_key}'.")

    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}

    to_date = request.get("to_date")
    fiscal_year = None
    if to_date:
        try:
            fiscal_year = int(str(to_date).split("-")[-1])
        except Exception:
            fiscal_year = None
    if fiscal_year is None:
        try:
            from tools.annual_report_financials import list_annual_report_years
            years = await asyncio.to_thread(list_annual_report_years, sym, request.get("name"))
            fiscal_year = max(years) if years else None
        except Exception:
            fiscal_year = None
    if fiscal_year is None:
        return {"applicable": False, "reason": "No Annual Report filings found for this company.",
                "ratio_key": ratio_key}

    try:
        result = await asyncio.to_thread(calculate_ratio, ratio_key, sym, request.get("name"), fiscal_year)
    except Exception as e:
        print(f"[HTTP ERROR] Generic ratio engine failed for '{ratio_key}' / {sym}: {e}")
        result = {"ratio_key": ratio_key, "applicable": False, "status": "ERROR",
                  "reason": "Something went wrong computing this ratio - please try again."}

    if result.get("missing_dependency") and spec["strategy"] == "A" and spec.get("nse_xbrl_fn"):
        try:
            import tools.nse_xbrl as nse_xbrl
            fn = getattr(nse_xbrl, spec["nse_xbrl_fn"])
            legacy = await asyncio.to_thread(fn, sym, request.get("name"), request.get("to_date"))
            return {"ratio_key": ratio_key, "engine": "legacy_compat", **legacy}
        except Exception as e:
            print(f"[HTTP ERROR] Legacy fallback failed for '{ratio_key}' / {sym}: {e}")

    return result


@app.post("/api/v1/inventory-turnover")
async def inventory_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Inventory Turnover = COGS (a+b+c) / Average Inventory, computed from the
    company's OWN audited NSE XBRL standalone filings. Runs off the event loop; the
    frontend calls it after the core report. Returns {applicable: False} for lenders
    (no inventory) - never a fabricated number."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_inventory_turnover
        return await asyncio.to_thread(fetch_inventory_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Inventory turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/receivables-turnover")
async def receivables_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Receivables Turnover = Revenue from Operations / Average Trade Receivables,
    computed from the company's OWN audited Annual Report (Revenue used as a proxy
    for Net Credit Sales - Indian Annual Reports don't split cash vs. credit sales).
    Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses (receivables concept differs - loans/advances instead)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_receivables_turnover
        return await asyncio.to_thread(fetch_receivables_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Receivables turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/payables-turnover")
async def payables_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Payables Turnover = Purchases / Average Trade Payables, computed from the
    company's OWN audited Annual Report (Purchases = Cost of materials consumed +
    Purchases of stock-in-trade, falling back to COGS minus the inventory movement
    only if that split isn't available). Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_payables_turnover
        return await asyncio.to_thread(fetch_payables_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Payables turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/asset-turnover")
async def asset_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Asset Turnover = Revenue from Operations / Average Total Assets, computed
    from the company's OWN audited Annual Report. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_asset_turnover
        return await asyncio.to_thread(fetch_asset_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Asset turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/fixed-asset-turnover")
async def fixed_asset_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Fixed Asset Turnover (Sr No 30) = Revenue from Operations / Average Net
    Fixed Assets, computed from the company's OWN audited Annual Report. Runs
    off the event loop. Returns {applicable: False} for lenders/financial
    businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_fixed_asset_turnover
        return await asyncio.to_thread(fetch_fixed_asset_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Fixed asset turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/working-capital-turnover")
async def working_capital_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Working Capital Turnover = Revenue from Operations / Average Working Capital
    (Total Current Assets - Total Current Liabilities), computed from the company's
    OWN audited Annual Report. Runs off the event loop. Returns {applicable: False}
    for lenders/financial businesses, and when Average Working Capital is
    zero/negative (never silently reports a sign-inverted ratio)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_working_capital_turnover
        return await asyncio.to_thread(fetch_working_capital_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Working capital turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/days-working-capital")
async def days_working_capital_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Days Working Capital (Sr No 31) = (Average Working Capital / Revenue from
    Operations) x 365 - the days-based expression of Working Capital Turnover
    (Sr No 8/26), computed from the company's OWN audited Annual Report. Runs
    off the event loop. Returns {applicable: False} for lenders/financial
    businesses and when Revenue is zero/missing - but, unlike Working Capital
    Turnover, a negative Average Working Capital is a valid result here, never
    withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_days_working_capital
        return await asyncio.to_thread(fetch_days_working_capital, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Days Working Capital failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/receivables-to-payables-ratio")
async def receivables_to_payables_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Receivables-to-Payables Ratio (Sr No 32) = Trade Receivables / Trade
    Payables, BOTH closing balance, computed from the company's OWN audited
    Annual Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Trade Payables is zero - a ratio
    below 1x is a real, valid result, never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_receivables_to_payables_ratio
        return await asyncio.to_thread(fetch_receivables_to_payables_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Receivables-to-Payables Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/net-debt-to-ebitda")
async def net_debt_to_ebitda_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Net Debt/EBITDA (Sr No 33) = (Total Debt - Cash and Cash Equivalents) /
    EBITDA, computed from the company's OWN audited Annual Report. Runs off
    the event loop. Returns {applicable: False} for lenders/financial
    businesses, when EBITDA is zero/negative, and when Net Debt is negative
    (flagged as a Net Cash position via net_cash: True rather than reported
    as a spuriously low leverage multiple)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_net_debt_to_ebitda
        return await asyncio.to_thread(fetch_net_debt_to_ebitda, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Net Debt/EBITDA failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/debt-service-coverage-ratio")
async def debt_service_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Debt Service Coverage Ratio (DSCR, Sr No 34) = EBITDA / (Finance Costs +
    Principal Repayment of Borrowings, from the Cash Flow Statement's
    Financing Activities section), computed from the company's OWN audited
    Annual Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Total Debt Service is zero (a
    genuinely debt-free company - not calculated rather than divided by
    zero)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_debt_service_coverage_ratio
        return await asyncio.to_thread(fetch_debt_service_coverage_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Debt Service Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/cash-flow-coverage-ratio")
async def cash_flow_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cash Flow Coverage Ratio (Sr No 35) = Net Cash Flow from Operating
    Activities / Total Debt, computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Total Debt is zero (a genuinely
    debt-free company - the ratio wouldn't be meaningful)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cash_flow_coverage_ratio
        return await asyncio.to_thread(fetch_cash_flow_coverage_ratio, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Cash Flow Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/free-cash-flow")
async def free_cash_flow_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Free Cash Flow (FCF, Sr No 36) = Net Cash Flow from Operating Activities
    - net Capital Expenditure, computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses. A negative FCF is a real, valid result
    (e.g. a capex/growth investment phase) - never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_free_cash_flow
        return await asyncio.to_thread(fetch_free_cash_flow, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Free Cash Flow failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/fcf-margin")
async def fcf_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """FCF Margin (Sr No 38) = Free Cash Flow / Revenue from Operations,
    computed from the company's OWN audited Annual Report. Runs off the
    event loop. Returns {applicable: False} for lenders/financial businesses
    and when Revenue is zero/missing. A negative margin is a real, valid
    result (e.g. a growth/capex investment phase) - never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_fcf_margin
        return await asyncio.to_thread(fetch_fcf_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] FCF Margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/operating-cash-flow-ratio")
async def operating_cash_flow_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Operating Cash Flow Ratio (Sr No 39) = Net Cash Flow from Operating
    Activities / Total Current Liabilities (closing), computed from the
    company's OWN audited Annual Report. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses and when Total
    Current Liabilities is zero."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_operating_cash_flow_ratio
        return await asyncio.to_thread(fetch_operating_cash_flow_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Operating Cash Flow Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/capex-intensity")
async def capex_intensity_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Capex Intensity (Sr No 40) = Capital Expenditure, net / Revenue from
    Operations, computed from the company's OWN audited Annual Report. Runs
    off the event loop. Returns {applicable: False} for lenders/financial
    businesses and when Revenue is zero/missing."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_capex_intensity
        return await asyncio.to_thread(fetch_capex_intensity, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Capex Intensity failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/ocf-to-net-profit")
async def ocf_to_net_profit_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """OCF/Net Profit (Sr No 41) = Net Cash Flow from Operating Activities /
    Net Profit (owners-attributable), computed from the company's OWN
    audited Annual Report. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses and when Net
    Profit is zero/negative."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_ocf_to_net_profit
        return await asyncio.to_thread(fetch_ocf_to_net_profit, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] OCF/Net Profit failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/roic")
async def roic_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Return on Invested Capital (ROIC, Sr No 42) = NOPAT / Invested
    Capital (Total Debt + Total Equity - Cash, closing balance), computed
    from the company's OWN audited Annual Report. Runs off the event loop.
    Returns {applicable: False} for lenders/financial businesses, when
    Profit Before Tax is zero/negative, or when Invested Capital is
    zero/negative."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_roic
        return await asyncio.to_thread(fetch_roic, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] ROIC failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/effective-tax-rate")
async def effective_tax_rate_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Effective Tax Rate (Sr No 43) = Total Tax Expense / Profit Before
    Tax, computed from the company's OWN audited Annual Report. Runs off
    the event loop. Returns {applicable: False} for lenders/financial
    businesses and when Profit Before Tax is zero/negative."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_effective_tax_rate
        return await asyncio.to_thread(fetch_effective_tax_rate, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Effective Tax Rate failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/contribution-margin")
async def contribution_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Contribution Margin (Sr No 44) = (Revenue - Variable Costs) / Revenue,
    computed from the company's OWN audited Annual Report. KNOWN
    APPROXIMATION: 'Variable Costs' is only the raw-material COGS
    components (Cost of materials consumed + Purchases of stock-in-trade)
    -- Ind AS filings don't disclose a true fixed/variable cost-behaviour
    split, so this always understates true Contribution Margin; confidence
    is capped at 0.4. Runs off the event loop. Returns {applicable: False}
    for lenders/financial businesses, when Revenue is zero, or for a
    genuine services business with no goods-cost lines."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_contribution_margin
        return await asyncio.to_thread(fetch_contribution_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Contribution Margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/eps-growth")
async def eps_growth_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """EPS Growth Rate (Sr No 45) = (Current Year Basic EPS / Prior Year
    Basic EPS) - 1, computed from the company's OWN audited Annual Report.
    Applicable to every sector including Banks/NBFC/Insurance. Runs off the
    event loop. Returns {applicable: False} when Prior Year EPS is
    zero/negative (Not Meaningful)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_eps_growth
        return await asyncio.to_thread(fetch_eps_growth, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] EPS Growth Rate failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/dividend-payout-ratio")
async def dividend_payout_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Dividend Payout Ratio (Sr No 47) = Total Dividends Declared (Dividend
    per Share x Shares Outstanding) / Net Profit, computed from the
    company's OWN audited Annual Report. Applicable to every sector
    including Banks/NBFC/Insurance. Runs off the event loop. Returns
    {applicable: False} when Net Profit is zero/negative."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_dividend_payout_ratio
        return await asyncio.to_thread(fetch_dividend_payout_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Dividend Payout Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/operating-cash-flow")
async def operating_cash_flow_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Net Cash Flow from Operating Activities, GROSS (before capex, never
    Free Cash Flow) - Price/Cash Flow's (Sr No 53) denominator, computed
    from the company's OWN audited Annual Report. Runs off the event loop.
    Returns {applicable: False} when Operating Cash Flow is zero/negative."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_operating_cash_flow
        return await asyncio.to_thread(fetch_operating_cash_flow, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Operating Cash Flow failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/altman-z-score-components")
async def altman_z_score_components_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Altman Z-Score (Sr No 55) statement-side components (Working
    Capital, Total Assets, Retained Earnings, EBIT, Total Liabilities,
    Sales), computed from the company's OWN audited Annual Report - Market
    Capitalisation (the fifth weighted term) needs a live price and is
    combined client-side. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_altman_z_score_components
        return await asyncio.to_thread(fetch_altman_z_score_components, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Altman Z-Score components failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/piotroski-f-score")
async def piotroski_f_score_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Piotroski F-Score (Sr No 56) = sum of nine binary (1/0) year-over-
    year fundamental-strength tests (0-9 scale), computed from the
    company's OWN audited Annual Report. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses, or when two
    consecutive years of PAT/Total Assets/Operating Cash Flow aren't
    available."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_piotroski_f_score
        return await asyncio.to_thread(fetch_piotroski_f_score, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Piotroski F-Score failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/beneish-m-score")
async def beneish_m_score_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Beneish M-Score (Sr No 57) = an 8-variable earnings-manipulation
    detection composite, computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses, or when two consecutive years of
    complete data aren't available for any of the eight required
    variables."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_beneish_m_score
        return await asyncio.to_thread(fetch_beneish_m_score, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Beneish M-Score failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/net-interest-margin")
async def net_interest_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Net Interest Margin (Sr No 58) = (Interest Income - Interest
    Expense) / Average Interest-Earning Assets, computed from the
    company's OWN audited Annual Report (RBI-prescribed Bank/NBFC
    format). Runs off the event loop. Returns {applicable: False} for
    non-financial companies - this ratio applies ONLY to Banks/NBFCs."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_net_interest_margin
        return await asyncio.to_thread(fetch_net_interest_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Net Interest Margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/casa-ratio")
async def casa_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """CASA Ratio (Sr No 59) = (Demand Deposits + Savings Bank Deposits) /
    Total Deposits, computed from the company's OWN audited Annual Report
    (RBI-prescribed Bank format). Runs off the event loop. Returns
    {applicable: False} for non-bank companies (including NBFCs) - a
    narrower scope than Net Interest Margin's Bank+NBFC applicability."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_casa_ratio
        return await asyncio.to_thread(fetch_casa_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] CASA Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/gross-npa-pct")
async def gross_npa_pct_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Gross NPA % (Sr No 60) = Gross Non-Performing Assets / Gross
    Advances, computed from the company's OWN audited Annual Report
    (RBI-prescribed Bank/NBFC format, Asset Quality Notes). Runs off the
    event loop. Returns {applicable: False} for non-financial companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_gross_npa_pct
        return await asyncio.to_thread(fetch_gross_npa_pct, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Gross NPA % failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/net-npa-pct")
async def net_npa_pct_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Net NPA % (Sr No 61) = Net Non-Performing Assets / Net Advances,
    computed from the company's OWN audited Annual Report (RBI-prescribed
    Bank/NBFC format, Asset Quality Notes). Runs off the event loop.
    Returns {applicable: False} for non-financial companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_net_npa_pct
        return await asyncio.to_thread(fetch_net_npa_pct, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Net NPA % failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/capital-adequacy-ratio")
async def capital_adequacy_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Capital Adequacy Ratio / CRAR (Sr No 63) = (Tier I + Tier II
    Capital) / Risk-Weighted Assets, computed from the company's OWN
    audited Annual Report (Basel III Capital Adequacy Notes). Runs off
    the event loop. Returns {applicable: False} for non-financial
    companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_capital_adequacy_ratio
        return await asyncio.to_thread(fetch_capital_adequacy_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Capital Adequacy Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/cost-to-income-ratio")
async def cost_to_income_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cost-to-Income Ratio (Sr No 65) = Operating Expenses / (Net
    Interest Income + Other Income), computed from the company's OWN
    audited Annual Report (RBI-prescribed Bank/NBFC format). Runs off the
    event loop. Returns {applicable: False} for non-financial companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cost_to_income_ratio
        return await asyncio.to_thread(fetch_cost_to_income_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Cost-to-Income Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/beta")
async def beta_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Beta (Sr No 66) = Covariance(Stock Returns, Nifty 50 Returns) /
    Variance(Nifty 50 Returns), computed from historical weekly price
    data (yfinance) over a trailing 2-year window - NOT derived from
    financial statements, no fiscal-year concept applies. Runs off the
    event loop. Returns {applicable: False} for newly-listed/illiquid
    stocks with insufficient trading history."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_beta
        return await asyncio.to_thread(fetch_beta, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Beta failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/promoter-pledge-pct")
async def promoter_pledge_pct_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Promoter Pledge % (Sr No 67) = Pledged Promoter Shares / Total
    Promoter Shareholding, from the most recent SEBI Shareholding Pattern
    filing (BSE/NSE) - not derived from the Annual Report. Runs off the
    event loop. Returns {applicable: False} for professionally-managed
    companies with no promoter group."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_promoter_pledge_pct
        return await asyncio.to_thread(fetch_promoter_pledge_pct, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Promoter Pledge % failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/free-float-pct")
async def free_float_pct_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Free Float % (Sr No 68) = (Total Shares - Promoter Holding -
    Locked-in Shares) / Total Shares, from the most recent SEBI
    Shareholding Pattern filing (BSE/NSE) - not derived from the Annual
    Report. Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_free_float_pct
        return await asyncio.to_thread(fetch_free_float_pct, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Free Float % failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/current-ratio")
async def current_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Current Ratio = Total Current Assets / Total Current Liabilities (closing
    balance, not averaged), computed from the company's OWN audited Annual Report.
    Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_current_ratio
        return await asyncio.to_thread(fetch_current_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Current ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/quick-ratio")
async def quick_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Quick Ratio = (Total Current Assets - Inventories) / Total Current Liabilities
    (closing balance, not averaged), computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_quick_ratio
        return await asyncio.to_thread(fetch_quick_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Quick ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/cash-ratio")
async def cash_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cash Ratio = Cash and Cash Equivalents / Total Current Liabilities (closing
    balance, not averaged), computed from the company's OWN audited Annual Report.
    Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cash_ratio
        return await asyncio.to_thread(fetch_cash_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Cash ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/gross-profit-margin")
async def gross_profit_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Gross Profit Margin = (Revenue from Operations - COGS) / Revenue from Operations,
    computed from the company's OWN audited Annual Report (COGS reuses the same a+b+c
    components validated for Inventory Turnover). Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_gross_profit_margin
        return await asyncio.to_thread(fetch_gross_profit_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Gross profit margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/operating-profit-margin")
async def operating_profit_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Operating Profit Margin (EBITDA-basis) = (Revenue - COGS - Employee Benefit
    Expense - Other Expenses) / Revenue, computed from the company's OWN audited
    Annual Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_operating_profit_margin
        return await asyncio.to_thread(fetch_operating_profit_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Operating profit margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/income-statement-flow")
async def income_statement_flow_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Revenue -> Cost of Revenue/Gross Profit -> Operating Expenses/Operating
    Profit -> PBT bridge -> Tax/Net Profit node+link graph for the Overview
    page Sankey, computed entirely from the company's OWN audited Annual
    Report P&L. Runs off the event loop. Returns {applicable: False} when
    even the shallow Revenue -> PBT -> Net Profit flow can't be built."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_income_statement_flow
        return await asyncio.to_thread(fetch_income_statement_flow, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Income statement flow failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this - please try again."}


@app.post("/api/v1/net-profit-margin")
async def net_profit_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Net Profit Margin = Profit After Tax (owners-attributable) / Revenue from
    Operations, computed from the company's OWN audited Annual Report. Runs off
    the event loop. Returns {applicable: False} for lenders/financial businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_net_profit_margin
        return await asyncio.to_thread(fetch_net_profit_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Net profit margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/return-on-equity")
async def return_on_equity_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Return on Equity = Profit After Tax (owners-attributable) / Average Total
    Equity (owners-attributable), computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and negative-equity companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_return_on_equity
        return await asyncio.to_thread(fetch_return_on_equity, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Return on equity failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/return-on-capital-employed")
async def return_on_capital_employed_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """ROCE = EBIT (Profit Before Tax + Finance Costs) / Average Capital Employed
    (Total Assets - Total Current Liabilities), computed from the company's OWN
    audited Annual Report. Runs off the event loop. Returns {applicable: False}
    for lenders/financial businesses and zero/negative Capital Employed."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_return_on_capital_employed
        return await asyncio.to_thread(fetch_return_on_capital_employed, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Return on capital employed failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/debt-to-equity")
async def debt_to_equity_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Debt-to-Equity = Total Debt (Long-term + Short-term Borrowings + Current
    Maturities) / Total Equity (owners-attributable), both closing balance,
    computed from the company's OWN audited Annual Report. Runs off the event
    loop. Returns {applicable: False} for lenders/financial businesses and
    negative/zero-equity companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_debt_to_equity
        return await asyncio.to_thread(fetch_debt_to_equity, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Debt-to-Equity failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/debt-ratio")
async def debt_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Debt Ratio = Total Debt (Long-term + Short-term Borrowings + Current
    Maturities, identical to Debt-to-Equity's numerator) / Total Assets, both
    closing balance, computed from the company's OWN audited Annual Report.
    Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_debt_ratio
        return await asyncio.to_thread(fetch_debt_ratio, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Debt Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/interest-coverage-ratio")
async def interest_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Interest Coverage Ratio = EBIT (Profit Before Tax + Finance Costs,
    identical to ROCE's numerator) / Interest Expense (Finance Costs), current
    year only, computed from the company's OWN audited Annual Report. Runs off
    the event loop. Returns {applicable: False} for lenders/financial
    businesses, and {applicable: False, not_meaningful: True} (not a failure)
    when Finance Costs is nil - a genuinely debt-free company."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_interest_coverage_ratio
        return await asyncio.to_thread(fetch_interest_coverage_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Interest Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/financial-leverage-ratio")
async def financial_leverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Financial Leverage Ratio = Average Total Assets (identical to Asset
    Turnover's denominator) / Average Shareholders' Equity (identical to
    Return on Equity's denominator, owners-attributable), computed from the
    company's OWN audited Annual Report. Runs off the event loop. Returns
    {applicable: False} for lenders/financial businesses and negative-equity
    companies."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_financial_leverage_ratio
        return await asyncio.to_thread(fetch_financial_leverage_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Financial Leverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/eps")
async def eps_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Basic Earnings per Share, current year only, computed from the
    company's OWN audited Annual Report (P/E Ratio's denominator - the market
    price half is fetched separately via /api/quote). Runs off the event
    loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_eps
        return await asyncio.to_thread(fetch_eps, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] EPS failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/book-value-per-share")
async def book_value_per_share_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Book Value per Share = Total Equity (owners-attributable, closing) /
    Equity Shares Outstanding (closing), computed from the company's OWN
    audited Annual Report (P/B Ratio's denominator - the market price half is
    fetched separately via /api/quote). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_book_value_per_share
        return await asyncio.to_thread(fetch_book_value_per_share, sym, request.get("name"), request.get("to_date"),
                                        request.get("consolidated", True))
    except Exception as e:
        print(f"[HTTP ERROR] Book Value per Share failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/shares-outstanding")
async def shares_outstanding_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Equity Shares Outstanding (closing), current year only, computed from
    the company's OWN audited Annual Report (Price-to-Sales' Market Cap
    building block). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_shares_outstanding
        return await asyncio.to_thread(fetch_shares_outstanding, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Shares Outstanding failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/revenue-from-operations")
async def revenue_from_operations_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Revenue from Operations, current year only, computed from the
    company's OWN audited Annual Report (Price-to-Sales' denominator). Runs
    off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_revenue_from_operations
        return await asyncio.to_thread(fetch_revenue_from_operations, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Revenue from Operations failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/dividend-per-share")
async def dividend_per_share_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Total Dividend per Equity Share declared during the year (always
    standalone-sourced), computed from the company's OWN audited Annual
    Report (Dividend Yield's numerator - the market price half is fetched
    separately via /api/quote). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_dividend_per_share
        return await asyncio.to_thread(fetch_dividend_per_share, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Dividend per Share failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/ebitda")
async def ebitda_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """EBITDA (Revenue − COGS − Employee Costs − Other Expenses), current
    year only, computed from the company's OWN audited Annual Report
    (EV/EBITDA's denominator - identical formula to Operating Profit
    Margin's numerator). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_ebitda
        return await asyncio.to_thread(fetch_ebitda, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] EBITDA failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/total-debt")
async def total_debt_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Total Debt (closing), computed from the company's OWN audited Annual
    Report (EV/EBITDA's Enterprise Value building block - identical
    components to Debt-to-Equity/Debt Ratio's numerator). Runs off the event
    loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_total_debt
        return await asyncio.to_thread(fetch_total_debt, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Total Debt failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.post("/api/v1/cash-and-equivalents")
async def cash_and_equivalents_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cash and Cash Equivalents (closing), computed from the company's OWN
    audited Annual Report (EV/EBITDA's Enterprise Value building block -
    identical field to Cash Ratio's numerator). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cash_and_equivalents
        return await asyncio.to_thread(fetch_cash_and_equivalents, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Cash and Cash Equivalents failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio - please try again."}


@app.get("/api/v1/all-symbols")
async def all_symbols_endpoint(_: dict = Depends(auth.require_session)):
    """Full NSE registry (same list the autocomplete searches), sorted
    alphabetically by symbol - for an external batch/audit tool (e.g. an
    n8n workflow) that needs to iterate every known company, not just
    search for one. Waits for the background scrip-master fetch the same
    way /api/search-symbols does, so an early call doesn't return only the
    ~100-company curated seed list."""
    _REGISTRY_READY.wait(timeout=15)
    return sorted(STOCK_REGISTRY, key=lambda item: item["symbol"])


@app.get("/api/v1/ratio-audit/{symbol}")
async def ratio_audit_endpoint(symbol: str, _: dict = Depends(auth.require_session)):
    """Runs EVERY Annual-Report/NSE-sourced ratio for one company in a
    single call and returns a uniform verdict per ratio (successful yes/no
    + reason if not) - built for an external audit automation that would
    otherwise need 54+ separate HTTP calls per stock, one per ratio, each
    with its own ad-hoc "did this work" logic. See tools/ratio_audit.py
    for exactly which endpoints this covers and why each row is identified
    by its endpoint slug rather than a numbered Sr No (two different,
    disagreeing Sr-No specs exist elsewhere in this codebase - documented
    there, not repeated here). Runs off the event loop since this can
    involve several PDF downloads+parses for a not-yet-precomputed company."""
    sym = resolve_symbol_from_registry(symbol or "")
    if not sym:
        return {"symbol": symbol, "ratios": [], "error": "Symbol not found in registry."}
    name = next((c["name"] for c in STOCK_REGISTRY if c["symbol"] == sym), sym)
    try:
        from tools.ratio_audit import audit_one
        ratios = await asyncio.to_thread(audit_one, sym, name)
        return {"symbol": sym, "name": name, "ratios": ratios}
    except Exception as e:
        print(f"[HTTP ERROR] Ratio audit failed for {sym}: {e}")
        return {"symbol": sym, "name": name, "ratios": [], "error": "Something went wrong running the audit - please try again."}


@app.post("/test-flow")
@app.post("/api/v1/test-flow")
async def test_flow_endpoint(request: ReportRequest, _: dict = Depends(auth.require_session)):
    """
    POST /test-flow endpoint to dry-run the workflow and verify ingestion and agents.
    """
    raw_symbol = request.ticker or request.symbol or ""
    incoming_symbol = resolve_symbol_from_registry(raw_symbol)
    if not incoming_symbol:
        raise HTTPException(status_code=400, detail="Stock ticker/symbol must not be empty.")
        
    print(f"\n[HTTP POST /test-flow] Request received for: {incoming_symbol}")
    
    initial_state = {
        'symbol': incoming_symbol,
        'raw_financial_data': {},
        'business_score': 0,
        'qualitative_analysis': {},
        'peer_synthesis_data': {},
        'verdict': 'PENDING'
    }
    
    try:
        print(f"[HTTP] Running validation workflow for: {incoming_symbol}...")
        final_state = await asyncio.to_thread(app_graph.invoke, initial_state)
        return {
            "status": "success",
            "message": "Workflow dry-run completed successfully.",
            "data": final_state
        }
    except Exception as e:
        print(f"[HTTP ERROR] Workflow dry-run failed for {incoming_symbol}: {e}")
        return {
            "status": "error",
            "message": f"Workflow dry-run failed: {str(e)}",
            "symbol": incoming_symbol
        }


if __name__ == '__main__':
    import uvicorn
    # Env-driven so the same file runs locally and on the Indian-region cloud:
    #   HOST   - bind address (0.0.0.0 to be reachable on a server; 127.0.0.1 local)
    #   PORT   - listening port (cloud platforms inject this)
    #   RELOAD - "1" for local auto-reload dev; off in production
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "1").strip() in ("1", "true", "True", "yes")
    print(f"Starting Navrist Research Terminal backend on {host}:{port} (reload={reload})...")
    # Exclude the data-cache tree from the reload file-watcher: every ratio/
    # document-analysis computation writes JSON files under cache/ (often
    # hundreds per run), which uvicorn's default watcher otherwise treats
    # exactly like a source-code change - restarting the whole process mid-
    # request. A long-running manual-upload analysis killed by one of these
    # restarts surfaces to the frontend as a 401 "Session expired" (the
    # in-flight request never gets a response from the dying worker, and the
    # retry against the freshly-started one races the client's own timeout/
    # abort handling) even though the JWT itself never expired. Source code
    # changes still trigger a reload as normal - only the cache/ output
    # directory is excluded.
    reload_kwargs = {"reload_excludes": ["cache/*", "cache/**", "**/cache/**"]} if reload else {}
    uvicorn.run("app:app", host=host, port=port, reload=reload, **reload_kwargs)
