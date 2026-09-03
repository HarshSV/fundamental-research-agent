"""
Screener.in shareholding + concall source.

Free, public, and covers essentially every NSE/BSE-listed company with ~12 quarters
of promoter / FII / DII / Government / Public holding - which fixes the "Awaiting NSE
Filing / N/A" gaps and powers the real multi-quarter ownership / FII-DII / promoter
trend charts. Also surfaces the latest concall transcript links for the AI summary.

Design: curl_cffi (real-browser TLS), disk cache (12h), never raises.
"""

import os
import re
import json
import time
import threading

_LIGATURE_MAP = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
})

try:
    from tools import ssl_bootstrap  # noqa: F401  (Windows TLS fix; no-op on cloud)
except Exception:
    pass

try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:  # pragma: no cover
    import requests as _http
    _HAVE_CFFI = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "screener")
TTL = 12 * 3600

_lock = threading.Lock()


def _num(s):
    try:
        v = float(str(s).replace(",", "").replace("%", "").replace("&nbsp;", "").strip())
        return v
    except Exception:
        return None


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


def _get(url):
    try:
        if _HAVE_CFFI:
            s = _http.Session(impersonate="chrome")
        else:
            s = _http.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
        r = s.get(url, timeout=25)
        if r.status_code == 200 and len(r.text) > 2000:
            return r.text
    except Exception as e:
        print(f"[screener] GET failed ({url}): {e}")
    return None


def _parse_shareholding(html):
    """Parse the quarterly shareholding-pattern table into series by holder class."""
    msec = re.search(r'id=["\']shareholding["\'].*?</section>', html, re.S)
    if not msec:
        return None
    sec = msec.group(0)
    mq = re.search(r'id=["\']quarterly-shp["\'].*?</table>', sec, re.S)
    block = mq.group(0) if mq else sec
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S)
    if not rows:
        return None

    quarters = []
    series = {"promoter": [], "fii": [], "dii": [], "government": [], "public": [], "others": []}
    num_holders = []
    label_map = [("promoter", "promoter"), ("fii", "fii"), ("dii", "dii"),
                 ("government", "government"), ("public", "public"), ("other", "others")]

    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        clean = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").replace("+", "").strip() for c in cells]
        clean = [c for c in clean if c != ""]
        if not clean:
            continue
        # Header row = the 12 quarter labels
        if re.match(r"^[A-Za-z]{3}\s+\d{4}$", clean[0]):
            quarters = clean[:]
            continue
        label = clean[0].lower()
        vals = [_num(c) for c in clean[1:]]
        if "shareholder" in label:
            num_holders = vals
            continue
        for key, dst in label_map:
            if key in label:
                series[dst] = vals
                break

    if not quarters or not series["promoter"]:
        return None

    n = len(quarters)
    def at(arr, i):
        return arr[i] if (arr and i < len(arr) and arr[i] is not None) else None
    latest_i = n - 1

    return {
        "status": "ok",
        "source": "Screener",
        "quarters": quarters,
        "as_of_quarter": quarters[latest_i],
        "promoter": series["promoter"],
        "fii": series["fii"],
        "dii": series["dii"],
        "government": series["government"],
        "public": series["public"],
        "num_shareholders": num_holders,
        "latest": {
            "promoter": at(series["promoter"], latest_i),
            "fii": at(series["fii"], latest_i),
            "dii": at(series["dii"], latest_i),
            "government": at(series["government"], latest_i),
            "public": at(series["public"], latest_i),
        },
        "prev": {
            "promoter": at(series["promoter"], latest_i - 1),
            "fii": at(series["fii"], latest_i - 1),
            "dii": at(series["dii"], latest_i - 1),
            "public": at(series["public"], latest_i - 1),
        },
    }


def _parse_concall_links(html):
    """Latest concall transcript links, newest-first (from Screener's Concalls list)."""
    links = []
    # Screener's Concalls section lists each call newest-first with a "Transcript"
    # anchor (usually a BSE AnnPdfOpen link that serves the PDF).
    msec = re.search(r"Concalls</h3>.*?</ul>", html, re.S)
    area = msec.group(0) if msec else html
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*[^<]*Transcript[^<]*</a>', area, re.I):
        u = m.group(1)
        if u not in links:
            links.append(u)
    if not links:  # fallback: any transcript-ish PDF anywhere on the page
        for m in re.finditer(r'href=["\']([^"\']+\.pdf)["\']', html, re.I):
            u = m.group(1)
            if re.search(r"transcri|concall|earnings", u, re.I) and u not in links:
                links.append(u)
    return links[:5]


def _parse_concall_list(html):
    """Per-month concall entries (newest first): [{date, url}]. url is the
    transcript PDF link for that month (None if Screener has no transcript yet)."""
    out = []
    msec = re.search(r"Concalls</h3>.*?</ul>", html, re.S)
    if not msec:
        return out
    seen = {}
    for li in re.findall(r"<li[^>]*>(.*?)</li>", msec.group(0), re.S):
        d = re.search(r"([A-Z][a-z]{2}\s+\d{4})", li)
        if not d:
            continue
        date = d.group(1)
        tr = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*[^<]*Transcript[^<]*</a>', li, re.I)
        url = tr.group(1) if tr else None
        # Dedup by month; keep the entry that actually has a transcript link.
        if date not in seen:
            seen[date] = {"date": date, "url": url}
            out.append(seen[date])
        elif url and not seen[date]["url"]:
            seen[date]["url"] = url
    return out[:8]


def download_transcript(url, max_chars=14000, max_pages=16):
    """Download a single transcript PDF (BSE/company link) and extract its text.
    Cached per-URL (and per max_pages/max_chars, when non-default, so a
    caller asking for MORE pages - e.g. B.4's Q&A-section scoring, which
    needs pages beyond the default 16-page/14000-char digest cap most
    callers use - doesn't silently get back a shorter, stale cached
    extract). Returns '' on any failure. Never raises."""
    if not url:
        return ""
    import hashlib
    suffix = "" if (max_chars, max_pages) == (14000, 16) else f"_{max_chars}_{max_pages}"
    ckey = "tr_" + hashlib.md5(url.encode("utf-8")).hexdigest() + suffix
    cached = _read_cache(ckey)
    if cached is not None:
        return cached.get("text", "")
    text = ""
    try:
        from pypdf import PdfReader
        import io as _io
        s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
        r = s.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) >= 5000:
            reader = PdfReader(_io.BytesIO(r.content))
            parts = []
            for page in reader.pages[:max_pages]:
                try:
                    # pypdf preserves Unicode ligature glyphs (ﬁ, ﬂ, ...) on
                    # professionally-typeset PDFs just like PyMuPDF does -
                    # "specific" extracts as "speciﬁc", silently breaking
                    # every "fi"/"fl"-containing keyword regex downstream
                    # (confirmed real: B.4.2's "we don't provide specific
                    # guidance" disclaimer match failed for exactly this
                    # reason before this fix).
                    parts.append((page.extract_text() or "").translate(_LIGATURE_MAP))
                except Exception:
                    continue
                if sum(len(p) for p in parts) > max_chars:
                    break
            text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()[:max_chars]
            if len(text) > 800:
                _write_cache(ckey, {"text": text})
    except Exception as e:
        print(f"[screener] transcript download failed ({url}): {e}")
    return text if len(text) > 800 else ""


def fetch_concall_list(symbol, name=None):
    """Public: per-month concall entries for the UI tabs (newest first).

    Same guard convention as tools.crisil_scraper.fetch_crisil_rationale /
    tools.nse_announcements.fetch_announcements: in tools.manual_mode's
    document-only manual workflow, this NEVER reaches live screener.in -
    B.4.3's fallback pathway (used when NSE's own transcript announcement
    isn't found) must not silently live-fetch just because the sub-point's
    gate let its compute_fn run for a different, uploaded document type.
    Returns [] (its existing "nothing found" contract - no caller of this
    function distinguishes not-checked from checked-and-empty, unlike
    fetch_announcements), never fabricated data."""
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return []
    sym = symbol.strip().upper().replace(".NS", "")
    try:
        return (fetch_screener(sym, name) or {}).get("concall_list") or []
    except Exception:
        return []


# Known renames/demergers where the NSE symbol no longer matches Screener's slug.
_SYMBOL_MAP = {"TATAMOTORS": "TMCV", "M&M": "M_M", "BAJAJ-AUTO": "BAJAJ_AUTO"}


def _parse_peers_table(html):
    """
    Parse Screener.in's peer-comparison table (from /api/company/<id>/peers/) into
    records shaped EXACTLY like the Apify actor's `peers` output, so the peer engine
    consumes either source unchanged. Columns (in order):
    S.No | Name | CMP | P/E | Mar Cap (Cr) | Div Yld % | NP Qtr (Cr) | Qtr Profit Var % |
    Sales Qtr (Cr) | Qtr Sales Var % | ROCE %
    """
    if not html:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        link = re.search(r"/company/([^/]+)/", row)
        if not link:
            continue  # header row or the trailing "Median" row (no company link)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
        if len(cells) < 11:
            continue
        sym = link.group(1).upper()
        out.append({
            "name": cells[1],
            "symbol": sym,
            "url": f"https://www.screener.in/company/{link.group(1)}/",
            "rank": len(out) + 1,
            "metrics": {
                "currentPrice": {"value": _num(cells[2])},
                "priceToEarning": {"value": _num(cells[3])},
                "marketCapitalization": {"value": _num(cells[4])},
                "dividendYield": {"value": _num(cells[5])},
                "netProfitLatestQuarter": {"value": _num(cells[6])},
                "yoyQuarterlyProfitGrowth": {"value": _num(cells[7])},
                "salesLatestQuarter": {"value": _num(cells[8])},
                "yoyQuarterlySalesGrowth": {"value": _num(cells[9])},
                "returnOnCapitalEmployed": {"value": _num(cells[10])},
            },
        })
    return out


def _row_history(table_html, label):
    """Return the numeric series for a labelled row in a Screener data table."""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html or "", re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        cells = [c for c in cells if c]
        if cells and cells[0].lower().strip().rstrip("%").strip() == label.lower():
            return [_num(c) for c in cells[1:] if _num(c) is not None]
    return []


def _ranges_table(html, title_substr):
    """Parse a Screener 'ranges-table' (Compounded Sales Growth, Return on Equity, ...)
    into {period_label: value}. Periods look like '10 Years:', '5 Years:', 'TTM:'."""
    out = {}
    for tbl in re.findall(r'<table class="ranges-table">(.*?)</table>', html or "", re.S):
        head = re.search(r"<th[^>]*>(.*?)</th>", tbl, re.S)
        if not head or title_substr.lower() not in re.sub(r"<[^>]+>", "", head.group(1)).lower():
            continue
        for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if len(cells) >= 2:
                out[cells[0].strip().rstrip(":").lower()] = _num(cells[1])
    return out


# ===========================================================================
# PRIMARY FINANCIALS SOURCE (P0 rework)
# Parse the P&L / balance sheet / cash flow / quarterly tables straight off the
# Screener.in company page - ONE HTML GET that replaces 6+ serial yfinance calls.
# Output matches the payload shape angel_scraper produces, so metrics_engine needs
# zero changes. INR throughout (no USD->INR conversion needed). Never raises.
# ===========================================================================

_MONTHS = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
           "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}


def _period_to_date(p):
    """'Mar 2023' -> '2023-03-31' so string sorting == chronological (metrics_engine
    sorts period keys as strings). Falls back to a bare year, else the raw label."""
    p = (p or "").strip()
    m = re.match(r"([A-Za-z]{3})\s*'?\s*(\d{2,4})", p)
    if m:
        mon = _MONTHS.get(m.group(1).lower(), "03")
        yr = m.group(2)
        if len(yr) == 2:
            yr = "20" + yr
        return f"{yr}-{mon}-31"
    m2 = re.match(r"(\d{4})", p)
    return f"{m2.group(1)}-03-31" if m2 else p


def _parse_data_table(html, section_id):
    """Parse a Screener data-table (id=profit-loss|balance-sheet|cash-flow|quarters)
    into {'periods': [labels], 'rows': {row_label_lower: [values]}}."""
    m = re.search(rf'id="{section_id}".*?</table>', html or "", re.S)
    if not m:
        return {"periods": [], "rows": {}}
    block = m.group(0)
    periods, rows = [], {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        ths = re.findall(r"<th[^>]*>(.*?)</th>", r, re.S)
        if ths and not periods:
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in ths]
            periods = [c for c in cells[1:] if c]
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if not tds:
            continue
        clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in tds]
        label = clean[0].replace("+", "").strip().rstrip("%").strip().lower()
        if label:
            rows[label] = [_num(c) for c in clean[1:]]
    return {"periods": periods, "rows": rows}


def _row_pick(rows, names):
    """First matching row series for any of the candidate labels (exact, then
    substring)."""
    for n in names:
        if n in rows:
            return rows[n]
    for n in names:
        for label, vals in rows.items():
            if n in label:
                return vals
    return None


def _build_income_grid(parsed):
    """Screener P&L/quarters table -> {date: {yfinance_row: value}} (INR)."""
    periods, rows = parsed["periods"], parsed["rows"]
    if not periods or not rows:
        return {}
    sales = _row_pick(rows, ["sales", "revenue", "total revenue", "revenue from operations",
                             "total income", "interest earned", "income"])
    expenses = _row_pick(rows, ["expenses", "total expenses"])
    op_profit = _row_pick(rows, ["operating profit", "financing profit"])  # Screener OP ~ EBITDA
    opm = _row_pick(rows, ["opm", "financing margin"])
    other_income = _row_pick(rows, ["other income"])
    interest = _row_pick(rows, ["interest"])
    depreciation = _row_pick(rows, ["depreciation"])
    pbt = _row_pick(rows, ["profit before tax", "profit before tax "])
    net_profit = _row_pick(rows, ["net profit", "profit after tax"])
    eps = _row_pick(rows, ["eps in rs", "eps"])

    grid = {}
    for i, p in enumerate(periods):
        col = {}

        def put(key, series, scale=1e7):
            if series and i < len(series) and series[i] is not None:
                col[key] = series[i] * scale

        put("Total Revenue", sales)
        put("Revenue", sales)
        put("Total Expenses", expenses)
        put("EBITDA", op_profit)
        put("Normalized EBITDA", op_profit)
        put("Other Income", other_income)
        put("Interest Expense", interest)
        put("Depreciation", depreciation)
        put("Pretax Income", pbt)
        put("Net Income", net_profit)
        put("Net Income Common Stockholders", net_profit)
        # EBIT = operating profit - depreciation (Screener "Operating Profit" is pre-dep).
        if op_profit and i < len(op_profit) and op_profit[i] is not None:
            dep = depreciation[i] if (depreciation and i < len(depreciation) and depreciation[i] is not None) else 0.0
            col["EBIT"] = (op_profit[i] - dep) * 1e7
            col["Operating Income"] = col["EBIT"]
        if opm and i < len(opm) and opm[i] is not None:
            col["Operating Margins"] = opm[i] / 100.0
        if eps and i < len(eps) and eps[i] is not None:
            col["Diluted EPS"] = eps[i]
            col["Basic EPS"] = eps[i]
        if col:
            grid[_period_to_date(p)] = col
    return grid


def _build_balance_grid(parsed):
    """Screener balance-sheet table -> {date: {yfinance_row: value}} (INR)."""
    periods, rows = parsed["periods"], parsed["rows"]
    if not periods or not rows:
        return {}
    equity_cap = _row_pick(rows, ["equity capital", "share capital"])
    reserves = _row_pick(rows, ["reserves"])
    borrowings = _row_pick(rows, ["borrowings", "borrowing"])
    other_liab = _row_pick(rows, ["other liabilities", "other liability"])
    total_assets = _row_pick(rows, ["total assets", "total liabilities"])
    fixed_assets = _row_pick(rows, ["fixed assets"])
    investments = _row_pick(rows, ["investments"])
    grid = {}
    for i, p in enumerate(periods):
        col = {}

        def v(series):
            return series[i] if (series and i < len(series) and series[i] is not None) else None

        ec, rv = v(equity_cap), v(reserves)
        if ec is not None or rv is not None:
            eq = (ec or 0.0) + (rv or 0.0)
            col["Stockholders Equity"] = eq * 1e7
            col["Common Stock Equity"] = eq * 1e7
            col["Total Equity Gross Minor Interest"] = eq * 1e7
        if v(borrowings) is not None:
            col["Total Debt"] = v(borrowings) * 1e7
            col["Long Term Debt"] = v(borrowings) * 1e7
        if v(total_assets) is not None:
            col["Total Assets"] = v(total_assets) * 1e7
        # Screener has no clean current-liabilities row; use Other Liabilities as a
        # proxy so ROCE (Total Assets - Current Liabilities) is computable (mirrors
        # the Apify-path convention in screener_api._build_balance_sheet).
        if v(other_liab) is not None:
            col["Current Liabilities"] = v(other_liab) * 1e7
            col["Total Current Liabilities"] = v(other_liab) * 1e7
        if v(fixed_assets) is not None:
            col["Net PPE"] = v(fixed_assets) * 1e7
        if v(investments) is not None:
            col["Investments"] = v(investments) * 1e7
        if col:
            grid[_period_to_date(p)] = col
    return grid


def _build_cashflow_grid(parsed):
    """Screener cash-flow table -> {date: {yfinance_row: value}} (INR)."""
    periods, rows = parsed["periods"], parsed["rows"]
    if not periods or not rows:
        return {}
    cfo = _row_pick(rows, ["cash from operating activity", "cash from operating activities"])
    cfi = _row_pick(rows, ["cash from investing activity", "cash from investing activities"])
    cff = _row_pick(rows, ["cash from financing activity", "cash from financing activities"])
    grid = {}
    for i, p in enumerate(periods):
        col = {}

        def put(key, series):
            if series and i < len(series) and series[i] is not None:
                col[key] = series[i] * 1e7

        put("Operating Cash Flow", cfo)
        put("Cash Flow From Continuing Operating Activities", cfo)
        put("Net Cash Provided By Operating Activities", cfo)
        put("Investing Cash Flow", cfi)
        put("Financing Cash Flow", cff)
        if col:
            grid[_period_to_date(p)] = col
    return grid


def _parse_top_ratios(html):
    """Screener 'top-ratios' list -> {name_lower: number}."""
    top = {}
    m = re.search(r'id="top-ratios".*?</ul>', html or "", re.S)
    if not m:
        return top
    for li in re.findall(r"<li[^>]*>(.*?)</li>", m.group(0), re.S):
        nm = re.search(r'class="name">(.*?)<', li, re.S)
        num = re.search(r'class="(?:number|value)">(.*?)</span>', li, re.S)
        if nm and num:
            key = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", nm.group(1))).strip().lower()
            top[key] = _num(re.sub(r"<[^>]+>", "", num.group(1)))
    return top


def _parse_about(html):
    """Best-effort company description from the 'About' profile block."""
    m = re.search(r'class="company-profile.*?<p[^>]*>(.*?)</p>', html or "", re.S)
    if not m:
        m = re.search(r'About</[^>]+>\s*<p[^>]*>(.*?)</p>', html or "", re.S)
    if m:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        return txt or None
    return None


def fetch_screener_financials(symbol, name=None):
    """
    PRIMARY financials source. Parse the full P&L / balance sheet / cash flow /
    quarterly tables + key ratios off the Screener.in company page in ONE GET.
    Returns a payload in angel_scraper's shape (lastPrice, info, financial_arrays,
    ownership_metrics, shareholding, screener_peers), or None if the page has no
    usable income statement (caller then falls through to yfinance/Apify). Cached
    12h. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cache_key = f"fin_{sym}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    try:
        slug = _SYMBOL_MAP.get(sym, sym)
        html = _get(f"https://www.screener.in/company/{slug}/consolidated/")
        if not html or 'id="profit-loss"' not in html:
            html = _get(f"https://www.screener.in/company/{slug}/")
        if not html or 'id="profit-loss"' not in html:
            r_slug = _resolve_slug(sym, name)
            if r_slug and r_slug != slug:
                html = _get(f"https://www.screener.in/company/{r_slug}/consolidated/") or \
                       _get(f"https://www.screener.in/company/{r_slug}/")
        if not html or 'id="profit-loss"' not in html:
            return None

        income = _build_income_grid(_parse_data_table(html, "profit-loss"))
        # Validation gate: no revenue -> unusable, let the fallback chain take over.
        if not income or not any("Total Revenue" in col for col in income.values()):
            print(f"[screener] financials for {sym}: no parseable revenue; deferring to fallback.")
            return None
        balance = _build_balance_grid(_parse_data_table(html, "balance-sheet"))
        cashflow = _build_cashflow_grid(_parse_data_table(html, "cash-flow"))
        quarterly = _build_income_grid(_parse_data_table(html, "quarters"))

        top = _parse_top_ratios(html)
        price = top.get("current price")
        mcap_cr = top.get("market cap")
        pe = top.get("stock p/e") or top.get("p/e")
        book_value = top.get("book value")
        roe = top.get("roe")
        div_yield = top.get("dividend yield")
        market_cap = (mcap_cr * 1e7) if mcap_cr else None
        shares = (market_cap / price) if (market_cap and price and price > 0) else None

        info = {
            "symbol": sym,
            "longName": name or sym,
            "shortName": name or sym,
            "currentPrice": price,
            "regularMarketPrice": price,
            "previousClose": price,
            "trailingPE": pe,
            "priceToBook": (price / book_value) if (price and book_value and book_value > 0) else None,
            "bookValue": book_value,
            "returnOnEquity": (roe / 100.0) if roe is not None else None,
            "dividendYield": (div_yield / 100.0) if div_yield is not None else None,
            "marketCap": market_cap,
            "sharesOutstanding": shares,
            "impliedSharesOutstanding": shares,
            "financialCurrency": "INR",
            "longBusinessSummary": _parse_about(html),
        }

        # Shareholding + peers + concall links come off the SAME page fetch already
        # done by fetch_screener(); reuse it (cached) rather than re-GETting.
        sh, peers = None, []
        try:
            sh = _parse_shareholding(html)
        except Exception:
            sh = None
        try:
            company_id = re.search(r'data-warehouse-id="(\d+)"', html)
            if company_id:
                peers = _parse_peers_table(_get(f"https://www.screener.in/api/company/{company_id.group(1)}/peers/")) or []
        except Exception:
            peers = []

        ownership = {
            "F-10_heldPercentInsiders": (sh or {}).get("latest", {}).get("promoter") if sh else None,
            "F-11_promoterPledges": None,
            "F-12_heldPercentInstitutions": (
                ((sh or {}).get("latest", {}).get("fii") or 0) + ((sh or {}).get("latest", {}).get("dii") or 0)
            ) if sh else None,
        }

        payload = {
            "symbol": sym,
            "lastPrice": price,
            "volume": None,
            "marketCap": market_cap,
            "sharesOutstanding": shares,
            "ohlc": {"open": price, "high": price, "low": price, "close": price},
            "ownership_metrics": ownership,
            "info": info,
            "financial_arrays": {
                "income_stmt": income,
                "balance_sheet": balance,
                "cash_flow": cashflow,
                "quarterly_income_stmt": quarterly,
                "quarterly_balance_sheet": {},
                "quarterly_cash_flow": {},
            },
            "shareholding": sh or {},
            "screener_peers": peers,
            "data_source": "screener_scrape",
        }
        _write_cache(cache_key, payload)
        print(f"[screener] financials for {sym}: {len(income)} annual / {len(quarterly)} quarterly periods "
              f"(price={price}, mcap={mcap_cr}Cr).")
        return payload
    except Exception as e:
        print(f"[screener] financials fetch failed for {sym}: {e}")
        return None


def fetch_screener_moat_data(symbol, name=None):
    """
    Scrape the moat-relevant fundamentals Screener.in publishes for a company:
    ROCE (level + multi-year history), ROE track record (10/5/3y/last), operating-
    margin (OPM) history, compounded sales/profit growth, working-capital efficiency
    (cash conversion cycle), and Screener's auto-generated Pros/Cons. Company-specific,
    free, cloud-safe. Returns a dict (or {} on failure). Cached 12h. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cache_key = f"moat_{sym}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    try:
        slug = _SYMBOL_MAP.get(sym, sym)
        html = _get(f"https://www.screener.in/company/{slug}/consolidated/")
        if not html or 'id="top-ratios"' not in html:
            html = _get(f"https://www.screener.in/company/{slug}/")
        if not html:
            r_slug = _resolve_slug(sym, name)
            if r_slug and r_slug != slug:
                html = _get(f"https://www.screener.in/company/{r_slug}/consolidated/") or \
                       _get(f"https://www.screener.in/company/{r_slug}/")
        if not html:
            return {}

        def _clean(s):
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()

        # --- Top ratios (latest ROCE / ROE / P/E / Div yield) ---
        top = {}
        mtop = re.search(r'id="top-ratios".*?</ul>', html, re.S)
        if mtop:
            for li in re.findall(r"<li[^>]*>(.*?)</li>", mtop.group(0), re.S):
                nm = re.search(r'class="name">(.*?)<', li, re.S)
                num = re.search(r'class="number">(.*?)<', li, re.S)
                if nm and num:
                    top[_clean(nm.group(1)).lower()] = _num(num.group(1))

        # --- Pros / Cons (Screener's own qualitative flags) ---
        def _bullets(klass):
            m = re.search(rf'class="{klass}".*?<ul>(.*?)</ul>', html, re.S)
            return [_clean(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)] if m else []
        pros, cons = _bullets("pros"), _bullets("cons")

        # --- Histories ---
        mratios = re.search(r'id="ratios".*?</table>', html, re.S)
        ratios_tbl = mratios.group(0) if mratios else ""
        mpl = re.search(r'id="profit-loss".*?</table>', html, re.S)
        pl_tbl = mpl.group(0) if mpl else ""

        roce_hist = _row_history(ratios_tbl, "ROCE %") or _row_history(ratios_tbl, "ROCE")
        opm_hist = _row_history(pl_tbl, "OPM %") or _row_history(pl_tbl, "OPM")
        ccc = _row_history(ratios_tbl, "Cash Conversion Cycle")
        wcd = _row_history(ratios_tbl, "Working Capital Days")

        roe_ranges = _ranges_table(html, "Return on Equity")
        sales_growth = _ranges_table(html, "Compounded Sales Growth")
        profit_growth = _ranges_table(html, "Compounded Profit Growth")

        data = {
            "symbol": sym,
            "roce_latest": top.get("roce"),
            "roe_latest": top.get("roe"),
            "pe": top.get("stock p/e") or top.get("p/e"),
            "dividend_yield": top.get("dividend yield"),
            "debt_to_equity": top.get("debt to equity"),
            "roce_history": roce_hist,
            "opm_history": opm_hist,
            "cash_conversion_cycle": ccc[-1] if ccc else None,
            "working_capital_days": wcd[-1] if wcd else None,
            "roe_3y": roe_ranges.get("3 years"),
            "roe_5y": roe_ranges.get("5 years"),
            "roe_10y": roe_ranges.get("10 years"),
            "roe_last": roe_ranges.get("last year"),
            "sales_growth_5y": sales_growth.get("5 years"),
            "sales_growth_3y": sales_growth.get("3 years"),
            "sales_growth_ttm": sales_growth.get("ttm"),
            "profit_growth_5y": profit_growth.get("5 years"),
            "profit_growth_3y": profit_growth.get("3 years"),
            "profit_growth_ttm": profit_growth.get("ttm"),
            "pros": pros,
            "cons": cons,
        }
        _write_cache(cache_key, data)
        print(f"[screener] moat data for {sym}: ROCE={data['roce_latest']} ROE3y={data['roe_3y']} OPM_hist={len(opm_hist)}")
        return data
    except Exception as e:
        print(f"[screener] moat data fetch failed for {sym}: {e}")
        return {}


def fetch_screener_peers(symbol, name=None):
    """
    FREE size/sector-aware peer list from Screener.in - no Apify, no API key, and it
    works from cloud hosts (screener.in is globally reachable, unlike NSE). Returns a
    list of Apify-shaped peer records (incl. the target itself), or [] on failure.
    Cached 12h. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cache_key = f"peers_{sym}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    try:
        m = None
        html = None
        # 1. Direct NSE-symbol slug FIRST. Screener uses the NSE symbol as the slug for
        # the vast majority of stocks; going straight to it avoids search picking a more
        # famous namesake (e.g. "APOLLO" search -> Apollo Hospitals, but the NSE ticker
        # APOLLO is Apollo Micro Systems). Known renames are mapped explicitly.
        direct_slug = _SYMBOL_MAP.get(sym, sym)
        direct = _get(f"https://www.screener.in/company/{direct_slug}/")
        if direct:
            m = re.search(r'data-warehouse-id="(\d+)"', direct)
            if m:
                html = direct
        # 2. Fall back to name/search slug resolution (BSE-coded small caps, odd slugs).
        if not m:
            slug = _resolve_slug(sym, name)
            if slug and slug != direct_slug:
                html = _get(f"https://www.screener.in/company/{slug}/")
                if html:
                    m = re.search(r'data-warehouse-id="(\d+)"', html)
        if not html or not m:
            print(f"[screener] could not resolve a peer page for {sym}.")
            return []
        company_id = m.group(1)
        peers_html = _get(f"https://www.screener.in/api/company/{company_id}/peers/")
        peers = _parse_peers_table(peers_html)
        if peers:
            _write_cache(cache_key, peers)
            print(f"[screener] free peer list for {sym}: {len(peers)} rows.")
        return peers
    except Exception as e:
        print(f"[screener] free peers fetch failed for {sym}: {e}")
        return []


def _search_slug(query):
    """Hit Screener's search API (tiny JSON) and return the first company's slug."""
    if not query:
        return None
    try:
        import urllib.parse
        s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
        r = s.get(f"https://www.screener.in/api/company/search/?q={urllib.parse.quote(query)}", timeout=15)
        if r.status_code == 200:
            data = json.loads(r.text)
            if data and isinstance(data, list):
                m = re.search(r"/company/([^/]+)/", data[0].get("url", ""))
                if m:
                    return m.group(1)
    except Exception as e:
        print(f"[screener] search failed for {query!r}: {e}")
    return None


def _resolve_slug(sym, name=None):
    """Screener slug can differ from the NSE symbol (renames/demergers, e.g.
    TATAMOTORS -> TMCV; small caps indexed by BSE code). Resolve via a known map,
    then symbol search, then company-name search."""
    if sym in _SYMBOL_MAP:
        return _SYMBOL_MAP[sym]
    for q in (sym, name):
        slug = _search_slug(q)
        if slug:
            return slug
    return None


def fetch_screener(symbol, name=None):
    """
    Public entry point. Returns {shareholding: {...}, concall_links: [...]} or a
    safe empty payload. Never raises. `name` (company long name) helps resolve
    renamed/demerged tickers whose NSE symbol no longer matches Screener's slug.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    cached = _read_cache(sym)
    if cached is not None:
        return cached

    with _lock:
        cached = _read_cache(sym)
        if cached is not None:
            return cached
        html = None
        for suffix in ("consolidated/", ""):
            html = _get(f"https://www.screener.in/company/{sym}/{suffix}")
            if html:
                break
        if html is None:
            # Slug differs from the NSE symbol (rename/demerger) -> resolve via search.
            slug = _resolve_slug(sym, name)
            if slug and slug.upper() != sym:
                for suffix in ("consolidated/", ""):
                    html = _get(f"https://www.screener.in/company/{slug}/{suffix}")
                    if html:
                        print(f"[screener] resolved {sym} -> slug {slug}.")
                        break
        result = {"shareholding": None, "concall_links": []}
        if html:
            try:
                result["shareholding"] = _parse_shareholding(html)
            except Exception as e:
                print(f"[screener] shareholding parse error for {sym}: {e}")
            try:
                result["concall_links"] = _parse_concall_links(html)
                result["concall_list"] = _parse_concall_list(html)
            except Exception as e:
                print(f"[screener] concall parse error for {sym}: {e}")
        if result["shareholding"]:
            _write_cache(sym, result)
        return result


def fetch_concall_text(symbol, max_chars=14000, name=None):
    """
    Download the latest concall / earnings-call transcript PDF (from Screener's
    document links) and extract its text, so the AI summary is grounded in the
    ACTUAL transcript rather than inferred. Cached per symbol. Returns
    {"text": str, "url": str} or {"text": "", "url": None}. Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"concall_{sym}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    out = {"text": "", "url": None}
    try:
        links = (fetch_screener(sym, name) or {}).get("concall_links") or []
        if not links:
            return out
        try:
            from pypdf import PdfReader
        except Exception as e:
            print(f"[screener] pypdf unavailable: {e}")
            return out
        import io as _io

        def _download_one(url):
            try:
                s = _http.Session(impersonate="chrome") if _HAVE_CFFI else _http.Session()
                r = s.get(url, timeout=30)
                if r.status_code != 200 or len(r.content) < 5000:
                    return None
                reader = PdfReader(_io.BytesIO(r.content))
                parts = []
                for page in reader.pages[:16]:
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:
                        continue
                    if sum(len(p) for p in parts) > max_chars:
                        break
                text = re.sub(r"[ \t]+", " ", "\n".join(parts)).strip()
                return text if len(text) > 800 else None
            except Exception as e:
                print(f"[screener] transcript download failed ({url}): {e}")
                return None

        # Download the (up to 3) candidate PDFs concurrently instead of one at a
        # time - sequentially this was up to 3x a 30s timeout (90s worst case) on
        # a cold cache; in parallel it's bounded by the slowest single download.
        from concurrent.futures import ThreadPoolExecutor
        candidates = links[:3]
        with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
            results = list(ex.map(_download_one, candidates))
        for url, text in zip(candidates, results):
            if text:
                out = {"text": text[:max_chars], "url": url}
                _write_cache(ckey, out)
                print(f"[screener] concall transcript fetched for {sym} ({len(out['text'])} chars).")
                break
    except Exception as e:
        print(f"[screener] concall fetch error for {sym}: {e}")
    return out


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "ONGC"
    print(json.dumps(fetch_screener(arg), indent=2)[:1200])
    print("--- concall ---")
    c = fetch_concall_text(arg)
    print("url:", c["url"], "| chars:", len(c["text"]))
    print(c["text"][:500])
