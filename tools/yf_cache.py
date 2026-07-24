"""
Process-level TTL cache for yfinance `.info` / `.history` lookups.

The same symbol's `.info` and price history were being re-fetched from the
network independently across angel_scraper.py, stock_agent.py and nse_xbrl.py
within a single /generate-report request (and again on the next request for
the same symbol soon after) — each a multi-second round trip. Caching these
per (symbol) / (symbol, period, interval) for a short TTL removes that
duplicate network cost without threading a cache object through every call site.
"""

import time
import yfinance as yf

_INFO_TTL = 15 * 60
_HIST_TTL = 15 * 60

_info_cache = {}
_hist_cache = {}


def cached_info(symbol: str) -> dict:
    """Ticker.info for `symbol` (e.g. 'TCS.NS'), cached for a few minutes."""
    now = time.time()
    hit = _info_cache.get(symbol)
    if hit and (now - hit[0]) < _INFO_TTL:
        return hit[1]
    info = yf.Ticker(symbol).info or {}
    _info_cache[symbol] = (now, info)
    return info


def cached_history(symbol: str, period: str = "1y", interval: str = "1d"):
    """Ticker.history(...) for `symbol`, cached per (symbol, period, interval)."""
    key = (symbol, period, interval)
    now = time.time()
    hit = _hist_cache.get(key)
    if hit is not None and (now - hit[0]) < _HIST_TTL:
        return hit[1]
    hist = yf.Ticker(symbol).history(period=period, interval=interval)
    _hist_cache[key] = (now, hist)
    return hist
