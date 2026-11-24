"""A fund that has not been listed long enough for its own forecast borrows the history of the index it tracks.

The index comes from the fund's name (a "Nifty 50" ETF tracks the Nifty 50). Only plain broad / sector indices whose long history is on the price
provider are mapped; a name that points to a variant (equal weight, momentum, quality, midcap ...) or to an index we cannot read stays unmapped, and
then the stock simply has no forecast (never a guess). The odds are the index's, applied to the fund's own price, and the page says so."""
from __future__ import annotations

import re

from . import outlook

# (pattern on the lower-cased fund name, display name, provider symbol). Every symbol was checked to return more than ten years of daily bars.
INDEXES: tuple[tuple[str, str, str], ...] = (
    (r"\bnifty\s*next\s*50\b|\bnifty\s*junior\b", "Nifty Next 50", "^NSMIDCP"),
    (r"\bnifty\s*50\b|\bnifty50\b", "Nifty 50", "^NSEI"),
    (r"\bnifty\s*100\b", "Nifty 100", "^CNX100"),
    (r"\bnifty\s*200\b", "Nifty 200", "^CNX200"),
    (r"\bnifty\s*500\b", "Nifty 500", "^CRSLDX"),
    (r"\bnifty\s*psu\s*bank\b", "Nifty PSU Bank", "^CNXPSUBANK"),
    (r"\bnifty\s*bank\b|\bbank\s*nifty\b", "Nifty Bank", "^NSEBANK"),
    (r"\bnifty\s*(financial\s*services|fin\s*service)\b", "Nifty Financial Services", "NIFTY_FIN_SERVICE.NS"),
    (r"\bnifty\s*it\b", "Nifty IT", "^CNXIT"),
    (r"\bnifty\s*pharma\b", "Nifty Pharma", "^CNXPHARMA"),
    (r"\bnifty\s*auto\b", "Nifty Auto", "^CNXAUTO"),
    (r"\bnifty\s*fmcg\b", "Nifty FMCG", "^CNXFMCG"),
    (r"\bnifty\s*metal\b", "Nifty Metal", "^CNXMETAL"),
    (r"\bnifty\s*energy\b", "Nifty Energy", "^CNXENERGY"),
    (r"\bnifty\s*infra(structure)?\b", "Nifty Infrastructure", "^CNXINFRA"),
    (r"\bnifty\s*realty\b", "Nifty Realty", "^CNXREALTY"),
    (r"\b(bse\s*)?sensex\b", "BSE Sensex", "^BSESN"),
    (r"\bbse\s*500\b", "BSE 500", "BSE-500.BO"),
    (r"\bbse\s*100\b", "BSE 100", "BSE-100.BO"),
)
# a fund built on a variant of the index follows a different series than the plain index, so it is not mapped
VARIANTS = re.compile(r"equal\s*weight|alpha|low\s*vol|momentum|quality|value|dividend|growth|midcap|smallcap|small\s*cap|mid\s*cap|multi\s*factor|"
                      r"leverag|inverse|short|2x|3x|esg|sharia|covered|target|\bcpse\b|\bpse\b|high\s*beta|enhanced|tax", re.I)
IS_FUND = re.compile(r"\betf\b|\bbees\b|index\s*fund|exchange\s*traded", re.I)

_NAMES: dict[str, str | None] = {}


def fund_name(symbol: str) -> str | None:
    """The fund's full name from the price provider (cached for the process). None when it cannot be read."""
    if symbol in _NAMES:
        return _NAMES[symbol]
    name = None
    try:
        import yfinance as yf
        name = yf.Ticker(f"{symbol}.NS").info.get("longName")
    except Exception:
        name = None
    if name:                                   # a failed read is not remembered, so a later request tries again
        _NAMES[symbol] = name
    return name


def underlying_index(name: str | None) -> tuple[str, str] | None:
    """(index name, provider symbol) for a fund name, or None when it is not a plain index fund or the index is not one we can read."""
    if not name or not IS_FUND.search(name) or VARIANTS.search(name):
        return None
    low = name.lower()
    for pat, label, sym in INDEXES:
        if re.search(pat, low):
            return label, sym
    return None


_INDEX_CACHE: dict[str, tuple[float, list[dict]]] = {}


def index_daily(symbol: str) -> list[dict]:
    """The index's whole daily history from the price provider (cached for an hour); [] when it cannot be read."""
    import time
    hit = _INDEX_CACHE.get(symbol)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=False)
        bars = [{"time": int(ts.timestamp()), "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]), "close": float(r["Close"])}
                for ts, r in hist.iterrows() if all(r.get(k) == r.get(k) and r.get(k) for k in ("Open", "High", "Low", "Close"))]
    except Exception:
        bars = []
    if bars:                                    # a failed read is not remembered
        _INDEX_CACHE[symbol] = (time.time(), bars)
    return bars


def with_index_forecast(out: dict, index_daily: list[dict], label: str, index_symbol: str, price: float | None) -> dict:
    """Replace the horizons of a forecast that had no usable history with the index's odds, priced from the fund's own last price,
    and record the basis so the page can say whose history it is. Trade plans stay as they were (they need the fund's own history)."""
    hs = []
    for old in out.get("outlook", []):
        h = 1 if old["id"] == "session" else old.get("sessions")
        new = {"id": old["id"], "label": "Next session" if old["id"] == "session" else old["label"], **({"sessions": h} if old["id"] != "session" else {}),
               **outlook.horizon_outlook(index_daily, h)}
        if price and new.get("p10") is not None:
            new["price_low"], new["price_mid"], new["price_high"] = (round(price * (1 + new[k] / 100), 2) for k in ("p10", "median", "p90"))
        hs.append(new)
    out["outlook"] = hs
    out["forecast_basis"] = {"kind": "index", "index": label, "symbol": index_symbol, "sessions": len(index_daily)}
    return out
