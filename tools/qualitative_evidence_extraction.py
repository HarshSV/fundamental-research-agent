"""
Reusable qualitative evidence extraction primitives (Phase 3B).

Wraps EXISTING, working extraction mechanisms - never re-implements them:
  - text-based primitives call
    `tools.annual_report_financials._fetch_ar_evidence_excerpts` (the
    shared scan-every-page-for-anchor-phrases engine already behind 282
    call sites in `qualitative_engine.py`), passing the SAME
    `extra_manual_document_types` mechanism that already lets it search
    uploaded Corporate Governance/BRSR/etc. documents alongside the
    Annual Report.
  - structured primitives call the existing scrapers directly:
    `tools.governance_scraper.fetch_latest_governance_filing`,
    `tools.shareholding_scraper.fetch_shareholding`,
    `tools.insider_trading_scraper.fetch_insider_trades`.

Every primitive returns a `tools.qualitative_evidence.EvidenceBundle` -
never a raw string, never an untraceable conclusion. This module is the
Phase 3B "extraction requirements" layer Phase 3C's task engine will call
instead of each of the 344 `qualitative_engine.py` functions re-implementing
its own fetch+score+persist sequence.

Company-agnostic by construction: every function signature takes
(symbol, name, fiscal_year, task_key, subtask_key, ...) - there is no
per-company or per-filename branch anywhere in this file (enforced by
tests/test_qualitative_evidence_architecture.py's static guard).
"""

import re
from typing import Dict, List, Optional, Tuple

from tools.qualitative_evidence import (
    Confidence, ConfidenceTier, EvidenceBundle, EvidenceStatus, QualitativeEvidence,
)
from tools.qualitative_source_router import resolve_availability

# --------------------------------------------------------------------------- #
# Terminology normalization (requirement #7). Concept key -> the phrase
# family that should all map to the SAME evidence_type, so a company that
# captions something "RPT" and another that captions it "Transactions with
# Related Parties" produce comparable evidence, not two different concepts.
# Generic across every company - never a per-company synonym.
# --------------------------------------------------------------------------- #
TERMINOLOGY_ALIASES: Dict[str, List[str]] = {
    "related_party_transaction": [
        "related party", "related parties", "related party disclosures",
        "related party transactions", "transactions with related parties", "rpt",
    ],
    "litigation": [
        "litigation", "legal proceedings", "pending litigations", "contingent liabilities",
        "material litigation", "court case", "arbitration proceedings",
    ],
    "auditor_qualification": [
        "qualified opinion", "adverse opinion", "disclaimer of opinion", "emphasis of matter",
        "key audit matter", "basis for qualified opinion", "modified opinion",
    ],
    "dividend_policy": [
        "dividend policy", "dividend distribution policy", "dividend payout policy",
    ],
    "capital_allocation": [
        "capital allocation", "capital allocation policy", "use of proceeds",
        "capital expenditure plan", "capex plan",
    ],
    "risk_disclosure": [
        "risk factors", "risk management", "principal risks", "key risks", "risk and concerns",
    ],
    "customer_concentration": [
        "major customers", "customer concentration", "top customers", "significant customers",
        "revenue from major customers",
    ],
    "segment_concentration": [
        "segment information", "operating segments", "reportable segments", "segment revenue",
    ],
    "remuneration_disclosure": [
        "managerial remuneration", "remuneration of directors", "remuneration policy",
        "kmp remuneration",
    ],
    "esg_metric": [
        "brsr", "business responsibility", "esg", "sustainability", "ghg emissions",
        "carbon footprint", "csr", "corporate social responsibility",
    ],
    "business_concentration": [
        "geographic concentration", "revenue concentration", "export revenue", "domestic revenue",
    ],
    "promoter_ownership": [
        "promoter holding", "promoter shareholding", "promoter group",
    ],
    "promoter_pledge": [
        "pledge", "encumbrance", "pledged shares",
    ],
    # --- Phase 3 final pass additions (spec section 6) ---
    "contingent_liabilities": [
        "contingent liabilities", "contingent liability", "claims not acknowledged as debt",
        "guarantees given", "capital commitments",
    ],
    "audit_observations": [
        "auditor's observations", "qualifications in audit report", "reservations", "adverse remarks",
        "cara", "companies auditor's report order",
    ],
    "supplier_concentration": [
        "major suppliers", "supplier concentration", "top suppliers", "significant suppliers",
        "single source supplier", "vendor concentration",
    ],
    "board_independence": [
        "independent director", "independent directors", "non-executive director",
        "board independence",
    ],
    "committee_structure": [
        "audit committee", "nomination and remuneration committee", "stakeholders relationship committee",
        "corporate social responsibility committee", "risk management committee",
    ],
    "institutional_ownership": [
        "institutional holding", "fii holding", "dii holding", "foreign portfolio investors",
        "mutual fund holding",
    ],
    "employee_human_capital": [
        "employee attrition", "attrition rate", "human capital", "employee benefit expense",
        "training and development", "diversity and inclusion", "employee turnover",
    ],
    "competitive_position": [
        "competitive landscape", "market position", "competitive advantage", "competitors",
        "market share",
    ],
    "management_quality": [
        "management discussion and analysis", "management commentary", "leadership team",
        "key managerial personnel",
    ],
    "capital_discipline": [
        "return on capital employed", "capital discipline", "capital efficiency",
        "capex discipline", "investment discipline",
    ],
    "regulatory_exposure": [
        "regulatory risk", "regulatory changes", "compliance requirements", "licences and approvals",
        "statutory compliance",
    ],
    "credit_rating_evidence": [
        "credit rating", "rating rationale", "rating outlook", "crisil", "icra", "care ratings",
    ],
    "business_model": [
        "business model", "revenue model", "recurring revenue", "subscription revenue",
        "contract revenue",
    ],
}

# Concepts that are genuinely structured/numeric and need a THRESHOLD or
# COUNT-based interpretation, not a plain presence/absence text scan - the
# actual analytical rule (spec section 5's "preserve unique business
# logic") lives in `tools.qualitative_task_engine`'s dedicated
# interpreters, not here. Listed so the engine and the registry-migration
# gate can identify which concepts have a real, non-generic rule wired.
STRUCTURED_INTERPRETATION_CONCEPTS = {
    "segment_concentration_threshold",  # A.1.A-style single-product vs portfolio, 90% rule
}

# Phrases indicating an EXPLICIT NEGATIVE disclosure (spec's VERIFIED_ABSENT
# vs NOT_DISCLOSED distinction) - generic across every concept, never
# per-company. Matched in a bounded window around a terminology-alias hit.
_NEGATION_MARKERS_RE = re.compile(
    r"\b(?:does not have|do not have|no such|not applicable|there (?:were|was|are|is) no|"
    r"the company has not|none (?:identified|reported)|nil\b|not maintained)\b", re.I,
)


def normalize_concept(text: Optional[str]) -> Optional[str]:
    """Maps free text to a canonical concept key via TERMINOLOGY_ALIASES, or
    None if no alias family matches. Case-insensitive substring match -
    deliberately simple and auditable rather than fuzzy/ML matching, so the
    mapping is always traceable back to an explicit phrase list."""
    low = (text or "").lower()
    for concept, phrases in TERMINOLOGY_ALIASES.items():
        if any(p in low for p in phrases):
            return concept
    return None


# How far (characters) a negation marker may be from an actual concept-alias
# mention within the SAME excerpt and still be read as negating THAT
# concept. Found necessary by real-company validation (Amrutanjan FY25 AR):
# a single ~600-char excerpt window legitimately contains several DIFFERENT,
# narrower claims near an RPT anchor match - "no trade receivables FROM
# related parties" and "no transactions NOT AT ARM'S LENGTH basis" are each
# narrower facts about related parties, not a blanket "no related party
# transactions exist" - while the excerpt as a whole (and the filing
# overall) plainly DOES disclose real related-party transactions elsewhere.
# An unscoped negation search flagged those narrower excerpts VERIFIED_ABSENT,
# producing a real (general, not company-specific) false-negative/
# CONTRADICTORY_EVIDENCE bug once combined with the genuine positive excerpt
# also found for the same company.
_NEGATION_PROXIMITY_CHARS = 80


def _classify_excerpt_status(excerpt_text: str, concept: Optional[str] = None) -> EvidenceStatus:
    """PARTIALLY_VERIFIED (plain positive mention) vs VERIFIED_ABSENT
    (explicit negative disclosure SCOPED to the actual concept, not just any
    negation phrase found anywhere in a large excerpt window) - never
    NOT_DISCLOSED here, since reaching this function already means text WAS
    found; NOT_DISCLOSED is reserved for the bundle-level "searched, nothing
    found" case in EvidenceBundle.classify()."""
    if not excerpt_text:
        return EvidenceStatus.PARTIALLY_VERIFIED
    aliases = TERMINOLOGY_ALIASES.get(concept, []) if concept else []
    low = excerpt_text.lower()
    for m in _NEGATION_MARKERS_RE.finditer(excerpt_text):
        if not aliases:
            return EvidenceStatus.VERIFIED_ABSENT  # no concept context to scope against - unchanged prior behaviour
        window_start = max(0, m.start() - _NEGATION_PROXIMITY_CHARS)
        window_end = min(len(excerpt_text), m.end() + _NEGATION_PROXIMITY_CHARS)
        window = low[window_start:window_end]
        if any(alias in window for alias in aliases):
            return EvidenceStatus.VERIFIED_ABSENT
    return EvidenceStatus.PARTIALLY_VERIFIED


def extract_text_based_evidence(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                 task_key: str, subtask_key: str, concept: str,
                                 cache_prefix: str, extra_manual_document_types: Optional[Tuple[str, ...]] = None,
                                 bio_filter: bool = False, max_excerpts: int = 8) -> EvidenceBundle:
    """The generic primitive underlying most narrative-text concepts
    (policy disclosure, litigation, auditor qualification, dividend policy,
    capital allocation, risk disclosure, customer/segment/business
    concentration, remuneration, ESG narrative, ...). Wraps
    `annual_report_financials._fetch_ar_evidence_excerpts` with the
    concept's own alias phrase list as anchors - never re-implements PDF
    scan/cache logic.
    """
    bundle = EvidenceBundle(company_identity=(symbol or "").strip().upper(), fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    anchors = TERMINOLOGY_ALIASES.get(concept)
    if not anchors:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=False, applicable=True)
        return bundle

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        result = _fetch_ar_evidence_excerpts(
            symbol, name, anchors, cache_prefix, fiscal_year=fiscal_year, bio_filter=bio_filter,
            max_excerpts=max_excerpts, fetch_label=concept,
            extra_manual_document_types=extra_manual_document_types,
        )
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    if not isinstance(result, dict) or "error" in result:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, found=False)
        return bundle

    excerpts = result.get("excerpts") or []
    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(excerpts))

    for exc in excerpts:
        text = exc.get("text") or ""
        status = _classify_excerpt_status(text, concept)
        ev = QualitativeEvidence.build(
            company_identity=bundle.company_identity, fiscal_year=fiscal_year,
            task_key=task_key, subtask_key=subtask_key, evidence_type=concept,
            source_document=result.get("pdf_url"), source_document_type="annual_report",
            extracted_text=text, normalized_value=("ABSENT" if status == EvidenceStatus.VERIFIED_ABSENT else "PRESENT"),
            status=status, confidence=Confidence(ConfidenceTier.MEDIUM, None, "single-pass anchor match"),
            source_priority=10, extraction_method="keyword_anchor",
            page_number=exc.get("page"), heading=exc.get("anchor"),
        )
        bundle.add(ev)
    return bundle


def extract_board_composition(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                               task_key: str, subtask_key: str) -> EvidenceBundle:
    """Structured primitive - wraps `governance_scraper.
    fetch_latest_governance_filing` (real NSE Corporate Governance JSON),
    never regex over Annual Report text for a fact that has a structured
    source."""
    bundle = EvidenceBundle(company_identity=(symbol or "").strip().upper(), fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    try:
        from tools.governance_scraper import fetch_latest_governance_filing
        data = fetch_latest_governance_filing(symbol)
    except Exception:
        bundle.source_availability["quarterly_corporate_governance_filing"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    if not data or not data.get("board"):
        bundle.source_availability["quarterly_corporate_governance_filing"] = resolve_availability(
            available=bool(data), searched=True, found=False)
        return bundle

    bundle.source_availability["quarterly_corporate_governance_filing"] = resolve_availability(
        available=True, searched=True, found=True)
    ev = QualitativeEvidence.build(
        company_identity=bundle.company_identity, fiscal_year=fiscal_year,
        task_key=task_key, subtask_key=subtask_key, evidence_type="board_composition",
        source_document=data.get("source_url"), source_document_type="quarterly_corporate_governance_filing",
        extracted_text=None, normalized_value=data.get("board"),
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.HIGH, None, "structured regulatory filing"),
        source_priority=1, extraction_method="structured_field",
        evidence_date=data.get("as_of_quarter"),
    )
    bundle.add(ev)
    return bundle


def extract_promoter_ownership(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                task_key: str, subtask_key: str) -> EvidenceBundle:
    """Structured primitive - wraps `shareholding_scraper.fetch_shareholding`
    (promoter holding % + pledge %, real NSE/Screener data)."""
    bundle = EvidenceBundle(company_identity=(symbol or "").strip().upper(), fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    try:
        from tools.shareholding_scraper import fetch_shareholding
        data = fetch_shareholding(symbol, name)
    except Exception:
        bundle.source_availability["shareholding_pattern_filing"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    promoter_pct = (data or {}).get("promoter_holding_pct")
    bundle.source_availability["shareholding_pattern_filing"] = resolve_availability(
        available=True, searched=True, found=promoter_pct is not None)
    if promoter_pct is None:
        return bundle

    ev = QualitativeEvidence.build(
        company_identity=bundle.company_identity, fiscal_year=fiscal_year,
        task_key=task_key, subtask_key=subtask_key, evidence_type="promoter_ownership",
        source_document=data.get("source"), source_document_type="shareholding_pattern_filing",
        extracted_text=None, normalized_value=promoter_pct,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.HIGH, None, "structured shareholding source"),
        source_priority=1, extraction_method="structured_field", evidence_date=data.get("as_of_quarter"),
    )
    bundle.add(ev)

    pledge_pct = data.get("promoter_pledge_pct")
    if pledge_pct is not None:
        pledge_ev = QualitativeEvidence.build(
            company_identity=bundle.company_identity, fiscal_year=fiscal_year,
            task_key=task_key, subtask_key=subtask_key, evidence_type="promoter_pledge",
            source_document=data.get("source"), source_document_type="shareholding_pattern_filing",
            extracted_text=None, normalized_value=pledge_pct,
            status=(EvidenceStatus.VERIFIED_ABSENT if pledge_pct == 0
                    and data.get("pledge_status") == "ok" else EvidenceStatus.PARTIALLY_VERIFIED),
            confidence=Confidence(
                ConfidenceTier.MEDIUM if data.get("pledge_status") == "assumed_zero" else ConfidenceTier.HIGH,
                None, f"pledge_status={data.get('pledge_status')}"),
            source_priority=1, extraction_method="structured_field",
        )
        bundle.add(pledge_ev)

    institutional_pct = data.get("institutional_holding_pct")
    if institutional_pct is not None:
        inst_ev = QualitativeEvidence.build(
            company_identity=bundle.company_identity, fiscal_year=fiscal_year,
            task_key=task_key, subtask_key=subtask_key, evidence_type="institutional_ownership",
            source_document=data.get("source"), source_document_type="shareholding_pattern_filing",
            extracted_text=None, normalized_value=institutional_pct,
            status=EvidenceStatus.PARTIALLY_VERIFIED,
            confidence=Confidence(ConfidenceTier.HIGH, None, "structured shareholding source (FII+DII)"),
            source_priority=1, extraction_method="structured_field",
        )
        bundle.add(inst_ev)
    return bundle


def extract_segment_concentration(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                   task_key: str, subtask_key: str) -> EvidenceBundle:
    """The REAL A.1.A rule (spec section 5 - do not replace a precise rule
    with generic keyword matching): '1 segment OR one segment >=90% of
    revenue = Single Product; otherwise = Portfolio/Diversified', exactly
    the registry's own `formula_or_matrix` text for this task. Reuses
    `annual_report_financials.fetch_multi_year_segment_revenue` (an
    existing, working, READ-ONLY function already used by the qualitative
    engine for A.4 - not modified, not re-implemented) rather than
    re-deriving segment revenue from scratch."""
    bundle = EvidenceBundle(company_identity=(symbol or "").strip().upper(), fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    try:
        from tools.annual_report_financials import fetch_multi_year_segment_revenue
        by_year = fetch_multi_year_segment_revenue(symbol, name, n_years=1)
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    if not by_year:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, found=False)
        return bundle

    latest_year = max(by_year.keys())
    segments = by_year.get(latest_year) or []
    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(segments))
    if not segments:
        return bundle

    total = sum(s.get("value_cr", 0) or 0 for s in segments)
    if len(segments) == 1:
        classification = "Single Product"
        rationale = f"Only one reportable segment disclosed: {segments[0].get('label')}."
    elif total > 0:
        dominant = max(segments, key=lambda s: s.get("value_cr", 0) or 0)
        dominant_pct = (dominant.get("value_cr", 0) or 0) / total * 100
        if dominant_pct >= 90:
            classification = "Single Product"
            rationale = f"Segment '{dominant.get('label')}' is {dominant_pct:.1f}% of total segment revenue (>=90%)."
        else:
            classification = "Portfolio/Diversified"
            rationale = (f"Largest segment '{dominant.get('label')}' is only {dominant_pct:.1f}% of total "
                         f"segment revenue (<90%), across {len(segments)} reported segments.")
    else:
        return bundle  # total revenue is 0/unreadable - genuinely can't classify, not a fabricated call

    ev = QualitativeEvidence.build(
        company_identity=bundle.company_identity, fiscal_year=fiscal_year,
        task_key=task_key, subtask_key=subtask_key, evidence_type="segment_concentration_threshold",
        source_document=None, source_document_type="annual_report",
        extracted_text=rationale, normalized_value=classification,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.HIGH, None, "structured segment revenue note (Ind AS 108)"),
        source_priority=2, extraction_method="structured_field", evidence_date=str(latest_year),
    )
    bundle.add(ev)
    return bundle


def extract_insider_activity(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                              task_key: str, subtask_key: str) -> EvidenceBundle:
    """Structured primitive - wraps `insider_trading_scraper.fetch_insider_trades`
    (real Regulation 7(2) disclosures). Never infers intent (spec's own
    rule) - normalized_value is the raw transaction list, not an
    interpretation."""
    bundle = EvidenceBundle(company_identity=(symbol or "").strip().upper(), fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        trades = fetch_insider_trades(symbol)
    except Exception:
        bundle.source_availability["insider_trading_disclosures"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    bundle.source_availability["insider_trading_disclosures"] = resolve_availability(
        available=True, searched=True, found=bool(trades))
    if not trades:
        return bundle

    ev = QualitativeEvidence.build(
        company_identity=bundle.company_identity, fiscal_year=fiscal_year,
        task_key=task_key, subtask_key=subtask_key, evidence_type="insider_activity",
        source_document="NSE Regulation 7(2) disclosures", source_document_type="insider_trading_disclosures",
        extracted_text=None, normalized_value=trades,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.HIGH, None, "structured regulatory disclosure"),
        source_priority=1, extraction_method="structured_field",
    )
    bundle.add(ev)
    return bundle


# Registry-facing map: concept/primitive key -> the callable Phase 3C's
# engine will dispatch to. Text-based concepts share one generic primitive
# parameterized by `concept`; structured concepts each have their own
# wrapper. This is the seam the generator (item 5) uses to populate
# `required_evidence_types`/`extraction_requirements`.
TEXT_BASED_CONCEPTS = tuple(TERMINOLOGY_ALIASES.keys())
STRUCTURED_PRIMITIVES: Dict[str, str] = {
    "board_composition": "extract_board_composition",
    "committee_composition": "extract_board_composition",
    "director_independence": "extract_board_composition",
    "attendance": "extract_board_composition",
    "promoter_ownership": "extract_promoter_ownership",
    "promoter_pledge": "extract_promoter_ownership",
    "institutional_ownership": "extract_promoter_ownership",
    "insider_activity": "extract_insider_activity",
    "segment_concentration_threshold": "extract_segment_concentration",
}
