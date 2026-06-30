import os
import sys

# Fix TLS trust BEFORE any HTTPS call. On Windows behind a TLS-inspecting
# firewall/AV (common in India) this makes requests + curl_cffi (yfinance/NSE)
# verify against the machine's own trusted roots. No-op on the Linux cloud box.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import tools.ssl_bootstrap  # noqa: E402  (must run before requests/yfinance/Angel)

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
    query = q.strip().upper()
    if not query:
        return []
    results = []
    for item in STOCK_REGISTRY:
        if query in item["symbol"].upper() or query in item["name"].upper():
            results.append(item)
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
    """Serve the dashboard SPA at the site root so the deployed domain shows the app."""
    from fastapi.responses import FileResponse
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend-dashboard", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
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
        final_state = app_graph.invoke(initial_state)
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
        final_state = app_graph.invoke(initial_state)
        print(f"[HTTP] Workflow completed successfully for symbol: {incoming_symbol}")
        
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
        final_state = app_graph.invoke(initial_state)
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
