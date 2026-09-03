"""
Manual-mode guard for the document-first "Upload Documents -> Analyse"
workflow (tools/document_analysis_engine.py).

That workflow must never silently fall back to a live NSE/BSE/yfinance/
shareholding-scraper call when an uploaded document doesn't contain a
value - only the uploaded Annual Report, Financial XBRL, Shareholding
Pattern filing, and Additional Filings are the source of truth (Angel
One's live price is the sole named exception, and only for market-price
data). The OLD automatic pipeline (tools/precompute_worker.py etc.) must
keep its existing live-fallback behaviour unchanged - it never enters
this context manager.

A contextvar (not a plain module global) so the guard is safe if the
manual and automatic pipelines ever run concurrently in the same process.
"""

import contextvars

_MANUAL_MODE = contextvars.ContextVar("manual_mode", default=False)


class manual_mode:
    def __enter__(self):
        self._token = _MANUAL_MODE.set(True)
        return self

    def __exit__(self, *exc):
        _MANUAL_MODE.reset(self._token)


def is_manual_mode():
    return _MANUAL_MODE.get()
