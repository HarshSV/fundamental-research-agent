import os
import sys

# Fix TLS trust BEFORE any HTTPS call. On Windows behind a TLS-inspecting
# firewall/AV (common in India) this makes requests + curl_cffi (yfinance/NSE)
# verify against the machine's own trusted roots. No-op on the Linux cloud box.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import tools.ssl_bootstrap  # noqa: E402  (must run before requests/yfinance/Angel)

import asyncio
import threading
import requests
from fastapi import FastAPI, HTTPException, Depends
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

@app.on_event("startup")
def startup_event():
    threading.Thread(target=load_scrip_master_async, daemon=True).start()

@app.get("/api/search-symbols")
def search_symbols(q: str = "", _: dict = Depends(auth.require_session)):
    """Ranked autocomplete: symbol-starts-with (what a ticker search means)
    ranks above name-starts-with, which ranks above a bare substring match
    anywhere. The OLD version only checked "query in symbol/name" with no
    ranking at all — typing "U" matched every company whose NAME contained
    a "u" anywhere (e.g. "Reliance INdUstries", "Tata ConsUltancy") and
    returned them in raw registry order, so RELIANCE/TCS/HINDUNILVR/LT/
    SUNPHARMA (the curated list's first few entries) always won regardless
    of query, never actual U-prefixed companies like UPL/ULTRACEMCO."""
    query = q.strip().upper()
    if not query:
        return []
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

    # Check if the query matches the name or symbol in registry
    for item in STOCK_REGISTRY:
        sym = item["symbol"].upper()
        name = item["name"].upper()
        if cleaned == sym or cleaned == name or cleaned in sym or cleaned in name:
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
    if os.path.exists(built_index):
        return FileResponse(built_index)
    if os.path.exists(legacy_index):
        return FileResponse(legacy_index)
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


@app.post("/api/v1/inventory-turnover")
async def inventory_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Inventory Turnover = COGS (a+b+c) / Average Inventory, computed from the
    company's OWN audited NSE XBRL standalone filings. Runs off the event loop; the
    frontend calls it after the core report. Returns {applicable: False} for lenders
    (no inventory) — never a fabricated number."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_inventory_turnover
        return await asyncio.to_thread(fetch_inventory_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Inventory turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/receivables-turnover")
async def receivables_turnover_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Receivables Turnover = Revenue from Operations / Average Trade Receivables,
    computed from the company's OWN audited Annual Report (Revenue used as a proxy
    for Net Credit Sales — Indian Annual Reports don't split cash vs. credit sales).
    Runs off the event loop. Returns {applicable: False} for lenders/financial
    businesses (receivables concept differs — loans/advances instead)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_receivables_turnover
        return await asyncio.to_thread(fetch_receivables_turnover, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Receivables turnover failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/days-working-capital")
async def days_working_capital_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Days Working Capital (Sr No 31) = (Average Working Capital / Revenue from
    Operations) x 365 — the days-based expression of Working Capital Turnover
    (Sr No 8/26), computed from the company's OWN audited Annual Report. Runs
    off the event loop. Returns {applicable: False} for lenders/financial
    businesses and when Revenue is zero/missing — but, unlike Working Capital
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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/receivables-to-payables-ratio")
async def receivables_to_payables_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Receivables-to-Payables Ratio (Sr No 32) = Trade Receivables / Trade
    Payables, BOTH closing balance, computed from the company's OWN audited
    Annual Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Trade Payables is zero — a ratio
    below 1x is a real, valid result, never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_receivables_to_payables_ratio
        return await asyncio.to_thread(fetch_receivables_to_payables_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Receivables-to-Payables Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/debt-service-coverage-ratio")
async def debt_service_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Debt Service Coverage Ratio (DSCR, Sr No 34) = EBITDA / (Finance Costs +
    Principal Repayment of Borrowings, from the Cash Flow Statement's
    Financing Activities section), computed from the company's OWN audited
    Annual Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Total Debt Service is zero (a
    genuinely debt-free company — not calculated rather than divided by
    zero)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_debt_service_coverage_ratio
        return await asyncio.to_thread(fetch_debt_service_coverage_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Debt Service Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/cash-flow-coverage-ratio")
async def cash_flow_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cash Flow Coverage Ratio (Sr No 35) = Net Cash Flow from Operating
    Activities / Total Debt, computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses and when Total Debt is zero (a genuinely
    debt-free company — the ratio wouldn't be meaningful)."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cash_flow_coverage_ratio
        return await asyncio.to_thread(fetch_cash_flow_coverage_ratio, sym, request.get("name"), request.get("to_date"), request.get("lease_basis", "basis1"))
    except Exception as e:
        print(f"[HTTP ERROR] Cash Flow Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/free-cash-flow")
async def free_cash_flow_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Free Cash Flow (FCF, Sr No 36) = Net Cash Flow from Operating Activities
    - net Capital Expenditure, computed from the company's OWN audited Annual
    Report. Runs off the event loop. Returns {applicable: False} for
    lenders/financial businesses. A negative FCF is a real, valid result
    (e.g. a capex/growth investment phase) — never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_free_cash_flow
        return await asyncio.to_thread(fetch_free_cash_flow, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Free Cash Flow failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/fcf-margin")
async def fcf_margin_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """FCF Margin (Sr No 38) = Free Cash Flow / Revenue from Operations,
    computed from the company's OWN audited Annual Report. Runs off the
    event loop. Returns {applicable: False} for lenders/financial businesses
    and when Revenue is zero/missing. A negative margin is a real, valid
    result (e.g. a growth/capex investment phase) — never withheld."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_fcf_margin
        return await asyncio.to_thread(fetch_fcf_margin, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] FCF Margin failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/interest-coverage-ratio")
async def interest_coverage_ratio_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Interest Coverage Ratio = EBIT (Profit Before Tax + Finance Costs,
    identical to ROCE's numerator) / Interest Expense (Finance Costs), current
    year only, computed from the company's OWN audited Annual Report. Runs off
    the event loop. Returns {applicable: False} for lenders/financial
    businesses, and {applicable: False, not_meaningful: True} (not a failure)
    when Finance Costs is nil — a genuinely debt-free company."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_interest_coverage_ratio
        return await asyncio.to_thread(fetch_interest_coverage_ratio, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Interest Coverage Ratio failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/eps")
async def eps_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Basic Earnings per Share, current year only, computed from the
    company's OWN audited Annual Report (P/E Ratio's denominator — the market
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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/book-value-per-share")
async def book_value_per_share_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Book Value per Share = Total Equity (owners-attributable, closing) /
    Equity Shares Outstanding (closing), computed from the company's OWN
    audited Annual Report (P/B Ratio's denominator — the market price half is
    fetched separately via /api/quote). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_book_value_per_share
        return await asyncio.to_thread(fetch_book_value_per_share, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Book Value per Share failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/dividend-per-share")
async def dividend_per_share_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Total Dividend per Equity Share declared during the year (always
    standalone-sourced), computed from the company's OWN audited Annual
    Report (Dividend Yield's numerator — the market price half is fetched
    separately via /api/quote). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_dividend_per_share
        return await asyncio.to_thread(fetch_dividend_per_share, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Dividend per Share failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/ebitda")
async def ebitda_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """EBITDA (Revenue − COGS − Employee Costs − Other Expenses), current
    year only, computed from the company's OWN audited Annual Report
    (EV/EBITDA's denominator — identical formula to Operating Profit
    Margin's numerator). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_ebitda
        return await asyncio.to_thread(fetch_ebitda, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] EBITDA failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/total-debt")
async def total_debt_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Total Debt (closing), computed from the company's OWN audited Annual
    Report (EV/EBITDA's Enterprise Value building block — identical
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
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


@app.post("/api/v1/cash-and-equivalents")
async def cash_and_equivalents_endpoint(request: dict, _: dict = Depends(auth.require_session)):
    """Cash and Cash Equivalents (closing), computed from the company's OWN
    audited Annual Report (EV/EBITDA's Enterprise Value building block —
    identical field to Cash Ratio's numerator). Runs off the event loop."""
    sym = resolve_symbol_from_registry(request.get("symbol", "") or "")
    if not sym:
        return {"applicable": False, "reason": "Symbol required."}
    try:
        from tools.nse_xbrl import fetch_cash_and_equivalents
        return await asyncio.to_thread(fetch_cash_and_equivalents, sym, request.get("name"), request.get("to_date"))
    except Exception as e:
        print(f"[HTTP ERROR] Cash and Cash Equivalents failed for {sym}: {e}")
        return {"applicable": False, "reason": "Something went wrong computing this ratio — please try again."}


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
    uvicorn.run("app:app", host=host, port=port, reload=reload)
