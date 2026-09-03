"""
Single authoritative consolidated-vs-standalone resolver (spec §3.1's
`StatementSelection`) - the one place that decides which basis a company's
ratios/facts are computed from, instead of every one of the ~50 nse_xbrl.py
`fetch_X_from_annual_report(..., consolidated=True)` call sites deciding for
itself by always hardcoding True regardless of what's actually in the filing.

This is a thin, honest wrapper - NOT a reimplementation of extraction. The
actual consolidated-first / standalone-fallback logic already lives in
`tools.annual_report_financials._get_extracted_financials` (which requests
consolidated=True and falls back to standalone only when the Annual Report
genuinely has no consolidated statements - see that module's own "_v18"
cache-version comment for the symmetric fallback it already implements).
This module's job is to surface that ALREADY-COMPUTED decision
(`parsed["basis_used"]`) as a single reusable, cacheable, provenance-bearing
result, so callers stop passing a blind `consolidated=True` and instead pass
whatever this resolver actually determined.

Never company-specific: the same function runs for every symbol/year.
"""

import os
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class StatementSelection:
    selected_basis: str          # "CONSOLIDATED" | "STANDALONE"
    document_id: Optional[str]   # source_url of the Annual Report PDF used
    financial_year: int
    selection_reason: str


_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "cache", "statement_selection")
_CACHE_TTL = 12 * 3600  # matches db_ratio_reader's freshness-guard TTL


def _cache_path(symbol, fiscal_year):
    return os.path.join(_CACHE_DIR, f"{symbol}_{fiscal_year}.json")


def select_statement_basis(symbol, name, fiscal_year) -> StatementSelection:
    """Resolves CONSOLIDATED-first for (symbol, fiscal_year), falling back to
    STANDALONE only when the Annual Report genuinely has no consolidated
    statements (never on a downstream parse failure - that distinction is
    already enforced inside `_get_extracted_financials`/
    `_broad_extraction_to_parsed_shape`, which only fall back after failing
    to locate the consolidated statement's own anchor pages, not merely
    failing to extract every field from them).

    Cached on disk per (symbol, fiscal_year) for `_CACHE_TTL` so a single
    ratio-registry run resolves this once, not once per ratio. Never raises;
    an unresolvable company defaults to CONSOLIDATED with a "could not
    verify" reason rather than silently guessing STANDALONE (matching the
    existing codebase's consolidated-priority default).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    path = _cache_path(sym, fiscal_year)
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) <= _CACHE_TTL:
            with open(path, "r", encoding="utf-8") as fh:
                return StatementSelection(**json.load(fh))
    except Exception:
        pass

    selection = _resolve(sym, name, fiscal_year)

    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(selection), fh)
    except Exception:
        pass
    return selection


def _resolve(sym, name, fiscal_year) -> StatementSelection:
    try:
        from tools.annual_report_financials import _get_extracted_financials
        parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=True)
    except Exception as e:
        return StatementSelection(
            selected_basis="CONSOLIDATED",
            document_id=None,
            financial_year=fiscal_year,
            selection_reason=f"Could not verify statement basis ({e}); defaulting to consolidated-first.",
        )

    if not parsed or "error" in parsed:
        reason = (parsed or {}).get("error", "Annual Report not found or unreadable.")
        return StatementSelection(
            selected_basis="CONSOLIDATED",
            document_id=(parsed or {}).get("source_url"),
            financial_year=fiscal_year,
            selection_reason=f"Could not verify statement basis ({reason}); defaulting to consolidated-first.",
        )

    basis_used = parsed.get("basis_used")
    if basis_used == "standalone":
        return StatementSelection(
            selected_basis="STANDALONE",
            document_id=parsed.get("source_url"),
            financial_year=fiscal_year,
            selection_reason="No consolidated financial statements found in the Annual Report "
                              "for this fiscal year; using standalone (only basis genuinely present).",
        )
    # "consolidated", "broad_extraction" (manual-mode fallback shape, always
    # requested consolidated=True), or unset (older cache entry pre-dating
    # basis_used) all mean the consolidated request was actually satisfied.
    return StatementSelection(
        selected_basis="CONSOLIDATED",
        document_id=parsed.get("source_url"),
        financial_year=fiscal_year,
        selection_reason="Consolidated financial statements found and used.",
    )
