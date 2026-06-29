"""
Apify Screener.in API client — primary data source for Indian stock fundamentals.

Uses the `solidcode/screener-in-scraper` Apify actor to pull structured company
data from Screener.in: key ratios, P&L, balance sheet, cash flow, quarterly
results, shareholding, and peers.

Outputs the SAME dict format that angel_scraper.py produces, so metrics_engine.py
requires zero changes. Disk-cached (12 h TTL) for fast repeat lookups.

Requires APIFY_API_TOKEN in .env (free at https://console.apify.com).
"""

import os
import json
import time
import threading
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "screener_api")
TTL = 12 * 3600  # 12-hour cache

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Cache helpers (mirrors screener_scraper.py pattern)
# ---------------------------------------------------------------------------

def _cache_path(key):
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key):
    try:
        p = _cache_path(key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_cache(key, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Apify actor call
# ---------------------------------------------------------------------------

def _resolve_screener_url(symbol: str) -> str:
    """
    Screener.in sometimes uses different slugs than NSE symbols (e.g. TATAMOTORS -> TMCV).
    We use their internal search API to resolve the exact URL slug.
    Returns the resolved URL, or the symbol itself if resolution fails.
    """
    import urllib.request
    import urllib.parse
    
    # 0. Known overrides for recent demergers/symbol changes
    SYMBOL_MAP = {
        "TATAMOTORS": "TMCV",
        "M&M": "M_M",
        "BAJAJ-AUTO": "BAJAJ_AUTO"
    }
    if symbol in SYMBOL_MAP:
        return f"https://www.screener.in/company/{SYMBOL_MAP[symbol]}/consolidated/"
    
    # 1. Try exact symbol search
    try:
        url = f"https://www.screener.in/api/company/search/?q={urllib.parse.quote(symbol)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
        if res and len(res) > 0:
            # e.g. "/company/TMCV/consolidated/" -> "https://www.screener.in/company/TMCV/consolidated/"
            return f"https://www.screener.in{res[0]['url']}"
    except Exception:
        pass
        
    # 2. Try company name search using yfinance as a fallback
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        name = ticker.info.get("shortName") or ticker.info.get("longName")
        if name:
            url = f"https://www.screener.in/api/company/search/?q={urllib.parse.quote(name)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
            if res and len(res) > 0:
                return f"https://www.screener.in{res[0]['url']}"
    except Exception:
        pass
        
    return symbol

def _call_apify_screener(symbol: str) -> dict | None:
    """
    Run the solidcode/screener-in-scraper Apify actor for a single company.
    Returns the first company record dict, or None on failure.
    """
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token:
        print("[screener_api] APIFY_API_TOKEN not set — skipping Screener API.")
        return None

    try:
        from apify_client import ApifyClient
        client = ApifyClient(token)

        # Resolve the symbol to a full Screener.in URL to avoid 404s for mismatched symbols
        resolved_url_or_symbol = _resolve_screener_url(symbol)
        print(f"[screener_api] Resolved {symbol} to {resolved_url_or_symbol}")

        run_input = {
            "companies": [resolved_url_or_symbol],
            "screenUrls": [],
            "financialsType": "consolidated",
            "includeSections": [
                "quarterlyResults",
                "profitLoss",
                "balanceSheet",
                "cashFlow",
                "ratios",
                "shareholding",
                "peers",
            ],
            "maxResults": 100,
        }

        print(f"[screener_api] Calling Apify solidcode/screener-in-scraper for {symbol}...")
        run = client.actor("solidcode/screener-in-scraper").call(run_input=run_input)

        # Handle both dict and Pydantic model returns (apify-client v3.0+)
        dataset_id = getattr(run, "default_dataset_id", None)
        if not dataset_id and isinstance(run, dict):
            dataset_id = run.get("defaultDatasetId")
            
        if not dataset_id:
            print(f"[screener_api] Could not extract dataset ID from Apify run: {run}")
            return None

        items = list(client.dataset(dataset_id).iterate_items())
        company_records = [i for i in items if i.get("recordType") == "company"]
        if company_records:
            print(f"[screener_api] Got company record for {symbol} ({len(company_records)} records).")
            return company_records[0]
        else:
            print(f"[screener_api] No company record returned for {symbol}.")
            return None
    except Exception as e:
        print(f"[screener_api] Apify call failed for {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Transform Screener.in output → angel_scraper format
# ---------------------------------------------------------------------------

def _v(obj):
    """Extract numeric value from a Screener {raw, value} pair, or return as-is."""
    if isinstance(obj, dict):
        return obj.get("value")
    return obj


def _build_income_stmt(profit_loss_rows: list, is_quarterly: bool = False) -> dict:
    """
    Convert Screener profitLoss or quarterlyResults array into the
    {date_str: {row_name: value}} format that metrics_engine expects.
    """
    result = {}
    for row in (profit_loss_rows or []):
        period = row.get("period", "")
        if not period:
            continue
        col = {}
        # Map Screener.in field names → yfinance-style row names
        mapping = {
            "sales": "Total Revenue",
            "expenses": "Total Expenses",
            "operatingProfit": "EBIT",
            "otherIncome": "Other Income",
            "profitBeforeTax": "Pretax Income",
            "netProfit": "Net Income",
            "eps": "Diluted EPS",
            "dividendPayout": "Dividend Payout",
        }
        # Also handle EBITDA: operating profit + depreciation
        for src_key, dst_key in mapping.items():
            val = _v(row.get(src_key))
            if val is not None:
                # Screener reports in Cr; yfinance expects raw INR.
                # Convert Cr → INR (×1e7) for monetary values
                if src_key not in ("eps", "opm"):
                    val = val * 1e7
                col[dst_key] = val

        # OPM% → Operating Margins (as fraction)
        opm = _v(row.get("opm"))
        if opm is not None:
            col["Operating Margins"] = opm / 100.0

        # Gross Profit (approximate: sales - material cost if available)
        # EBITDA (approximate: operating profit + depreciation)
        depreciation = _v(row.get("depreciation"))
        op_profit = _v(row.get("operatingProfit"))
        if depreciation is not None and op_profit is not None:
            col["EBITDA"] = (op_profit + depreciation) * 1e7
        elif op_profit is not None:
            col["EBITDA"] = op_profit * 1e7
            col["Normalized EBITDA"] = op_profit * 1e7

        # Interest
        interest = _v(row.get("interest"))
        if interest is not None:
            col["Interest Expense"] = interest * 1e7

        # Tax
        tax = _v(row.get("tax"))
        if tax is not None:
            col["Tax Provision"] = tax * 1e7

        # Depreciation
        if depreciation is not None:
            col["Depreciation"] = depreciation * 1e7

        # Net Income Common Stockholders (alias)
        if "Net Income" in col:
            col["Net Income Common Stockholders"] = col["Net Income"]

        # Revenue alias
        if "Total Revenue" in col:
            col["Revenue"] = col["Total Revenue"]

        # Gross Profit approximation (Revenue - expenses + operating profit)
        sales_val = _v(row.get("sales"))
        material_cost = _v(row.get("materialCost"))
        if sales_val is not None and material_cost is not None:
            col["Gross Profit"] = (sales_val - material_cost) * 1e7

        result[period] = col
    return result


def _build_balance_sheet(bs_rows: list) -> dict:
    """Convert Screener balanceSheet array → yfinance-style format."""
    result = {}
    for row in (bs_rows or []):
        period = row.get("period", "")
        if not period:
            continue
        col = {}
        mapping = {
            "totalAssets": "Total Assets",
            "shareCapital": "Share Capital",
            "reserves": "Stockholders Equity",  # reserves + share capital ≈ equity
            "borrowings": "Total Debt",
            "otherLiabilities": "Other Liabilities",
            "fixedAssets": "Net PPE",
            "investments": "Investments",
            "otherAssets": "Other Assets",
        }
        for src_key, dst_key in mapping.items():
            val = _v(row.get(src_key))
            if val is not None:
                col[dst_key] = val * 1e7

        # Compute equity = share capital + reserves
        share_cap = _v(row.get("shareCapital"))
        reserves = _v(row.get("reserves"))
        if share_cap is not None and reserves is not None:
            col["Stockholders Equity"] = (share_cap + reserves) * 1e7
            col["Total Equity Gross Minor Interest"] = (share_cap + reserves) * 1e7
            col["Common Stock Equity"] = (share_cap + reserves) * 1e7

        # Current liabilities approximation
        curr_liab = _v(row.get("currentLiabilities"))
        if curr_liab is not None:
            col["Current Liabilities"] = curr_liab * 1e7
            col["Total Current Liabilities"] = curr_liab * 1e7

        # Long Term Debt
        long_term = _v(row.get("longTermBorrowings")) or _v(row.get("borrowings"))
        if long_term is not None:
            col["Long Term Debt"] = long_term * 1e7

        # Cash
        cash = _v(row.get("cashEquivalents")) or _v(row.get("cash"))
        if cash is not None:
            col["Cash And Cash Equivalents"] = cash * 1e7
            col["Cash Cash Equivalents And Short Term Investments"] = cash * 1e7

        # Total non-current assets / total current assets if available
        total_assets = _v(row.get("totalAssets"))
        if total_assets is not None and "Current Liabilities" not in col:
            # Estimate current liabilities ≈ other liabilities (rough)
            other_liab = _v(row.get("otherLiabilities"))
            if other_liab is not None:
                col["Current Liabilities"] = other_liab * 1e7
                col["Total Current Liabilities"] = other_liab * 1e7

        result[period] = col
    return result


def _build_cash_flow(cf_rows: list) -> dict:
    """Convert Screener cashFlow array → yfinance-style format."""
    result = {}
    for row in (cf_rows or []):
        period = row.get("period", "")
        if not period:
            continue
        col = {}
        mapping = {
            "operatingActivity": "Operating Cash Flow",
            "investingActivity": "Investing Cash Flow",
            "financingActivity": "Financing Cash Flow",
            "netCashFlow": "Net Cash Flow",
        }
        for src_key, dst_key in mapping.items():
            val = _v(row.get(src_key))
            if val is not None:
                col[dst_key] = val * 1e7

        # Aliases
        if "Operating Cash Flow" in col:
            col["Cash Flow From Continuing Operating Activities"] = col["Operating Cash Flow"]
            col["Net Cash Provided By Operating Activities"] = col["Operating Cash Flow"]

        # Capital Expenditure (part of investing activity — approximate from fixedAssets delta)
        capex = _v(row.get("fixedAssetsPurchased")) or _v(row.get("capitalExpenditure"))
        if capex is not None:
            col["Capital Expenditure"] = -abs(capex) * 1e7  # Capex is typically negative
            col["Purchase Of PPE"] = -abs(capex) * 1e7

        result[period] = col
    return result


def _build_shareholding(sh_rows: list) -> dict:
    """Convert Screener shareholding array → the shareholding dict format."""
    if not sh_rows:
        return {}

    # Sort by period descending (newest first)
    sorted_rows = sorted(sh_rows, key=lambda r: r.get("period", ""), reverse=True)
    latest = sorted_rows[0] if sorted_rows else {}

    # Multi-quarter history for trend charts
    quarters = []
    promoter_series = []
    fii_series = []
    dii_series = []
    public_series = []
    govt_series = []

    for row in reversed(sorted_rows):  # oldest first for charting
        period = row.get("period", "")
        quarters.append(period)
        promoter_series.append(_v(row.get("promoters")))
        fii_series.append(_v(row.get("fIIs")))
        dii_series.append(_v(row.get("dIIs")))
        public_series.append(_v(row.get("public")))
        govt_series.append(_v(row.get("government")))

    # Build ownership_history array (for UI trend charts)
    ownership_history = []
    for i, q in enumerate(quarters):
        ownership_history.append({
            "quarter": q,
            "promoter": promoter_series[i],
            "fii": fii_series[i],
            "dii": dii_series[i],
            "public": public_series[i],
            "government": govt_series[i] if i < len(govt_series) else None,
        })

    return {
        "source": "Screener",
        "status": "ok",
        "as_of_quarter": latest.get("period"),
        "promoter_holding_pct": _v(latest.get("promoters")),
        "institutional_holding_pct": (
            (_v(latest.get("fIIs")) or 0) + (_v(latest.get("dIIs")) or 0)
        ) if latest else None,
        "public_holding_pct": _v(latest.get("public")),
        "promoter_pledge_pct": _v(latest.get("pledged")),
        "fii_stake": _v(latest.get("fIIs")),
        "dii_stake": _v(latest.get("dIIs")),
        "government_stake": _v(latest.get("government")),
        "pledge_status": "pledged" if _v(latest.get("pledged")) else "no_pledge",
        "ownership_history": ownership_history,
        "market_fii_dii": [],
        "fund_flows": [],
        "concall_links": [],
    }


def _build_info_dict(record: dict) -> dict:
    """Build a yfinance-compatible info dict from Screener record."""
    kr = record.get("keyRatios") or {}
    current_price = _v(kr.get("currentPrice")) or record.get("currentPrice")
    market_cap_cr = _v(kr.get("marketCap")) or record.get("marketCapCr")
    pe = _v(kr.get("pe"))
    book_value = _v(kr.get("bookValue"))
    dividend_yield = _v(kr.get("dividendYield"))
    roce = _v(kr.get("roce"))
    roe = _v(kr.get("roe"))
    face_value = _v(kr.get("faceValue"))
    high_low = _v(kr.get("highLow"))

    # Shares outstanding estimation
    shares_outstanding = None
    if market_cap_cr and current_price and current_price > 0:
        # market_cap_cr is in Cr, price is per share
        shares_outstanding = (market_cap_cr * 1e7) / current_price

    info = {
        "symbol": record.get("symbol") or record.get("nseCode"),
        "longName": record.get("name"),
        "shortName": record.get("name"),
        "currentPrice": current_price,
        "regularMarketPrice": current_price,
        "previousClose": current_price,  # Approximation
        "trailingPE": pe,
        "forwardPE": pe,
        "priceToBook": (current_price / book_value) if current_price and book_value and book_value > 0 else None,
        "bookValue": book_value,
        "dividendYield": (dividend_yield / 100.0) if dividend_yield else None,
        "returnOnEquity": (roe / 100.0) if roe else None,
        "marketCap": (market_cap_cr * 1e7) if market_cap_cr else None,
        "sharesOutstanding": shares_outstanding,
        "impliedSharesOutstanding": shares_outstanding,
        "financialCurrency": "INR",
        "faceValue": face_value,
        "roce": roce,
        "website": record.get("website"),
        "longBusinessSummary": record.get("about"),
    }

    # 52-week high/low
    high_low_raw = kr.get("highLow", {})
    if isinstance(high_low_raw, dict):
        raw_str = high_low_raw.get("raw", "")
        if "/" in str(raw_str):
            parts = str(raw_str).replace("₹", "").replace(",", "").split("/")
            try:
                info["fiftyTwoWeekHigh"] = float(parts[0].strip())
                info["fiftyTwoWeekLow"] = float(parts[1].strip())
            except (ValueError, IndexError):
                pass

    return info


def _screener_to_payload(record: dict) -> dict:
    """
    Transform a full Screener.in company record into the payload dict
    that angel_scraper.fetch_fundamental_payload() returns.
    """
    info = _build_info_dict(record)
    current_price = info.get("currentPrice")
    market_cap = info.get("marketCap")

    # Financial arrays
    income_stmt = _build_income_stmt(record.get("profitLoss", []))
    quarterly_income_stmt = _build_income_stmt(record.get("quarterlyResults", []), is_quarterly=True)
    balance_sheet = _build_balance_sheet(record.get("balanceSheet", []))
    cash_flow = _build_cash_flow(record.get("cashFlow", []))

    financial_arrays = {
        "income_stmt": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "quarterly_income_stmt": quarterly_income_stmt,
        "quarterly_balance_sheet": {},   # Not available from Screener per-quarter
        "quarterly_cash_flow": {},       # Not available from Screener per-quarter
    }

    # Shareholding
    shareholding = _build_shareholding(record.get("shareholding", []))

    # Ownership metrics (legacy format)
    ownership = {
        "F-10_heldPercentInsiders": shareholding.get("promoter_holding_pct"),
        "F-11_promoterPledges": shareholding.get("promoter_pledge_pct"),
        "F-12_heldPercentInstitutions": shareholding.get("institutional_holding_pct"),
    }

    # OHLC (approximate from current price)
    ohlc = {
        "open": current_price,
        "high": current_price,
        "low": current_price,
        "close": current_price,
    }

    return {
        "symbol": record.get("symbol") or record.get("nseCode"),
        "lastPrice": current_price,
        "volume": None,
        "marketCap": market_cap,
        "sharesOutstanding": info.get("sharesOutstanding"),
        "ohlc": ohlc,
        "ownership_metrics": ownership,
        "info": info,
        "financial_arrays": financial_arrays,
        "shareholding": shareholding,
        "screener_peers": record.get("peers", []),
        "data_source": "screener_api",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_screener_fundamentals(symbol: str) -> dict | None:
    """
    Fetch full fundamental data for an Indian stock via Apify Screener.in.
    Returns a payload dict in the same format as angel_scraper, or None on failure.
    Results are cached for 12 hours.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cache_key = f"screener_api_{sym}"

    # Check cache first
    cached = _read_cache(cache_key)
    if cached is not None:
        print(f"[screener_api] Cache hit for {sym}.")
        return cached

    with _lock:
        # Double-check after acquiring lock
        cached = _read_cache(cache_key)
        if cached is not None:
            return cached

        record = _call_apify_screener(sym)
        if record is None:
            return None

        payload = _screener_to_payload(record)
        _write_cache(cache_key, payload)
        print(f"[screener_api] Cached fundamentals for {sym}.")
        return payload


def fetch_screener_peer_metrics(symbol: str) -> dict | None:
    """
    Fetch peer comparison data from the cached/fresh Screener response.
    Returns the raw peers list from Screener, or None.
    """
    payload = fetch_screener_fundamentals(symbol)
    if payload is None:
        return None
    return payload.get("screener_peers")


def get_peer_stock_metrics(symbol: str) -> dict:
    """
    Fetch valuation/return/growth/leverage metrics for a single symbol
    using the Screener API. Returns a dict compatible with PeerSectorEvaluator.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    payload = fetch_screener_fundamentals(sym)
    if payload is None:
        return {
            "symbol": sym, "lastPrice": None, "pe": None,
            "operatingMargin": None, "roe": None, "revenueGrowth": None,
            "debtToEquity": None, "error": "screener_api returned None"
        }

    info = payload.get("info", {}) or {}
    kr = {}
    # Try to reconstruct key ratios
    pe = info.get("trailingPE")
    roe = info.get("returnOnEquity")
    operating_margin = None
    revenue_growth = None
    debt_to_equity = None

    # Compute operating margin from latest income statement
    fin_arrays = payload.get("financial_arrays", {}) or {}
    inc = fin_arrays.get("income_stmt", {})
    if inc:
        # Get the two most recent periods for growth calc
        sorted_periods = sorted(inc.keys(), reverse=True)
        if sorted_periods:
            latest = inc[sorted_periods[0]]
            revenue = latest.get("Total Revenue") or latest.get("Revenue")
            ebit = latest.get("EBIT") or latest.get("Operating Income")
            if revenue and ebit and revenue > 0:
                operating_margin = ebit / revenue

            # Revenue growth YoY
            if len(sorted_periods) >= 2:
                prev = inc[sorted_periods[1]]
                prev_revenue = prev.get("Total Revenue") or prev.get("Revenue")
                if revenue and prev_revenue and prev_revenue > 0:
                    revenue_growth = (revenue - prev_revenue) / prev_revenue

    # Debt to equity from balance sheet
    bs = fin_arrays.get("balance_sheet", {})
    if bs:
        sorted_bs = sorted(bs.keys(), reverse=True)
        if sorted_bs:
            latest_bs = bs[sorted_bs[0]]
            debt = latest_bs.get("Total Debt") or latest_bs.get("Long Term Debt")
            equity = latest_bs.get("Stockholders Equity") or latest_bs.get("Common Stock Equity")
            if debt is not None and equity and equity > 0:
                debt_to_equity = debt / equity

    return {
        "symbol": sym,
        "lastPrice": info.get("currentPrice"),
        "pe": pe,
        "operatingMargin": operating_margin,
        "roe": roe,
        "revenueGrowth": revenue_growth,
        "debtToEquity": debt_to_equity,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATAMOTORS"
    print(f"\n{'='*60}")
    print(f"  Testing Screener API for: {sym}")
    print(f"{'='*60}\n")

    result = fetch_screener_fundamentals(sym)
    if result:
        print(f"\n✅ Got data for {sym}")
        print(f"   Last Price: {result.get('lastPrice')}")
        print(f"   Market Cap: {result.get('marketCap')}")
        info = result.get("info", {})
        print(f"   Company: {info.get('longName')}")
        print(f"   P/E: {info.get('trailingPE')}")
        print(f"   ROE: {info.get('returnOnEquity')}")
        print(f"   Book Value: {info.get('bookValue')}")

        fin = result.get("financial_arrays", {})
        inc = fin.get("income_stmt", {})
        print(f"   Income statement periods: {list(inc.keys())[:5]}")
        bs = fin.get("balance_sheet", {})
        print(f"   Balance sheet periods: {list(bs.keys())[:5]}")
        cf = fin.get("cash_flow", {})
        print(f"   Cash flow periods: {list(cf.keys())[:5]}")

        sh = result.get("shareholding", {})
        print(f"   Promoter holding: {sh.get('promoter_holding_pct')}%")
        print(f"   FII stake: {sh.get('fii_stake')}%")
        print(f"   DII stake: {sh.get('dii_stake')}%")

        peers = result.get("screener_peers", [])
        print(f"   Peers: {[p.get('name') for p in peers[:5]]}")
    else:
        print(f"[screener_api] Failed to get data for {sym}")
        print("   Make sure APIFY_API_TOKEN is set in .env")
