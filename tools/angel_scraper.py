import os
import time
import requests
import pyotp
try:
    from SmartApi import SmartConnect
except Exception as _smartapi_import_error:
    # The `smartapi-python` package (requirements.txt) can be absent/broken
    # in a given environment (not installed, incompatible Python version,
    # etc.) - that used to crash this WHOLE module at import time, which
    # took down `market_price.get_live_price()`'s entire price pipeline
    # before it ever reached the yfinance fallback this class already
    # implements for auth/API failures. An unavailable Angel SDK should
    # degrade to yfinance-only, exactly like a failed Angel login already
    # does - not silently return no price at all for every ratio that needs
    # one (P/E, P/B, P/S, Dividend Yield, EV/EBITDA, FCF Yield, Price/CF).
    SmartConnect = None
    print(f"[angel_scraper] SmartApi unavailable ({_smartapi_import_error}) - "
          f"Angel One live-tick path disabled, yfinance fallback only.")
import yfinance as yf
from dotenv import load_dotenv

# Load env variables from root .env if it exists
load_dotenv()

# Process-level Angel One session cache. Logging in (TOTP + generateSession) is a
# real network round-trip; re-running it on every single AngelDataScraper()
# instantiation - which used to happen once per /generate-report request - was
# pure wasted latency, since an Angel session stays valid for hours. Reuse the
# same authenticated SmartConnect object across requests until it expires.
_SESSION_TTL = 6 * 3600
_session_cache = {"smart_connect": None, "authenticated": False, "ts": 0.0}
# Process-wide Scrip Master cache, same rationale as _session_cache above -
# `self.scrip_master` was an INSTANCE attribute, so it reset to None on
# every fresh `AngelDataScraper()` construction even though the same
# 151,191-row instrument list is identical for the whole process's
# lifetime. Confirmed real cost: a single qualitative analysis run
# constructs a fresh AngelDataScraper() independently from several
# different compute_fn's (A.4's growth fallback alone does it once per
# A.4/A.4.A/A.4.B/A.4.C/A.4.D sub-point - 5 times for one company), each
# re-parsing the same multi-MB on-disk JSON file from scratch. Sharing it
# at module level turns that into one parse per process, not one per
# instantiation.
_scrip_master_cache = {"data": None, "failed": False}
# Short-lived process-wide cache for fetch_fundamental_payload - see that
# method's docstring. 5 minutes is long enough to dedupe every call
# within a single analysis run, short enough that a live price genuinely
# doesn't go stale across separate requests.
_FUNDAMENTAL_PAYLOAD_TTL = 300
_fundamental_payload_cache = {}


def _usd_inr_rate():
    """Best-effort live USD->INR rate; falls back to a sane constant on failure."""
    for getter in (
        lambda: getattr(yf.Ticker('USDINR=X').fast_info, 'last_price', None),
        lambda: (yf.Ticker('USDINR=X').info or {}).get('regularMarketPrice'),
    ):
        try:
            r = getter()
            if r and 50 < float(r) < 150:
                return float(r)
        except Exception:
            continue
    return 83.0


def normalize_financials_to_inr(financial_arrays, financial_currency, fx_rate=None):
    """
    yfinance reports many Indian companies' financial statements in USD even on the
    `.NS` ticker (info['financialCurrency'] == 'USD'), while their market price is in
    INR. Left uncorrected, revenue/PAT/cash-flow show ~80x too small and the DCF /
    fair-value collapse. This converts monetary statement lines to INR.

    Share-count and rate/ratio rows are currency-independent and are left untouched,
    so derived ratios (margins, ROE, D/E) stay correct.

    Returns (financial_arrays, fx_used_or_None). Never raises.
    """
    try:
        if not financial_arrays or not financial_currency:
            return financial_arrays, None
        if str(financial_currency).upper() == 'INR':
            return financial_arrays, None
        fx = fx_rate if (fx_rate and fx_rate > 0) else _usd_inr_rate()
        SKIP = ('share', 'rate', 'ratio')  # counts & ratios must not be scaled
        for stmt_grid in financial_arrays.values():
            if not isinstance(stmt_grid, dict):
                continue
            for rows in stmt_grid.values():
                if not isinstance(rows, dict):
                    continue
                for row_name, val in list(rows.items()):
                    if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
                        continue
                    if any(s in str(row_name).lower() for s in SKIP):
                        continue
                    rows[row_name] = val * fx
        print(f"[angel_scraper] Normalized financial statements {financial_currency}->INR at {fx:.2f}.")
        return financial_arrays, fx
    except Exception as e:
        print(f"[angel_scraper] Currency normalization skipped: {e}")
        return financial_arrays, None


def compute_pe_band(symbol, income_stmt_annual, current_pe=None):
    """
    Derive a historical P/E band entirely from FREE data: monthly price history
    (yfinance) divided by the company's annual EPS (already INR-normalized in our
    income statement). Returns a series + median/min/max so the UI can draw a
    valuation band chart. Never raises - returns None if it can't be built.
    """
    try:
        sym = str(symbol).strip().upper().replace('.NS', '')
        # Build EPS-by-fiscal-year from the (INR) income statement.
        eps_by_year = {}
        for date_str, rows in (income_stmt_annual or {}).items():
            if not isinstance(rows, dict):
                continue
            eps = None
            for key in ('Diluted EPS', 'Basic EPS'):
                if rows.get(key) is not None:
                    eps = rows.get(key); break
            if eps is None:
                for k, v in rows.items():
                    if 'eps' in str(k).lower() and v is not None:
                        eps = v; break
            try:
                yr = int(str(date_str)[:4])
            except Exception:
                continue
            if eps is not None and isinstance(eps, (int, float)) and eps > 0:
                eps_by_year[yr] = float(eps)
        if len(eps_by_year) < 2:
            return None

        hist = yf.Ticker(f"{sym}.NS").history(period="5y", interval="1mo")
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None

        years_sorted = sorted(eps_by_year.keys())
        series = []
        for ts, close in hist['Close'].items():
            try:
                price = float(close)
                if price <= 0:
                    continue
                yr = ts.year
                # use the most recent fiscal-year EPS available at/just before this date
                use_yr = None
                for y in years_sorted:
                    if y <= yr:
                        use_yr = y
                if use_yr is None:
                    use_yr = years_sorted[0]
                eps = eps_by_year[use_yr]
                pe = price / eps
                if 0 < pe < 500:  # guard against outliers
                    series.append({"date": ts.strftime("%Y-%m"), "pe": round(pe, 2)})
            except Exception:
                continue
        if len(series) < 6:
            return None

        pes = [p["pe"] for p in series]
        pes_sorted = sorted(pes)
        n = len(pes_sorted)
        median = pes_sorted[n // 2] if n % 2 else (pes_sorted[n // 2 - 1] + pes_sorted[n // 2]) / 2
        cur = current_pe if (current_pe and current_pe > 0) else pes[-1]
        return {
            "series": series,
            "median": round(median, 2),
            "min": round(min(pes), 2),
            "max": round(max(pes), 2),
            "current": round(float(cur), 2),
        }
    except Exception as e:
        print(f"[angel_scraper] P/E band skipped: {e}")
        return None


class AngelDataScraper:
    """
    Handles real-time data scraping from Angel One SmartAPI.
    Uses daily session token generation with TOTP (2FA).
    Falls back to yfinance dynamically if authentication or API limits fail.
    """
    def __init__(self):
        self.api_key = os.getenv('ANGEL_API_KEY')
        self.client_code = os.getenv('ANGEL_CLIENT_CODE')
        self.password = os.getenv('ANGEL_PASSWORD')
        self.totp_secret = os.getenv('ANGEL_TOTP_SECRET')
        
        self.smart_connect = None
        self.authenticated = False
        self.scrip_master = None

        # Reuse a still-fresh session instead of re-authenticating (TOTP +
        # generateSession network call) on every instantiation.
        cached = _session_cache
        if cached["authenticated"] and cached["smart_connect"] is not None \
                and (time.time() - cached["ts"]) < _SESSION_TTL:
            self.smart_connect = cached["smart_connect"]
            self.authenticated = True
            return

        # Initialize and log in
        self._login()

    def _login(self):
        """
        Performs authentication via SmartConnect and generates a session.
        Uses pyotp to handle the 2FA Layer (TOTP).
        """
        # Retrieve credentials directly from environment as requested
        api_key = os.getenv("ANGEL_API_KEY")
        client_code = os.getenv("ANGEL_CLIENT_CODE")
        password = os.getenv("ANGEL_PASSWORD")
        totp_secret = os.getenv("ANGEL_TOTP_SECRET")

        if SmartConnect is None:
            print("[AngelDataScraper] SmartApi package unavailable in this environment - sliding over to yfinance fallback.")
            return False

        if not all([api_key, client_code, password, totp_secret]) or \
           any(p in (api_key or "") for p in ["your_copied", "dummy", "here"]):
            print("[AngelDataScraper] Warning: One or more Angel One credentials (ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PASSWORD, ANGEL_TOTP_SECRET) are missing or set to placeholder values. Sliding over to yfinance fallback.")
            return False

        try:
            print("[AngelDataScraper] Connecting to SmartConnect...")
            # Initialize the SmartConnect session using ANGEL_API_KEY
            self.smart_connect = SmartConnect(api_key=api_key)
            
            # Programmatically generate the 2FA token using pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
            totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET").strip()).now()
            
            print(f"[AngelDataScraper] Generated TOTP: {totp}. Logging in user: {client_code}...")
            
            # Initialize the SmartConnect session using client code and password
            session = self.smart_connect.generateSession(client_code, password, totp)
            
            if session.get('status') is True:
                print("[AngelDataScraper] Authentication successful! Session established.")
                self.authenticated = True
                _session_cache["smart_connect"] = self.smart_connect
                _session_cache["authenticated"] = True
                _session_cache["ts"] = time.time()
                return True
            else:
                msg = session.get('message', 'Unknown error')
                print(f"[AngelDataScraper] Warning: Authentication failed (Response: {msg}). Sliding over to yfinance fallback.")
                return False
        except Exception as e:
            if "App Deactive" in str(e) or "auth" in str(e).lower() or "active" in str(e).lower():
                print(f"[AngelDataScraper] Warning: SmartAPI Authentication failed / App Deactive ({e}). Gracefully sliding over to yfinance fallback.")
            else:
                print(f"[AngelDataScraper] Warning during login initialization: {e}. Gracefully sliding over to yfinance fallback.")
            return False

    def _load_scrip_master(self):
        """
        Loads the official Angel One Instrument List (Scrip Master), preferring a
        fresh on-disk cache so we don't re-download the multi-MB file on every
        process start. If the download fails (common behind a TLS-inspecting
        firewall, where it read-times-out), the failure is memoized for the
        session so subsequent quote calls skip straight to the yfinance fallback
        instead of eating another full timeout every single time - that repeated
        timeout was the root cause of multi-minute quote latency.
        """
        if self.scrip_master is not None:
            return
        # Process-wide first: another AngelDataScraper instance (this
        # same pipeline run, a different compute_fn) may have already
        # loaded it - reuse that in-memory list instead of re-reading the
        # multi-MB disk cache file all over again.
        if _scrip_master_cache["data"] is not None:
            self.scrip_master = _scrip_master_cache["data"]
            return
        if _scrip_master_cache["failed"] or getattr(self, '_scrip_master_failed', False):
            return  # already failed this session - don't retry the slow download

        import json as _json
        import tempfile
        import time as _t
        cache_path = os.path.join(tempfile.gettempdir(), 'navrist_angel_scrip_master.json')

        # Serve from disk cache when it's less than a day old.
        try:
            if os.path.exists(cache_path) and (_t.time() - os.path.getmtime(cache_path) < 86400):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.scrip_master = _json.load(f)
                _scrip_master_cache["data"] = self.scrip_master
                print(f"[AngelDataScraper] Loaded {len(self.scrip_master)} instruments from disk cache.")
                return
        except Exception as e:
            print(f"[AngelDataScraper] Scrip master disk cache unreadable ({e}); will download.")

        try:
            print("[AngelDataScraper] Downloading Angel One Scrip Master json...")
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                self.scrip_master = response.json()
                _scrip_master_cache["data"] = self.scrip_master
                print(f"[AngelDataScraper] Loaded {len(self.scrip_master)} instrument tokens from Scrip Master.")
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        _json.dump(self.scrip_master, f)
                except Exception:
                    pass  # cache write is best-effort
            else:
                print(f"[AngelDataScraper] Failed to download Scrip Master. Status Code: {response.status_code}")
                self._scrip_master_failed = True
                _scrip_master_cache["failed"] = True
        except Exception as e:
            print(f"[AngelDataScraper] Failed to fetch Instrument List: {e}")
            self._scrip_master_failed = True
            _scrip_master_cache["failed"] = True

    def _resolve_symbol(self, symbol: str) -> dict:
        """
        Finds matching token and trading symbol details. Tries NSE first
        (most Indian-listed companies trade there and it's the deepest/most
        liquid quote), then falls back to BSE - many smaller/SME-IPO
        companies (e.g. Prime Fresh Limited, BSE scrip code 540404) are
        listed ONLY on BSE and were previously unresolvable here, silently
        blanking every market-price-dependent ratio (P/E, P/B, P/S,
        Dividend Yield, EV/EBITDA, FCF Yield, Price/Cash Flow, Altman
        Z-Score, and everything derived from them) for any BSE-only
        company, generically - not specific to one symbol.
        """
        self._load_scrip_master()
        if not self.scrip_master:
            return None

        clean_symbol = symbol.strip().upper()
        if clean_symbol.endswith('.NS') or clean_symbol.endswith('.BO'):
            clean_symbol = clean_symbol[:-3]

        # Match name or trading symbol (typically NAME=INFY, SYMBOL=INFY-EQ)
        for exch in ('NSE', 'BSE'):
            for instrument in self.scrip_master:
                if instrument.get('exch_seg') == exch:
                    if instrument.get('name') == clean_symbol or instrument.get('symbol') == f"{clean_symbol}-EQ":
                        return instrument
        return None

    def _serialize_df(self, df) -> dict:
        """
        Safely serializes a pandas DataFrame to a dictionary, stringifying keys
        (like columns representing Dates/Timestamps) and handling NaN/NaT values
        for clean JSON serialization.
        """
        if df is None or df.empty:
            return {}
        try:
            res = {}
            for col in df.columns:
                col_str = str(col.date()) if hasattr(col, 'date') else str(col)
                res[col_str] = {}
                for idx, val in df[col].items():
                    import pandas as pd
                    if pd.isna(val):
                        val = None
                    elif hasattr(val, 'item'):
                        val = val.item()
                    res[col_str][str(idx)] = val
            return res
        except Exception as e:
            print(f"[AngelDataScraper] Warning: DataFrame serialization failed: {e}")
            return {}

    def _fetch_from_yfinance_fallback(self, symbol: str) -> dict:
        """
        Last-resort fallback fetching fundamental/market metrics using yfinance.
        Only called if both Angel One and Screener API fail.
        """
        print(f"[AngelDataScraper] Executing last-resort yfinance fallback for: {symbol}")
        try:
            symbol_ns = symbol.upper()
            if not symbol_ns.endswith('.NS'):
                symbol_ns = f"{symbol_ns}.NS"
                
            from tools.yf_cache import cached_info
            ticker = yf.Ticker(symbol_ns)
            info = cached_info(symbol_ns)

            last_price = info.get('currentPrice', info.get('lastPrice', info.get('regularMarketPrice')))
            volume = info.get('volume', info.get('regularMarketVolume'))
            
            # Format OHLC
            ohlc = {
                'open': info.get('open', info.get('regularMarketOpen')),
                'high': info.get('high', info.get('regularMarketDayHigh')),
                'low': info.get('low', info.get('regularMarketDayLow')),
                'close': info.get('previousClose', info.get('regularMarketPreviousClose'))
            }
            
            # Format ownership metrics
            ownership = {
                'F-10_heldPercentInsiders': info.get('heldPercentInsiders'),
                'F-11_promoterPledges': info.get('promoterPledges', None),
                'F-12_heldPercentInstitutions': info.get('heldPercentInstitutions')
            }

            # Fetch financial arrays
            financial_arrays = {}
            try:
                financial_arrays = {
                    'quarterly_income_stmt': self._serialize_df(ticker.quarterly_income_stmt),
                    'quarterly_balance_sheet': self._serialize_df(ticker.quarterly_balance_sheet),
                    'quarterly_cash_flow': self._serialize_df(ticker.quarterly_cashflow),
                    'income_stmt': self._serialize_df(ticker.income_stmt),
                    'balance_sheet': self._serialize_df(ticker.balance_sheet),
                    'cash_flow': self._serialize_df(ticker.cashflow)
                }
            except Exception as yf_fin_err:
                print(f"[AngelDataScraper] Warning: Failed to populate financial arrays in fallback: {yf_fin_err}")
            
            return {
                'lastPrice': last_price,
                'volume': volume,
                'ohlc': ohlc,
                'ownership_metrics': ownership,
                'info': info,
                'financial_arrays': financial_arrays
            }
            
        except Exception as e:
            print(f"[AngelDataScraper] WARNING: yfinance fallback also failed for {symbol}: {e}")
            return {
                'lastPrice': None,
                'volume': None,
                'ohlc': {'open': None, 'high': None, 'low': None, 'close': None},
                'ownership_metrics': {
                    'F-10_heldPercentInsiders': None,
                    'F-11_promoterPledges': None,
                    'F-12_heldPercentInstitutions': None
                },
                'financial_arrays': {},
                'info': {},
                'error': str(e)
            }

    def _fetch_with_fallback_chain(self, symbol: str) -> dict:
        """
        Cascading data fetch, Screener-primary (P0 rework):
          1. Direct Screener.in scrape - ONE HTML page, INR, complete financials.
             Replaces 6+ serial yfinance calls; fast and cloud-reliable.
          2. yfinance - fallback for tickers Screener can't parse (odd slugs, banks).
        Returns the first result that actually has financial statements.
        """
        # 1. Direct Screener.in scrape (PRIMARY).
        try:
            from tools.screener_scraper import fetch_screener_financials
            screener = fetch_screener_financials(symbol)
            if screener is not None and (screener.get('financial_arrays') or {}).get('income_stmt'):
                print(f"[AngelDataScraper] Screener.in scrape is primary source for {symbol}.")
                return screener
        except Exception as e:
            print(f"[AngelDataScraper] Screener.in scrape unavailable for {symbol}: {e}")

        # 2. yfinance fallback.
        result = self._fetch_from_yfinance_fallback(symbol)
        return result

    def fetch_live_quote(self, symbol: str, bse_code: str = None) -> dict:
        """
        Lightweight real-time quote (LTP + OHLC + volume) for live tracking/polling.
        Deliberately does NOT pull financial statements, so it is cheap to call on a
        short interval. Uses Angel One live market data when authenticated, else a
        fast yfinance fallback. Never raises.

        `bse_code` (optional) is the company's real BSE scrip code, as
        printed in its own Annual Report/registry - a stable,
        exchange-assigned identifier, independent of whatever internal
        registry `symbol` this system happens to key the company under.
        Used as a DIRECT, exact fallback token match on the BSE segment
        when name/symbol-based resolution fails - covers the case where
        the internal `symbol` is a synthetic placeholder that was never a
        real tradeable ticker (see manual_document_pipeline.py's
        `_extract_listing_identifiers`/`_backfill_listing_identifiers`).
        """
        symbol_clean = symbol.strip().upper()
        if symbol_clean.endswith('.NS'):
            symbol_clean = symbol_clean[:-3]

        # Preferred path: Angel One live tick
        if self.authenticated and self.smart_connect:
            try:
                inst = self._resolve_symbol(symbol_clean)
                if not inst and bse_code:
                    self._load_scrip_master()
                    inst = next((i for i in (self.scrip_master or [])
                                 if i.get('exch_seg') == 'BSE' and str(i.get('token')) == str(bse_code)), None)
                if inst:
                    token = inst.get('token')
                    exch = inst.get('exch_seg') or 'NSE'
                    md = self.smart_connect.getMarketData("FULL", {exch: [token]})
                    if md.get('status') is True:
                        items = md.get('data', {}).get('fetched', [])
                        if items:
                            d = items[0]
                            return {
                                'symbol': symbol_clean, 'ltp': d.get('ltp'),
                                'open': d.get('open'), 'high': d.get('high'),
                                'low': d.get('low'), 'close': d.get('close'),
                                'volume': d.get('tradeVolume') or d.get('volume'),
                                'source': 'angel'
                            }
            except Exception as e:
                print(f"[AngelDataScraper] live quote via Angel failed for {symbol_clean}: {e}")

        # Fallback: yfinance fast quote. Try NSE (".NS", by trading symbol)
        # first since it's most Indian-listed companies' primary/most liquid
        # listing, then BSE (".BO") - which Yahoo indexes by numeric scrip
        # code rather than ticker text, so a BSE-only company (no NSE
        # listing at all, e.g. Prime Fresh Limited / scrip 540404) needs
        # its scrip code, not its name, for the ".BO" attempt. Generic for
        # any BSE-only-listed company, not just one symbol.
        resolved_bse_token = bse_code
        if not resolved_bse_token:
            try:
                inst = self._resolve_symbol(symbol_clean)
                if inst and inst.get('exch_seg') == 'BSE':
                    resolved_bse_token = inst.get('token')
            except Exception:
                pass

        yf_candidates = [f"{symbol_clean}.NS"]
        if resolved_bse_token:
            yf_candidates.append(f"{resolved_bse_token}.BO")
        else:
            yf_candidates.append(f"{symbol_clean}.BO")

        last_err = None
        for yf_symbol in yf_candidates:
            try:
                ticker = yf.Ticker(yf_symbol)
                ltp = open_ = high = low = close = volume = None
                try:
                    fi = ticker.fast_info
                    ltp = getattr(fi, 'last_price', None)
                    open_ = getattr(fi, 'open', None)
                    high = getattr(fi, 'day_high', None)
                    low = getattr(fi, 'day_low', None)
                    close = getattr(fi, 'previous_close', None)
                    volume = getattr(fi, 'last_volume', None)
                except Exception:
                    pass
                if ltp is None:
                    info = ticker.info or {}
                    ltp = info.get('currentPrice') or info.get('regularMarketPrice')
                    close = close or info.get('previousClose') or info.get('regularMarketPreviousClose')
                    volume = volume or info.get('volume')
                if ltp is not None:
                    return {
                        'symbol': symbol_clean, 'ltp': ltp, 'open': open_, 'high': high,
                        'low': low, 'close': close, 'volume': volume, 'source': 'yfinance'
                    }
            except Exception as e:
                last_err = e
                print(f"[AngelDataScraper] live quote fallback failed for {yf_symbol}: {e}")

        return {'symbol': symbol_clean, 'ltp': None, 'source': 'unavailable',
                'error': str(last_err) if last_err else 'no quote found on NSE or BSE'}

    def fetch_fundamental_payload(self, symbol: str) -> dict:
        """
        Fetches LTP, Volume, and OHLC data from Angel One SmartAPI,
        and aggregates ownership metrics/financial arrays.
        Formats payload into a uniform dictionary: lastPrice, volume, ohlc, ownership_metrics, financial_arrays.

        Process-wide cached per symbol for a short TTL - several
        independent compute_fn's in a single qualitative-analysis run
        (confirmed real: A.4's growth fallback alone calls this once for
        each of A.4/A.4.A/A.4.B/A.4.C/A.4.D - 5 times for one company)
        each ask for the SAME symbol's SAME live data within seconds of
        each other. Without this, every one of those repeats the full
        token-resolution attempt, then the yfinance 404 fallback network
        round-trip, for a company that's already known (from the very
        first call) to have no live coverage at all.
        """
        symbol_clean = symbol.strip().upper()
        if symbol_clean.endswith('.NS'):
            symbol_clean = symbol_clean[:-3]
        cached = _fundamental_payload_cache.get(symbol_clean)
        if cached is not None and (time.time() - cached[0]) < _FUNDAMENTAL_PAYLOAD_TTL:
            return cached[1]
        result = self._fetch_fundamental_payload_impl(symbol_clean)
        _fundamental_payload_cache[symbol_clean] = (time.time(), result)
        return result

    def _fetch_fundamental_payload_impl(self, symbol_clean: str) -> dict:
        if not self.authenticated or not self.smart_connect:
            print("[AngelDataScraper] Angel One client not authenticated. Using Screener API -> yfinance chain.")
            return self._fetch_with_fallback_chain(symbol_clean)
            
        try:
            # Resolve symbol to instrument token
            inst = self._resolve_symbol(symbol_clean)
            if not inst:
                print(f"[AngelDataScraper] Could not find trading token for NSE scrip: {symbol_clean}. Shifting to fallback.")
                return self._fetch_from_yfinance_fallback(symbol_clean)
                
            token = inst.get('token')
            trading_symbol = inst.get('symbol')
            print(f"[AngelDataScraper] Resolved {symbol_clean} -> TradingSymbol: {trading_symbol}, Token: {token}")
            
            # Fetch FULL market data (LTP, volume, OHLC info)
            print(f"[AngelDataScraper] Fetching Market Data for Token: {token}")
            market_data = self.smart_connect.getMarketData("FULL", {"NSE": [token]})
            
            if market_data.get('status') is True:
                fetched_items = market_data.get('data', {}).get('fetched', [])
                if fetched_items:
                    data = fetched_items[0]
                    last_price = data.get('ltp')
                    volume = data.get('volume')
                    ohlc = {
                        'open': data.get('open'),
                        'high': data.get('high'),
                        'low': data.get('low'),
                        'close': data.get('close')
                    }
                    
                    # Financials: Screener.in scrape is PRIMARY (matches the rest of
                    # the codebase's NSE/BSE-first sourcing) - yfinance is only the
                    # fallback when Screener has no parseable income statement for
                    # this ticker (e.g. an odd slug or a very new listing).
                    financial_arrays = {}
                    shareholding = {}
                    screener_data = None
                    try:
                        from tools.screener_scraper import fetch_screener_financials
                        screener_data = fetch_screener_financials(symbol_clean)
                        if screener_data and screener_data.get('financial_arrays'):
                            financial_arrays = screener_data['financial_arrays']
                            shareholding = screener_data.get('shareholding', {})
                    except Exception as scr_err:
                        print(f"[AngelDataScraper] Screener.in scrape failed ({scr_err}).")
                    if not financial_arrays.get('income_stmt'):
                        try:
                            ticker = yf.Ticker(f"{symbol_clean}.NS")
                            financial_arrays = {
                                'quarterly_income_stmt': self._serialize_df(ticker.quarterly_income_stmt),
                                'quarterly_balance_sheet': self._serialize_df(ticker.quarterly_balance_sheet),
                                'quarterly_cash_flow': self._serialize_df(ticker.quarterly_cashflow),
                                'income_stmt': self._serialize_df(ticker.income_stmt),
                                'balance_sheet': self._serialize_df(ticker.balance_sheet),
                                'cash_flow': self._serialize_df(ticker.cashflow)
                            }
                            print(f"[AngelDataScraper] Screener.in empty -> yfinance fallback financials for {symbol_clean}.")
                        except Exception as yf_fin_err:
                            print(f"[AngelDataScraper] Warning: yfinance fallback financials failed: {yf_fin_err}")

                    # Use ownership from Screener if available, else try yfinance
                    ownership = {
                        'F-10_heldPercentInsiders': None,
                        'F-11_promoterPledges': None,
                        'F-12_heldPercentInstitutions': None
                    }
                    info = {}
                    try:
                        if screener_data and screener_data.get('info'):
                            info = screener_data['info']
                            ownership = screener_data.get('ownership_metrics', ownership)
                        else:
                            from tools.yf_cache import cached_info
                            info = cached_info(f"{symbol_clean}.NS")
                            ownership['F-10_heldPercentInsiders'] = info.get('heldPercentInsiders')
                            ownership['F-11_promoterPledges'] = info.get('promoterPledges', None)
                            ownership['F-12_heldPercentInstitutions'] = info.get('heldPercentInstitutions')
                    except Exception as yf_err:
                        print(f"[AngelDataScraper] Warning: Failed to populate ownership details: {yf_err}")
                        
                    result = {
                        'lastPrice': last_price,
                        'volume': volume,
                        'ohlc': ohlc,
                        'ownership_metrics': ownership,
                        'info': info,
                        'financial_arrays': financial_arrays
                    }
                    if shareholding:
                        result['shareholding'] = shareholding
                    return result
            
            # Alternate fallback to ltpData if getMarketData is empty/fails
            print("[AngelDataScraper] getMarketData failed. Attempting ltpData fetch...")
            ltp_res = self.smart_connect.ltpData("NSE", trading_symbol, token)
            if ltp_res.get('status') is True:
                data = ltp_res.get('data', {})
                last_price = data.get('ltp')
                ohlc = {
                    'open': data.get('open'),
                    'high': data.get('high'),
                    'low': data.get('low'),
                    'close': data.get('close')
                }
                
                # Financials: Screener.in scrape PRIMARY, yfinance fallback if empty.
                financial_arrays = {}
                try:
                    from tools.screener_scraper import fetch_screener_financials
                    screener_data = fetch_screener_financials(symbol_clean)
                    if screener_data and screener_data.get('financial_arrays'):
                        financial_arrays = screener_data['financial_arrays']
                except Exception:
                    pass
                if not financial_arrays.get('income_stmt'):
                    try:
                        ticker = yf.Ticker(f"{symbol_clean}.NS")
                        financial_arrays = {
                            'quarterly_income_stmt': self._serialize_df(ticker.quarterly_income_stmt),
                            'quarterly_balance_sheet': self._serialize_df(ticker.quarterly_balance_sheet),
                            'quarterly_cash_flow': self._serialize_df(ticker.quarterly_cashflow),
                            'income_stmt': self._serialize_df(ticker.income_stmt),
                            'balance_sheet': self._serialize_df(ticker.balance_sheet),
                            'cash_flow': self._serialize_df(ticker.cashflow)
                        }
                        print(f"[AngelDataScraper] ltpData path: Screener.in empty -> yfinance fallback.")
                    except Exception as yf_fin_err:
                        print(f"[AngelDataScraper] Warning: yfinance fallback financials failed: {yf_fin_err}")

                # Retrieve volume and ownership metrics from yfinance
                volume = None
                ownership = {
                    'F-10_heldPercentInsiders': None,
                    'F-11_promoterPledges': None,
                    'F-12_heldPercentInstitutions': None
                }
                info = {}
                try:
                    from tools.yf_cache import cached_info
                    info = cached_info(f"{symbol_clean}.NS")
                    volume = info.get('volume')
                    ownership['F-10_heldPercentInsiders'] = info.get('heldPercentInsiders')
                    ownership['F-11_promoterPledges'] = info.get('promoterPledges', None)
                    ownership['F-12_heldPercentInstitutions'] = info.get('heldPercentInstitutions')
                except Exception as yf_err:
                    print(f"[AngelDataScraper] Warning: Failed to populate dynamic volume/ownership from yfinance: {yf_err}")
                    
                return {
                    'lastPrice': last_price,
                    'volume': volume,
                    'ohlc': ohlc,
                    'ownership_metrics': ownership,
                    'info': info,
                    'financial_arrays': financial_arrays
                }
                
            print("[AngelDataScraper] Angel One SmartAPI calls unsuccessful. Using Screener API -> yfinance chain.")
            return self._fetch_with_fallback_chain(symbol_clean)
            
        except Exception as e:
            if "App Deactive" in str(e) or "auth" in str(e).lower() or "active" in str(e).lower() or "session" in str(e).lower():
                print(f"[AngelDataScraper] Warning: SmartAPI connection throws App Deactive / authentication exception ({e}). Using Screener API -> yfinance chain.")
            else:
                print(f"[AngelDataScraper] Error fetching data for {symbol}: {e}. Using Screener API -> yfinance chain.")
            return self._fetch_with_fallback_chain(symbol_clean)

if __name__ == '__main__':
    # Local verification block
    import json
    print("Testing AngelDataScraper client...")
    scraper = AngelDataScraper()
    payload = scraper.fetch_fundamental_payload('INFY')
    print("\nResulting Ingestion Payload:")
    print(json.dumps(payload, indent=4))
