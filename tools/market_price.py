"""
The ONLY place the document-analysis Fundamental engine touches Angel One -
a thin wrapper around AngelDataScraper.fetch_live_quote for the handful of
market-price-dependent ratios (P/E, P/B, P/S, Dividend Yield, Earnings
Yield, EV/EBITDA, FCF Yield, Price/Cash Flow and the ratios derived from
them). Never used for Revenue/PAT/EBITDA/Debt/Cash/Assets/Equity/
Inventory/Receivables/Payables/Cash Flow/Capex/Tax - those always come
from the uploaded Annual Report/XBRL (see tools/manual_mode.py).
"""

import threading

_scraper = None
_lock = threading.Lock()


def _get_scraper():
    global _scraper
    if _scraper is None:
        with _lock:
            if _scraper is None:
                from tools.angel_scraper import AngelDataScraper
                _scraper = AngelDataScraper()
    return _scraper


def get_live_price(symbol, bse_code=None):
    """Returns {"ltp": float, "close": float|None, "source": str|None} or
    None if unavailable. Never raises, never fabricates - a caller that
    can't get a price marks the dependent ratio not_disclosed rather than
    using a stale/guessed value.

    `source` ("angel" = live NSE tick via Angel One, "yfinance" = fallback,
    often a delayed/previous-close quote) is passed through rather than
    discarded - every price-dependent ratio (P/E, P/B, P/S, Dividend Yield,
    EV/EBITDA, FCF Yield, Price/Cash Flow) needs to record WHICH kind of
    price it used for the ratio's own data-lineage trail (Sr No 24 etc.'s
    `inputs`), not just the number - a "why does this look off" question
    can't be answered from a bare float.

    `bse_code` (optional): the company's real BSE scrip code (from
    companies.bse_code, itself backfilled from the Annual Report's own
    text - see manual_document_pipeline.py). Passed straight through to
    fetch_live_quote as a direct-match fallback identifier, for when the
    internal registry `symbol` isn't the company's actual tradeable
    ticker (synthetic placeholder symbols, renamed companies, etc.)."""
    try:
        q = _get_scraper().fetch_live_quote(symbol, bse_code=bse_code)
    except Exception:
        return None
    ltp = q.get("ltp") if isinstance(q, dict) else None
    if not ltp:
        return None
    return {"ltp": float(ltp), "close": q.get("close"), "source": q.get("source")}
