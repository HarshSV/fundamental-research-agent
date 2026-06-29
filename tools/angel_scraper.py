import os
import requests
import pyotp
from SmartApi import SmartConnect
import yfinance as yf
from dotenv import load_dotenv

# Load env variables from root .env if it exists
load_dotenv()


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
    valuation band chart. Never raises — returns None if it can't be built.
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
        Downloads and caches the official Angel One Instrument List (Scrip Master).
        """
        if self.scrip_master is not None:
            return
            
        try:
            print("[AngelDataScraper] Downloading Angel One Scrip Master json...")
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                self.scrip_master = response.json()
                print(f"[AngelDataScraper] Loaded {len(self.scrip_master)} instrument tokens from Scrip Master.")
            else:
                print(f"[AngelDataScraper] Failed to download Scrip Master. Status Code: {response.status_code}")
        except Exception as e:
            print(f"[AngelDataScraper] Failed to fetch Instrument List: {e}")

    def _resolve_symbol(self, symbol: str) -> dict:
        """
        Finds matching token and trading symbol details for NSE segment.
        """
        self._load_scrip_master()
        if not self.scrip_master:
            return None
            
        clean_symbol = symbol.strip().upper()
        if clean_symbol.endswith('.NS'):
            clean_symbol = clean_symbol[:-3]
            
        # Match name or trading symbol (typically NAME=INFY, SYMBOL=INFY-EQ)
        for instrument in self.scrip_master:
            if instrument.get('exch_seg') == 'NSE':
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

    def _fetch_from_screener_api(self, symbol: str) -> dict:
        """
        Primary fallback: Apify Screener.in API for accurate Indian stock data.
        Returns the full payload or None if unavailable.
        """
        try:
            from tools.screener_api import fetch_screener_fundamentals
            result = fetch_screener_fundamentals(symbol)
            if result and result.get('lastPrice') is not None:
                print(f"[AngelDataScraper] ✅ Screener API returned real data for {symbol}.")
                return result
            elif result and result.get('financial_arrays'):
                # Got financials but no live price — still usable
                print(f"[AngelDataScraper] Screener API returned financials (no live price) for {symbol}.")
                return result
        except Exception as e:
            print(f"[AngelDataScraper] Screener API unavailable for {symbol}: {e}")
        return None

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
                
            ticker = yf.Ticker(symbol_ns)
            info = ticker.info
            
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
        Cascading data fetch: yfinance (fast) → Apify Screener (only if yfinance empty).
        Returns the first result that actually has financial statements.
        """
        # 1. yfinance first — fast and complete for the large majority of stocks.
        result = self._fetch_from_yfinance_fallback(symbol)
        if result and (result.get('financial_arrays') or {}).get('income_stmt'):
            return result

        # 2. Only if yfinance came back empty (renamed/missing ticker), try Apify Screener.
        screener_result = self._fetch_from_screener_api(symbol)
        if screener_result is not None and (screener_result.get('financial_arrays') or {}).get('income_stmt'):
            return screener_result

        return result

    def fetch_live_quote(self, symbol: str) -> dict:
        """
        Lightweight real-time quote (LTP + OHLC + volume) for live tracking/polling.
        Deliberately does NOT pull financial statements, so it is cheap to call on a
        short interval. Uses Angel One live market data when authenticated, else a
        fast yfinance fallback. Never raises.
        """
        symbol_clean = symbol.strip().upper()
        if symbol_clean.endswith('.NS'):
            symbol_clean = symbol_clean[:-3]

        # Preferred path: Angel One live tick
        if self.authenticated and self.smart_connect:
            try:
                inst = self._resolve_symbol(symbol_clean)
                if inst:
                    token = inst.get('token')
                    md = self.smart_connect.getMarketData("FULL", {"NSE": [token]})
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

        # Fallback: yfinance fast quote
        try:
            ticker = yf.Ticker(f"{symbol_clean}.NS")
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
            return {
                'symbol': symbol_clean, 'ltp': ltp, 'open': open_, 'high': high,
                'low': low, 'close': close, 'volume': volume, 'source': 'yfinance'
            }
        except Exception as e:
            print(f"[AngelDataScraper] live quote fallback failed for {symbol_clean}: {e}")
            return {'symbol': symbol_clean, 'ltp': None, 'source': 'unavailable', 'error': str(e)}

    def fetch_fundamental_payload(self, symbol: str) -> dict:
        """
        Fetches LTP, Volume, and OHLC data from Angel One SmartAPI,
        and aggregates ownership metrics/financial arrays.
        Formats payload into a uniform dictionary: lastPrice, volume, ohlc, ownership_metrics, financial_arrays.
        """
        symbol_clean = symbol.strip().upper()
        if symbol_clean.endswith('.NS'):
            symbol_clean = symbol_clean[:-3]
            
        if not self.authenticated or not self.smart_connect:
            print("[AngelDataScraper] Angel One client not authenticated. Using Screener API → yfinance chain.")
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
                    
                    # Financials: yfinance PRIMARY (fast, complete). Apify Screener is a
                    # last-resort fallback only when yfinance returns nothing (e.g. a
                    # renamed/demerged ticker like TATAMOTORS that 404s on yfinance).
                    financial_arrays = {}
                    shareholding = {}
                    screener_data = None
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
                    except Exception as yf_fin_err:
                        print(f"[AngelDataScraper] Warning: yfinance financials failed: {yf_fin_err}")
                    if not financial_arrays.get('income_stmt'):
                        try:
                            from tools.screener_api import fetch_screener_fundamentals
                            screener_data = fetch_screener_fundamentals(symbol_clean)
                            if screener_data and screener_data.get('financial_arrays'):
                                financial_arrays = screener_data['financial_arrays']
                                shareholding = screener_data.get('shareholding', {})
                                print(f"[AngelDataScraper] yfinance empty -> Screener API financials for {symbol_clean}.")
                        except Exception as scr_err:
                            print(f"[AngelDataScraper] Screener API fallback failed ({scr_err}).")

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
                            ticker = yf.Ticker(f"{symbol_clean}.NS")
                            info = ticker.info
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
                
                # Financials: yfinance PRIMARY, Apify Screener fallback only if empty.
                financial_arrays = {}
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
                except Exception as yf_fin_err:
                    print(f"[AngelDataScraper] Warning: yfinance financials failed: {yf_fin_err}")
                if not financial_arrays.get('income_stmt'):
                    try:
                        from tools.screener_api import fetch_screener_fundamentals
                        screener_data = fetch_screener_fundamentals(symbol_clean)
                        if screener_data and screener_data.get('financial_arrays'):
                            financial_arrays = screener_data['financial_arrays']
                            print(f"[AngelDataScraper] ltpData path: yfinance empty -> Screener API.")
                    except Exception:
                        pass

                # Retrieve volume and ownership metrics from yfinance
                volume = None
                ownership = {
                    'F-10_heldPercentInsiders': None,
                    'F-11_promoterPledges': None,
                    'F-12_heldPercentInstitutions': None
                }
                info = {}
                try:
                    ticker = yf.Ticker(f"{symbol_clean}.NS")
                    info = ticker.info
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
                
            print("[AngelDataScraper] Angel One SmartAPI calls unsuccessful. Using Screener API → yfinance chain.")
            return self._fetch_with_fallback_chain(symbol_clean)
            
        except Exception as e:
            if "App Deactive" in str(e) or "auth" in str(e).lower() or "active" in str(e).lower() or "session" in str(e).lower():
                print(f"[AngelDataScraper] Warning: SmartAPI connection throws App Deactive / authentication exception ({e}). Using Screener API → yfinance chain.")
            else:
                print(f"[AngelDataScraper] Error fetching data for {symbol}: {e}. Using Screener API → yfinance chain.")
            return self._fetch_with_fallback_chain(symbol_clean)

if __name__ == '__main__':
    # Local verification block
    import json
    print("Testing AngelDataScraper client...")
    scraper = AngelDataScraper()
    payload = scraper.fetch_fundamental_payload('INFY')
    print("\nResulting Ingestion Payload:")
    print(json.dumps(payload, indent=4))
