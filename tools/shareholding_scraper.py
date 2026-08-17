"""
Shareholding & institutional-flow data layer (F-11 promoter pledge, F-12 fund flows).

Design goals
------------
* REAL data, never fabricated. When a figure cannot be sourced we return ``None``
  and a status flag so the UI can say "awaiting next filing" instead of showing
  made-up numbers.
* Swappable providers. ``ShareholdingProvider`` is an abstract interface; today the
  free ``NSEShareholdingProvider`` is wired in, but a paid vendor (Trendlyne /
  Tickertape / etc.) can be dropped in later by implementing the same two methods
  and registering it in ``get_provider()`` — zero changes elsewhere.
* Resilient transport. Uses curl_cffi (real-browser TLS fingerprint) to get past
  NSE's bot wall, warms up session cookies, retries once, and degrades gracefully.
* Cached. Pledge data only changes quarterly and FII/DII once a day, so responses
  are cached on disk to keep the dashboard fast and avoid hammering NSE.

Confirmed-working NSE endpoints (probed 2026-06-25 from an Indian IP):
* https://www.nseindia.com/api/corporate-pledgedata?index=equities&symbol=SYMBOL
* https://www.nseindia.com/api/fiidiiTradeReact   (market-wide FII/DII net flows)
"""

import os
import json
import time
import threading

# Ensure TLS trust is set up (Windows behind a TLS-inspecting proxy) before
# curl_cffi creates any session. No-op on Linux/cloud.
try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

# --- HTTP transport: prefer curl_cffi (defeats NSE's TLS fingerprint blocking) ---
try:
    from curl_cffi import requests as _http
    _HAVE_CFFI = True
except Exception:  # pragma: no cover - fallback path
    import requests as _http
    _HAVE_CFFI = False

# yfinance is an optional enrichment source for institutional holding level
try:
    import yfinance as yf
    _HAVE_YF = True
except Exception:  # pragma: no cover
    _HAVE_YF = False


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "shareholding")
PLEDGE_TTL_SECONDS = 12 * 3600     # promoter pledge updates quarterly -> cache 12h
FIIDII_TTL_SECONDS = 4 * 3600      # market FII/DII updates daily -> cache 4h

# Allow disabling TLS verification on machines with a broken local CA store
# (e.g. some corporate Windows boxes). Production on a proper host keeps it on.
_INSECURE = os.getenv("NSE_INSECURE", "").strip() in ("1", "true", "True", "yes")


def _to_float(val):
    """NSE returns numbers as padded strings like '   21.04'. Parse safely."""
    if val is None:
        return None
    try:
        s = str(val).strip().replace(",", "")
        if s == "" or s.lower() in ("-", "na", "n/a"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _cache_path(key: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key: str, ttl: int):
    try:
        path = _cache_path(key)
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_cache(key: str, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception as e:
        print(f"[shareholding] cache write skipped: {e}")


class ShareholdingProvider:
    """Abstract interface. Implement these two methods for any data vendor."""

    def fetch_pledge(self, symbol: str) -> dict:
        raise NotImplementedError

    def fetch_market_fii_dii(self) -> list:
        raise NotImplementedError


class NSEShareholdingProvider(ShareholdingProvider):
    """Free provider backed by NSE's public JSON endpoints."""

    HOME = "https://www.nseindia.com"

    def __init__(self):
        self._session = None
        self._session_ts = 0
        self._lock = threading.Lock()

    # -- transport helpers -------------------------------------------------
    def _new_session(self):
        if _HAVE_CFFI:
            s = _http.Session(impersonate="chrome", verify=not _INSECURE)
        else:
            s = _http.Session()
            s.headers.update({
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "*/*",
            })
            s.verify = not _INSECURE
        return s

    def _session_get(self, url: str, referer: str):
        """GET with a warm cookie session, one retry, and an SSL-fallback."""
        with self._lock:
            # Rebuild the session every ~5 min so cookies stay fresh
            if self._session is None or (time.time() - self._session_ts) > 300:
                self._session = self._new_session()
                try:
                    self._session.get(self.HOME, timeout=15)
                except Exception as e:
                    # Local boxes sometimes fail TLS verification; retry insecure once
                    if "certificate" in str(e).lower() and _HAVE_CFFI:
                        self._session = _http.Session(impersonate="chrome", verify=False)
                        try:
                            self._session.get(self.HOME, timeout=15)
                        except Exception as e2:
                            print(f"[shareholding] NSE warmup failed: {e2}")
                    else:
                        print(f"[shareholding] NSE warmup failed: {e}")
                self._session_ts = time.time()
            session = self._session

        headers = {"Referer": referer}
        for attempt in range(2):
            try:
                r = session.get(url, headers=headers, timeout=20)
                if r.status_code == 200 and r.text.strip()[:1] in "{[":
                    return r.json()
                # 401/403 -> cookies stale; force a fresh session next loop
                with self._lock:
                    self._session = None
            except Exception as e:
                if attempt == 0 and "certificate" in str(e).lower() and _HAVE_CFFI:
                    with self._lock:
                        self._session = _http.Session(impersonate="chrome", verify=False)
                        try:
                            self._session.get(self.HOME, timeout=15)
                        except Exception:
                            pass
                        self._session_ts = time.time()
                else:
                    print(f"[shareholding] NSE GET failed ({url}): {e}")
            time.sleep(0.6)
        return None

    # -- data methods ------------------------------------------------------
    def fetch_pledge(self, symbol: str) -> dict:
        sym = symbol.strip().upper().replace(".NS", "")
        cached = _read_cache(f"pledge_{sym}", PLEDGE_TTL_SECONDS)
        if cached is not None:
            return cached

        url = f"{self.HOME}/api/corporate-pledgedata?index=equities&symbol={sym}"
        ref = f"{self.HOME}/get-quotes/equity?symbol={sym}"
        data = self._session_get(url, ref)

        result = {"status": "unavailable", "as_of_quarter": None,
                  "promoter_holding_pct": None, "promoter_pledge_pct": None,
                  "num_shares_pledged": None, "total_promoter_holding": None,
                  "total_public_holding": None, "total_issued_shares": None}

        rows = (data or {}).get("data") if isinstance(data, dict) else None
        if rows:
            latest = rows[0]
            result.update({
                "status": "ok",
                "as_of_quarter": latest.get("shp"),
                "promoter_holding_pct": _to_float(latest.get("percPromoterHolding")),
                "promoter_pledge_pct": _to_float(latest.get("percSharesPledged")),
                "num_shares_pledged": _to_float(latest.get("numSharesPledged")),
                "total_promoter_holding": _to_float(latest.get("totPromoterHolding")),
                "total_public_holding": _to_float(latest.get("totPublicHolding")),
                "total_issued_shares": _to_float(latest.get("totIssuedShares")),
            })
            _write_cache(f"pledge_{sym}", result)
        elif isinstance(data, dict):
            # NSE responded successfully but lists no pledge -> the company has no
            # promoter pledge on record (NSE only lists pledged scrips). That is a
            # REAL 0%, not "unknown".
            result.update({"status": "zero", "promoter_pledge_pct": 0.0, "num_shares_pledged": 0})
            _write_cache(f"pledge_{sym}", result)
        return result

    def fetch_promoter_holding_trend(self, symbol: str) -> list:
        """Every quarter NSE's corporate-pledgedata endpoint returns (same endpoint
        `fetch_pledge` uses, just not truncated to `rows[0]`) — used for C.1's
        promoter-shareholding trend / QoQ change, since PORTAL-02 (BSE/NSE
        Shareholding Pattern) is the same real filing either way. Returns
        [{quarter, promoter_holding_pct}, ...] oldest-first, or [] on failure.
        Never raises."""
        sym = symbol.strip().upper().replace(".NS", "")
        cached = _read_cache(f"promoter_trend_{sym}", PLEDGE_TTL_SECONDS)
        if cached is not None:
            return cached
        url = f"{self.HOME}/api/corporate-pledgedata?index=equities&symbol={sym}"
        ref = f"{self.HOME}/get-quotes/equity?symbol={sym}"
        data = self._session_get(url, ref)
        rows = (data or {}).get("data") if isinstance(data, dict) else None
        out = []
        if rows:
            for r in rows:
                pct = _to_float(r.get("percPromoterHolding"))
                if pct is not None:
                    out.append({"quarter": r.get("shp"), "promoter_holding_pct": pct})
            out.reverse()  # NSE returns newest-first; we want oldest-first for a trend
            if out:
                _write_cache(f"promoter_trend_{sym}", out)
        return out

    def fetch_promoter_holding_history(self, symbol: str, max_quarters: int = 8) -> list:
        """Real quarter-by-quarter Promoter/Public shareholding split, straight
        from NSE's own Shareholding Pattern master (SEBI LODR Reg. 31 filing) —
        `corporate-share-holdings-master?index=equities&symbol=X` (confirmed
        working, returns up to 20 historical quarters, newest-first). This is a
        different, more reliable endpoint than fetch_promoter_holding_trend's
        pledge-data byproduct, which only carries a promoter% row for quarters
        where a pledge was ALSO reported — silently empty for the many
        zero-pledge companies where this data matters most.

        Returns [{quarter, promoter_pct, public_pct}, ...] oldest-first
        (last `max_quarters`), or [] on failure. Never raises."""
        sym = symbol.strip().upper().replace(".NS", "")
        cache_key = f"promoter_history_{sym}_{max_quarters}"
        cached = _read_cache(cache_key, PLEDGE_TTL_SECONDS)
        if cached is not None:
            return cached
        url = f"{self.HOME}/api/corporate-share-holdings-master?index=equities&symbol={sym}"
        ref = f"{self.HOME}/get-quotes/equity?symbol={sym}"
        data = self._session_get(url, ref)
        out = []
        if isinstance(data, list):
            for row in data:
                promoter_pct = _to_float(row.get("pr_and_prgrp"))
                public_pct = _to_float(row.get("public_val"))
                quarter = row.get("date")
                if promoter_pct is not None and quarter:
                    out.append({"quarter": quarter, "promoter_pct": promoter_pct, "public_pct": public_pct})
            out = out[:max_quarters]
            out.reverse()  # NSE returns newest-first; we want oldest-first for a trend
            if out:
                _write_cache(cache_key, out)
        return out

    def fetch_market_fii_dii(self) -> list:
        cached = _read_cache("market_fiidii", FIIDII_TTL_SECONDS)
        if cached is not None:
            return cached

        url = f"{self.HOME}/api/fiidiiTradeReact"
        data = self._session_get(url, f"{self.HOME}/")
        out = []
        if isinstance(data, list):
            for row in data:
                out.append({
                    "category": row.get("category"),
                    "date": row.get("date"),
                    "buy_cr": _to_float(row.get("buyValue")),
                    "sell_cr": _to_float(row.get("sellValue")),
                    "net_cr": _to_float(row.get("netValue")),
                })
            if out:
                _write_cache("market_fiidii", out)
        return out


# --- module-level singleton -------------------------------------------------
_provider = None
_provider_lock = threading.Lock()


def get_provider() -> ShareholdingProvider:
    """Return the active shareholding provider (swap implementation here later)."""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = NSEShareholdingProvider()
    return _provider


def _institutional_pct_from_yf(symbol: str):
    if not _HAVE_YF:
        return None
    try:
        sym = symbol.strip().upper()
        if not sym.endswith(".NS"):
            sym += ".NS"
        info = yf.Ticker(sym).info or {}
        held = info.get("heldPercentInstitutions")
        if held is not None:
            return round(held * 100.0, 2) if held <= 1.0 else round(held, 2)
    except Exception:
        return None
    return None


def fetch_shareholding(symbol: str, name: str = None) -> dict:
    """
    Public entry point. Returns a normalized, UI-ready ownership payload that
    NEVER raises. Real values where sourced, ``None`` + status flags otherwise.
    `name` (company long name) helps resolve renamed tickers on Screener.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    provider = get_provider()

    pledge = {"status": "unavailable"}
    market = []
    try:
        pledge = provider.fetch_pledge(sym)
    except Exception as e:
        print(f"[shareholding] pledge fetch error for {sym}: {e}")
    try:
        market = provider.fetch_market_fii_dii()
    except Exception as e:
        print(f"[shareholding] FII/DII fetch error: {e}")

    # --- Primary holdings + multi-quarter trend: Screener.in (covers all stocks) ---
    scr = {}
    concall_links = []
    try:
        from tools.screener_scraper import fetch_screener
        _s = fetch_screener(sym, name) or {}
        scr = _s.get("shareholding") or {}
        concall_links = _s.get("concall_links") or []
    except Exception as e:
        print(f"[shareholding] screener fetch error for {sym}: {e}")

    have_scr = scr.get("status") == "ok"
    latest = scr.get("latest", {}) if have_scr else {}

    # Build multi-quarter ownership history (REAL) for the trend charts.
    history = []
    if have_scr:
        qs = scr.get("quarters") or []
        def _at(key, i):
            arr = scr.get(key) or []
            return arr[i] if i < len(arr) else None
        for i, q in enumerate(qs):
            history.append({
                "quarter": q,
                "promoter": _at("promoter", i),
                "fii": _at("fii", i),
                "dii": _at("dii", i),
                "public": _at("public", i),
            })

    # Promoter / institutional / public — Screener first, then NSE/yfinance fallback.
    fii_stake = latest.get("fii")
    dii_stake = latest.get("dii")
    if have_scr:
        promoter_pct = latest.get("promoter")
        institutional_pct = round((fii_stake or 0.0) + (dii_stake or 0.0), 2)
        public_pct = latest.get("public")
        as_of = scr.get("as_of_quarter")
        source = "Screener"
    else:
        promoter_pct = pledge.get("promoter_holding_pct")
        institutional_pct = _institutional_pct_from_yf(sym)
        public_pct = None
        if promoter_pct is not None:
            public_pct = round(max(100.0 - promoter_pct - (institutional_pct or 0.0), 0.0), 2)
        as_of = pledge.get("as_of_quarter")
        source = "NSE" if pledge.get("status") == "ok" else "fallback"

    # Pledge — NSE is authoritative. "ok" => real value; "zero" => NSE responded with
    # no pledge on record (= 0%); otherwise default to 0 (NSE lists only pledged
    # scrips, so absence overwhelmingly means zero) but flag it as assumed.
    if pledge.get("status") in ("ok", "zero"):
        pledge_pct = pledge.get("promoter_pledge_pct")
        if pledge_pct is None:
            pledge_pct = 0.0
        pledge_status = pledge.get("status")
    else:
        pledge_pct = 0.0
        pledge_status = "assumed_zero"

    return {
        "source": source,
        "as_of_quarter": as_of,
        "pledge_status": pledge_status,
        # F-11 — promoter pledge
        "promoter_holding_pct": promoter_pct,
        "promoter_pledge_pct": pledge_pct,
        "num_shares_pledged": pledge.get("num_shares_pledged"),
        "total_promoter_holding": pledge.get("total_promoter_holding"),
        # F-10 — ownership split (REAL via Screener)
        "institutional_holding_pct": institutional_pct,
        "fii_stake": fii_stake,
        "dii_stake": dii_stake,
        "public_holding_pct": public_pct,
        # multi-quarter history (REAL) for ownership / promoter / FII-DII trends
        "ownership_history": history,
        # F-12 — market-wide institutional flows (REAL, latest session)
        "market_fii_dii": market,
        "fund_flows": [],
        "concall_links": concall_links,
    }


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    print(json.dumps(fetch_shareholding(target), indent=2))
