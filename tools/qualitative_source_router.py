"""
Universal qualitative source router (Phase 3B).

    task/subtask -> preferred source types -> fallback source types
        -> available documents -> (Phase 3C) evidence extraction

Source types are NOT invented here - they are the exact vocabulary the
application can already provide:
  - "annual_report": always structurally attempted (the automatic pipeline's
    baseline source; also uploadable in the manual workflow).
  - The 10 values of `tools.manual_document_pipeline.QUALITATIVE_DOCUMENT_TYPES`
    (imported, never duplicated) - the manual-upload taxonomy already wired
    to `annual_report_financials._fetch_ar_evidence_excerpts`'s
    `extra_manual_document_types` parameter.
  - "shareholding_pattern" / "corporate_governance_filing" /
    "insider_disclosure" / "credit_rating_report": the 4 structured-scraper
    sources already implemented (tools.shareholding_scraper,
    tools.governance_scraper, tools.insider_trading_scraper,
    tools.crisil_scraper) - aliased onto the closest matching
    QUALITATIVE_DOCUMENT_TYPES value below so there is exactly one
    canonical name per real source, not two competing taxonomies.

Routing is derived ONCE, generically, from each task's own `primary_source`
text via keyword classification (never per-task hardcoding, never
company/filename-specific) - the generator (Phase 3B item 5) calls
`route_task` once per registry row and bakes the result into
`preferred_sources`/`fallback_sources`, so at RUNTIME (Phase 3C) nothing
re-parses prose - it just reads the registry's own pre-computed fields.
"""

import re
from typing import Dict, List, Optional, Set, Tuple

from tools.qualitative_evidence import SourceAvailability

try:
    from tools.manual_document_pipeline import QUALITATIVE_DOCUMENT_TYPES
except Exception:  # pragma: no cover - keeps this module importable standalone
    QUALITATIVE_DOCUMENT_TYPES = (
        "corporate_governance_report", "brsr_esg_report", "investor_presentation",
        "earnings_call_transcript", "credit_rating_report", "corporate_actions",
        "shareholding_pattern_filing", "insider_trading_disclosures",
        "quarterly_corporate_governance_filing", "other_supporting_document",
    )

# The complete, real source-type vocabulary. "annual_report" is added
# because it is the one source that is never an upload slot (it's the
# automatic pipeline's own baseline) but is absolutely a real, always-
# attempted source type.
SOURCE_TYPES: Tuple[str, ...] = ("annual_report",) + tuple(QUALITATIVE_DOCUMENT_TYPES)

# Which source types have a REAL, already-implemented extraction mechanism
# behind them today (Phase 3B doesn't build new extraction - see
# tools/qualitative_evidence_extraction.py). A router entry can legitimately
# name a source type that has no extraction yet (e.g. "brsr_esg_report" has
# an upload slot but no dedicated primitive) - that's an honest
# SOURCE_UNAVAILABLE/not-yet-extractable state, not something to hide.
EXTRACTION_BACKED_SOURCE_TYPES: Set[str] = {
    "annual_report",
    "quarterly_corporate_governance_filing",  # tools.governance_scraper
    "shareholding_pattern_filing",             # tools.shareholding_scraper
    "insider_trading_disclosures",             # tools.insider_trading_scraper
    "credit_rating_report",                    # tools.crisil_scraper
}

# Generic keyword -> source type classification. Deliberately keyword-based
# (not per-task, not per-company) - the same table applies to all 364
# registry rows' `primary_source` prose. Order matters: first match per
# source type wins; multiple source types can match the same text (that's
# how a task ends up with >1 preferred source).
_SOURCE_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("shareholding_pattern_filing", [
        "shareholding pattern", "promoter holding", "promoter shareholding",
        "pledge", "encumbrance", "free float", "free-float",
    ]),
    ("insider_trading_disclosures", [
        "insider trading", "regulation 7(2)", "reg 7(2)", "pit regulations",
        "insider trades", "sast",
    ]),
    ("quarterly_corporate_governance_filing", [
        "corporate governance filing", "cobod", "board of directors composition",
        "committee composition", "attendance",
    ]),
    ("corporate_governance_report", [
        "corporate governance report", "governance report", "board's report",
        "boards report", "director's report", "directors report",
        "secretarial audit", "vigil mechanism", "whistle blower", "whistleblower",
    ]),
    ("brsr_esg_report", [
        "brsr", "business responsibility", "esg", "sustainability report",
        "environmental, social", "ghg emission", "carbon emission",
    ]),
    ("credit_rating_report", [
        "credit rating", "crisil", "icra", "care ratings", "rating rationale",
    ]),
    ("investor_presentation", [
        "investor presentation", "investor deck", "earnings presentation",
    ]),
    ("earnings_call_transcript", [
        "earnings call", "concall", "conference call transcript", "analyst call",
    ]),
    ("corporate_actions", [
        "corporate announcement", "regulation 30", "material event",
        "corporate action", "nse announcement", "bse announcement",
    ]),
]

# "related party" is deliberately generic and phrase-family-based (spec's
# own example) - notes to accounts, not a distinct upload slot, so it
# routes to annual_report with a heightened priority note rather than its
# own source type.
_ANNUAL_REPORT_ALWAYS_FALLBACK = True


def classify_source_types(primary_source_text: Optional[str]) -> Tuple[List[str], List[str]]:
    """Deterministic, generic classification of a task's `primary_source`
    prose into (preferred_sources, fallback_sources). No task ID, company
    name, or filename is ever inspected - only the sourcing-pathway text
    itself. `annual_report` is always included as at least a fallback,
    since nearly every qualitative task can be attempted there even when a
    more specific structured source is preferred."""
    text = (primary_source_text or "").lower()
    preferred: List[str] = []
    for source_type, keywords in _SOURCE_KEYWORDS:
        if any(kw in text for kw in keywords):
            preferred.append(source_type)

    fallback: List[str] = []
    ar_signal = ("annual report" in text or "notes to accounts" in text or "md&a" in text
                 or "management discussion" in text)
    if not preferred:
        # Nothing more specific matched - Annual Report is the universal
        # default preferred source (every task can at least be attempted
        # there), per _ANNUAL_REPORT_ALWAYS_FALLBACK's own intent.
        preferred = ["annual_report"]
    elif ar_signal and "annual_report" not in preferred:
        preferred.append("annual_report")
    elif _ANNUAL_REPORT_ALWAYS_FALLBACK and "annual_report" not in preferred:
        fallback.append("annual_report")

    # other_supporting_document is always a last-resort fallback - never a
    # preferred source (it's an undifferentiated bucket, per the Phase 3A
    # audit's finding that 9 named subtypes collapse into it).
    if "other_supporting_document" not in preferred and "other_supporting_document" not in fallback:
        fallback.append("other_supporting_document")

    return preferred, fallback


def route_task(task_row: Dict) -> Dict[str, List[str]]:
    """Takes one `qualitative_task_registry` row (a dict with at least
    `primary_source`) and returns the routing fields to bake into the
    registry at generation time. Pure function of the row's own text -
    no side effects, no I/O, no company/filename awareness."""
    preferred, fallback = classify_source_types(task_row.get("primary_source"))
    return {"preferred_sources": preferred, "fallback_sources": fallback}


def resolve_availability(available: bool, searched: bool, found: Optional[bool] = None,
                          search_failed: bool = False, applicable: bool = True) -> SourceAvailability:
    """Requirement #10 - the ONE place that decides which of the four
    source-availability states applies, from plain booleans a caller
    already knows (never inferred from company identity or filenames).

    `available`  - does this source type exist for this company at all
                   (an upload was made / a scraper returned real data)?
    `searched`   - was an actual extraction attempt made against it?
    `found`      - if searched, did it produce evidence (True/False)?
                   Ignored if `searched` is False.
    `search_failed` - the attempt was made but errored (I/O/parse failure),
                   distinct from a clean "nothing found".
    `applicable` - is this source type even relevant to this task/company
                   (e.g. BRSR for a company below the BRSR applicability
                   threshold)?
    """
    if not applicable:
        return SourceAvailability.NOT_APPLICABLE
    if not available:
        return SourceAvailability.SOURCE_UNAVAILABLE
    if not searched:
        return SourceAvailability.SOURCE_UNAVAILABLE
    if search_failed:
        return SourceAvailability.SEARCH_FAILED
    if found:
        return SourceAvailability.SEARCHED_FOUND
    return SourceAvailability.SEARCHED_NOT_FOUND


def is_extraction_backed(source_type: str) -> bool:
    """Whether Phase 3B/3C actually has a working extraction primitive for
    this source type today - used to avoid ever claiming NOT_DISCLOSED for
    a source type this codebase can't search yet."""
    return source_type in EXTRACTION_BACKED_SOURCE_TYPES
