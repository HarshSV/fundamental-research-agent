"""Live headline index levels for the site ticker (NIFTY 50, NIFTY BANK, ...), via the price provider.

Each index is reported with its latest close/level and the % change against the previous session's
close. An index the provider has no (or only one) data point for is OMITTED - never filled with a
placeholder or zero. Results are cached briefly so many page views do not fan out to the provider."""
from __future__ import annotations

import threading
import time

try:
    import yfinance as yf
    _HAVE_YF = True
except Exception:  # pragma: no cover
    _HAVE_YF = False

# display name -> provider symbol (same set the reference market-data site shows, plus IT and Auto)
INDICES: list[tuple[str, str]] = [
    ("NIFTY 50", "^NSEI"),
    ("NIFTY BANK", "^NSEBANK"),
    ("NIFTY FIN SERVICE", "^CNXFIN"),
    ("NIFTY NEXT 50", "^NSMIDCP"),
    ("NIFTY 100", "^CNX100"),
    ("NIFTY 500", "^CRSLDX"),
    ("NIFTY IT", "^CNXIT"),
    ("NIFTY AUTO", "^CNXAUTO"),
]

TTL_SECONDS = 60
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": []}


def _one(name: str, sym: str) -> dict | None:
    # a month of daily bars so a sparse series (e.g. NIFTY FIN SERVICE) still has two points
    for attempt in range(2):
        try:
            h = yf.Ticker(sym).history(period="1mo", interval="1d")
            closes = [float(x) for x in h["Close"].dropna().tolist()] if h is not None and not h.empty else []
            if len(closes) >= 2 and closes[-2]:
                last, prev = closes[-1], closes[-2]
                return {"name": name, "symbol": sym, "value": last, "change": last - prev,
                        "change_pct": (last / prev - 1.0) * 100.0}
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.3)
    return None


def get_indices(force: bool = False) -> list[dict]:
    if not _HAVE_YF:
        return []
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < TTL_SECONDS:
            return _cache["data"]
    rows = [r for r in (_one(n, s) for n, s in INDICES) if r]
    with _lock:
        if rows:  # keep serving the last good list if a refresh comes back empty
            _cache["data"], _cache["at"] = rows, time.time()
        return _cache["data"]
