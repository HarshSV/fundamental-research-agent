"""
Two-stage Annual Report document cache - shared by every AR-evidence-based
qualitative sub-point (E.1.1, E.1.3, and future A-F/G-U tasks) so the same
company's Annual Report is downloaded and fitz-parsed ONCE, not once per
task. Phase 1D performance fix.

Stage 1 (PDF bytes): reuses tools.ar_table_extractor.download_ar_pdf_bytes
(cache/ar_pdfs/{SYMBOL}_{YEAR}.pdf, 30-day TTL) instead of maintaining a
second download implementation. The URL is resolved via the fast path
first - companies.latest_ar_url/latest_ar_year, already persisted by
tools/seed_company_registry.py - falling back to the existing live
BSE-then-NSE lookup (list_annual_report_years/_find_annual_report_pdf)
only when that fast path is missing or doesn't cover the requested year.

Stage 2 (extracted text): NEW disk cache of per-page, ligature-normalized
text (cache/ar_text/{SYMBOL}_{YEAR}.json), so fitz only opens/parses the
PDF once per (symbol, fiscal_year) regardless of how many different
qualitative tasks need evidence from it afterward.

Callers get back a list of already-normalized page strings - identical to
what tools.annual_report_financials._fetch_ar_evidence_excerpts previously
produced inline via `_page_text(page)` + whitespace/control-char cleanup - 
so downstream anchor-scoring logic is unaffected; only where the text comes
from changes.

Concurrency: a per-(symbol, fiscal_year) in-process lock serializes the
"check cache, else download+extract+write" critical section, so N threads
in the same batch-worker process asking for the same company/year at the
same time do one download+parse, not N (the batch worker runs threads
within a single process, not separate processes, so an in-memory lock is
sufficient - see module docstring in tools/qualitative_batch_worker.py).
"""

import json
import os
import re
import threading
import time

_TEXT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "ar_text")
_TEXT_CACHE_TTL = 30 * 24 * 3600  # matches ar_table_extractor's PDF-bytes TTL - same document, same staleness rule

_locks_guard = threading.Lock()
_locks = {}  # (symbol, fiscal_year) -> threading.Lock()


def _lock_for(symbol, fiscal_year):
    key = (symbol, fiscal_year)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _text_cache_path(symbol, fiscal_year):
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    return os.path.join(_TEXT_CACHE_DIR, f"{sym}_{fiscal_year}.json")


def _read_text_cache(symbol, fiscal_year):
    p = _text_cache_path(symbol, fiscal_year)
    try:
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= _TEXT_CACHE_TTL:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _write_text_cache(symbol, fiscal_year, pages, pdf_url):
    try:
        os.makedirs(_TEXT_CACHE_DIR, exist_ok=True)
        p = _text_cache_path(symbol, fiscal_year)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"pages": pages, "pdf_url": pdf_url, "fiscal_year": fiscal_year}, fh)
    except Exception:
        pass


def manual_cached_years(symbol):
    """Every fiscal year already sitting in the on-disk text cache for this
    symbol (newest first) - whether it got there via a manual upload
    (tools/manual_document_pipeline.py:_write_shared_ar_caches) or a prior
    live fetch. Used by tools/manual_mode.py-guarded callers to answer
    "what years do we actually have" WITHOUT hitting BSE/NSE live."""
    sym = re.sub(r"[^A-Z0-9]", "", (symbol or "").upper())
    if not os.path.isdir(_TEXT_CACHE_DIR):
        return []
    years = []
    prefix = f"{sym}_"
    for fname in os.listdir(_TEXT_CACHE_DIR):
        if fname.startswith(prefix) and fname.endswith(".json"):
            try:
                years.append(int(fname[len(prefix):-len(".json")]))
            except ValueError:
                continue
    return sorted(set(years), reverse=True)


def resolve_latest_ar_year_and_url(symbol, name):
    """Fast path: companies.latest_ar_year/latest_ar_url (already persisted
    by tools/seed_company_registry.py). Falls back to the existing live
    BSE-then-NSE lookup (list_annual_report_years + _find_annual_report_pdf)
    only when the fast path is missing or invalid - never fabricated.
    Returns (year, url) with either possibly None on total failure."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    try:
        from tools.supabase_client import get_client
        sb = get_client()
        r = (sb.table("companies").select("latest_ar_year,latest_ar_url")
             .eq("symbol", sym).limit(1).execute())
        if r.data:
            year = r.data[0].get("latest_ar_year")
            url = r.data[0].get("latest_ar_url")
            if year and url:
                return year, url
    except Exception as e:
        print(f"[ar_document_cache] companies fast-path lookup failed for {sym}: {e}")

    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        # Manual document-analysis workflow: never reach live BSE/NSE - the
        # companies fast-path row is expected to already point at the
        # uploaded document (tools/manual_document_pipeline.py:
        # _point_company_at_manual_ar). If it's genuinely missing, the
        # honest answer is "no uploaded Annual Report", not a live fetch.
        years = manual_cached_years(sym)
        return (years[0], f"manual-upload://{sym}_{years[0]}") if years else (None, None)

    # Fast path missing/invalid - fall back to the existing live resolution,
    # exactly as _fetch_ar_evidence_excerpts did before this change.
    from tools.annual_report_financials import list_annual_report_years, _find_annual_report_pdf
    years = list_annual_report_years(sym, name)
    if not years:
        return None, None
    year = years[0]
    url = _find_annual_report_pdf(sym, name, year)
    return year, url


def get_ar_pages(symbol, name, fiscal_year=None):
    """Returns {'pages': [str, ...], 'fiscal_year': int, 'pdf_url': str,
    'pdf_from_cache': bool, 'text_from_cache': bool} or {'error': reason}.
    Never raises.

    `pages[i]` is page i's ligature-normalized, whitespace-collapsed,
    control-character-stripped text - identical transformation to what
    _fetch_ar_evidence_excerpts applied inline before this change, so
    existing anchor-scan/scoring code sees the same text either way."""
    sym = (symbol or "").strip().upper().replace(".NS", "")

    def _cached_result(resolved_year):
        cached_text = _read_text_cache(sym, resolved_year)
        if cached_text is None:
            return None
        return {
            "pages": cached_text["pages"], "fiscal_year": resolved_year,
            "pdf_url": cached_text.get("pdf_url"),
            "pdf_from_cache": True, "text_from_cache": True,
        }

    resolved_year = fiscal_year
    resolved_url = None
    if resolved_year is not None:
        hit = _cached_result(resolved_year)
        if hit is not None:
            return hit
    else:
        # No specific year requested - fast path first (companies table),
        # live BSE/NSE lookup only as resolve_latest_ar_year_and_url's own
        # fallback.
        resolved_year, resolved_url = resolve_latest_ar_year_and_url(sym, name)
        if not resolved_year:
            return {"error": "Annual Report year/URL could not be resolved."}
        hit = _cached_result(resolved_year)
        if hit is not None:
            return hit

    with _lock_for(sym, resolved_year):
        # Re-check the text cache after acquiring the lock - another thread
        # may have just finished the exact same (symbol, year) while we
        # were waiting, in which case we should reuse its result rather
        # than re-downloading/re-parsing.
        hit = _cached_result(resolved_year)
        if hit is not None:
            return hit

        if resolved_url is None:
            from tools.manual_mode import is_manual_mode
            if is_manual_mode():
                # Manual document-analysis workflow: a cache miss here means
                # this fiscal year genuinely wasn't uploaded - never reach
                # live BSE/NSE to fill the gap.
                return {"error": f"No uploaded Annual Report for fiscal year {resolved_year}."}
            # Either a specific fiscal_year was requested (bypassing the
            # "latest" fast path entirely, matching the old per-year
            # behavior) or the fast path returned a year without a URL - 
            # use the existing live per-year lookup, never fabricated.
            from tools.annual_report_financials import _find_annual_report_pdf
            resolved_url = _find_annual_report_pdf(sym, name, resolved_year)

        if not resolved_url:
            return {"error": "Annual Report PDF URL not found."}

        from tools.ar_table_extractor import download_ar_pdf_bytes
        p = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cache", "ar_pdfs", f"{sym}_{resolved_year}.pdf",
        )
        pdf_from_cache = os.path.exists(p)
        content = download_ar_pdf_bytes(sym, name, resolved_year, pdf_url=resolved_url)
        if not content:
            return {"error": "Could not download the Annual Report right now.", "source_url": resolved_url}

        try:
            import fitz
        except Exception as e:
            return {"error": f"pymupdf unavailable: {e}"}
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            return {"error": f"PDF read failed: {e}"}

        from tools.annual_report_financials import _page_text
        pages = []
        try:
            for page in doc:
                try:
                    t = _page_text(page)
                except Exception:
                    t = ""
                t = re.sub(r"\s+", " ", t)
                t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
                pages.append(t)
        finally:
            doc.close()

        _write_text_cache(sym, resolved_year, pages, resolved_url)
        return {
            "pages": pages, "fiscal_year": resolved_year, "pdf_url": resolved_url,
            "pdf_from_cache": pdf_from_cache, "text_from_cache": False,
        }
