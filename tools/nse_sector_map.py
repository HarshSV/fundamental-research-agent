"""
Python-side reader for frontend/src/lib/nseSectorMap.js - the same NSE
sector classification (26-sector taxonomy from sectorMatrix.js) the
frontend uses for ratio-tier filtering. Parsed directly from that file
(single source of truth, no separately-maintained copy) rather than
duplicated here by hand.
"""

import os
import re
import json
import threading

_JS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "src", "lib", "nseSectorMap.js",
)

_lock = threading.Lock()
_cache = None


def _load():
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            with open(_JS_PATH, "r", encoding="utf-8") as fh:
                src = fh.read()
            m = re.search(r"NSE_SECTOR_BY_SYMBOL\s*=\s*(\{.*?\});", src, re.S)
            _cache = json.loads(m.group(1)) if m else {}
        except Exception as e:
            print(f"[nse_sector_map] failed to parse {_JS_PATH}: {e}")
            _cache = {}
        return _cache


def get_nse_sector(symbol):
    """Verbatim NSE sector for a symbol (one of sectorMatrix.js's 26 sectors),
    or None if the symbol isn't in the Nifty Total Market coverage this map
    is built from - mirrors frontend/src/lib/nseSectorMap.js's getNseSector()."""
    if not symbol:
        return None
    return _load().get(symbol.strip().upper())


def all_symbols_by_sector():
    """{sector_name: [symbol, ...]} across the whole mapped universe."""
    out = {}
    for sym, sector in _load().items():
        out.setdefault(sector, []).append(sym)
    return out
