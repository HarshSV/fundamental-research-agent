"""
Canonical qualitative evidence model (Phase 3B).

Separate and independent from every Phase 2 quantitative module - this file
does not import, read, or reference `fundamental_ratio_registry`,
`ratio_calculation_engine`, `fundamental_fact_store`, or `statement_selector`
in any way, and defines its own `QUALITATIVE_EXTRACTION_VERSION` (starting
at 1) rather than reusing the quantitative `EXTRACTION_VERSION`.

This module does not itself fetch anything. It defines the TYPES that
`tools.qualitative_evidence_extraction` populates and that a future Phase 3C
engine will consume - the "canonical fact store" equivalent for the
qualitative side, except the atomic unit is `QualitativeEvidence`
(a bounded, provenance-bearing excerpt/record) rather than a single number.

Mandatory distinctions this module encodes as data, not comments:
  - NOT_DISCLOSED (searched, genuinely absent) != VERIFIED_ABSENT (filing
    explicitly states the negative) - see `EvidenceStatus`.
  - confidence is independent of score/status - see `Confidence`, which
    carries no coupling to any score value anywhere in this module.
  - "source exists and was searched" / "exists but search failed" /
    "does not exist" / "not applicable" are four distinct states - see
    `SourceAvailability`, consumed by `EvidenceBundle.classify()` to avoid
    ever reporting NOT_DISCLOSED for a source that was never available.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

QUALITATIVE_EXTRACTION_VERSION = 1

# Evidence excerpts must remain bounded - never the whole document. This is
# enforced by `truncate_excerpt`, used everywhere a QualitativeEvidence is
# constructed from raw extracted text.
MAX_EXCERPT_CHARS = 600


def truncate_excerpt(text: Optional[str], max_chars: int = MAX_EXCERPT_CHARS) -> Optional[str]:
    if text is None:
        return None
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


class EvidenceStatus(str, Enum):
    """Canonical status vocabulary. Distinct on purpose - never collapse
    NOT_DISCLOSED into VERIFIED_ABSENT, and never treat "no evidence found"
    as a negative characteristic unless the scoring contract explicitly
    says non-disclosure itself is scored (that decision belongs to Phase
    3C/3D task contracts, never to this module)."""
    VERIFIED = "VERIFIED"                          # corroborated across >=2 independent sources
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"       # single credible source, no contradiction
    NEEDS_REVIEW = "NEEDS_REVIEW"                   # ambiguous / proxy evidence
    NOT_DISCLOSED = "NOT_DISCLOSED"                 # source(s) searched, genuinely absent
    VERIFIED_ABSENT = "VERIFIED_ABSENT"             # filing explicitly states the negative
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE" # couldn't search enough sources to conclude
    NOT_APPLICABLE = "NOT_APPLICABLE"               # structurally irrelevant (sector/structure gate)
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"  # sources disagree, unresolved
    ERROR = "ERROR"                                 # processing failure, not a data conclusion


class SourceAvailability(str, Enum):
    """Requirement #10 - four distinct states a source can be in for one
    task, so a caller can never legitimately claim NOT_DISCLOSED for a
    source that was never actually available or never successfully
    searched."""
    SEARCHED_FOUND = "SEARCHED_FOUND"          # A: source exists, was searched, evidence found
    SEARCHED_NOT_FOUND = "SEARCHED_NOT_FOUND"  # A: source exists, was searched, nothing found
    SEARCH_FAILED = "SEARCH_FAILED"            # B: source exists but the search itself failed (I/O, parse error)
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"  # C: source does not exist / was never uploaded
    NOT_APPLICABLE = "NOT_APPLICABLE"          # D: this source type is not applicable to this task/company


class ConfidenceTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Confidence:
    """Independent from score/status - a caller can legitimately construct
    Confidence(tier=LOW, score=0.2) alongside ANY status, including
    VERIFIED, or Confidence(tier=HIGH) alongside NOT_DISCLOSED (high
    confidence that the search was thorough and the item genuinely isn't
    disclosed). Nothing in this class derives from or references a score
    value - that coupling is exactly what Phase 3B must NOT introduce."""
    tier: ConfidenceTier
    score: Optional[float] = None   # 0.0-1.0, optional numeric refinement of `tier`
    reason: str = ""


def make_evidence_id(company_identity: str, fiscal_year: Optional[int], task_key: str,
                      subtask_key: str, source_document: Optional[str],
                      extraction_method: str, extracted_text: Optional[str]) -> str:
    """Stable, deterministic evidence ID - same inputs always produce the
    same ID (so re-extracting unchanged evidence doesn't create a
    duplicate), different inputs always produce a different ID. Hashes the
    first 200 chars of the (already-truncated) excerpt, not the whole text,
    so the ID is bounded-cost to compute and stable under retries that
    re-fetch the identical excerpt."""
    key = "|".join([
        (company_identity or "").strip().upper(),
        str(fiscal_year or ""),
        task_key or "", subtask_key or "",
        (source_document or "")[:200],
        extraction_method or "",
        (extracted_text or "")[:200],
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class QualitativeEvidence:
    evidence_id: str
    company_identity: str
    fiscal_year: Optional[int]
    task_key: str
    subtask_key: str
    evidence_type: str                    # e.g. "related_party_transaction", "board_composition"
    source_document: Optional[str]        # URL/identifier of the document this came from
    source_document_type: str             # one of tools.qualitative_source_router.SourceType values
    page_number: Optional[int]
    section: Optional[str]
    heading: Optional[str]
    extracted_text: Optional[str]         # bounded excerpt (see MAX_EXCERPT_CHARS) - never full document
    normalized_value: Any                 # the structured fact/classification derived from extracted_text
    evidence_date: Optional[str]          # filing/disclosure date - never "today"
    source_priority: int                  # lower = preferred, from the source-routing contract
    extraction_method: str                # e.g. "keyword_anchor", "structured_field", "table_extraction"
    confidence: Confidence
    status: EvidenceStatus
    extraction_version: int = QUALITATIVE_EXTRACTION_VERSION

    @staticmethod
    def build(company_identity: str, fiscal_year: Optional[int], task_key: str, subtask_key: str,
              evidence_type: str, source_document: Optional[str], source_document_type: str,
              extracted_text: Optional[str], normalized_value: Any, status: EvidenceStatus,
              confidence: Confidence, source_priority: int = 99, extraction_method: str = "keyword_anchor",
              page_number: Optional[int] = None, section: Optional[str] = None,
              heading: Optional[str] = None, evidence_date: Optional[str] = None) -> "QualitativeEvidence":
        """Preferred constructor - truncates the excerpt and computes the
        stable ID, so callers never have to remember either step."""
        excerpt = truncate_excerpt(extracted_text)
        eid = make_evidence_id(company_identity, fiscal_year, task_key, subtask_key,
                                source_document, extraction_method, excerpt)
        return QualitativeEvidence(
            evidence_id=eid, company_identity=company_identity, fiscal_year=fiscal_year,
            task_key=task_key, subtask_key=subtask_key, evidence_type=evidence_type,
            source_document=source_document, source_document_type=source_document_type,
            page_number=page_number, section=section, heading=heading,
            extracted_text=excerpt, normalized_value=normalized_value, evidence_date=evidence_date,
            source_priority=source_priority, extraction_method=extraction_method,
            confidence=confidence, status=status,
        )


@dataclass
class EvidenceBundle:
    """Multiple evidence objects for ONE task/subtask - never silently
    merged (requirement #8). `source_availability` records, per source
    type, what actually happened when that source was consulted (or why it
    wasn't), so `classify()` can distinguish NOT_DISCLOSED from
    INSUFFICIENT_EVIDENCE honestly (requirement #10)."""
    company_identity: str
    fiscal_year: Optional[int]
    task_key: str
    subtask_key: str
    evidence: List[QualitativeEvidence] = field(default_factory=list)
    source_availability: Dict[str, SourceAvailability] = field(default_factory=dict)

    def add(self, ev: QualitativeEvidence) -> None:
        self.evidence.append(ev)

    def corroborating_sources(self) -> List[Tuple[QualitativeEvidence, QualitativeEvidence]]:
        """Pairs of evidence from DIFFERENT source_document_types whose
        normalized_value agrees - deterministic corroboration detection,
        never assumed."""
        pairs = []
        for i, a in enumerate(self.evidence):
            for b in self.evidence[i + 1:]:
                # Scoped to the SAME evidence_type/concept - a task's
                # bundle commonly holds evidence for several distinct
                # concepts at once (e.g. promoter_ownership AND
                # promoter_pledge), which must never be cross-compared as
                # if they were competing claims about the same fact.
                if a.evidence_type == b.evidence_type and a.source_document_type != b.source_document_type and \
                        a.normalized_value == b.normalized_value and a.normalized_value is not None:
                    pairs.append((a, b))
        return pairs

    def contradicting_pairs(self) -> List[Tuple[QualitativeEvidence, QualitativeEvidence]]:
        """Pairs of evidence whose normalized_value genuinely disagrees -
        e.g. Annual Report says promoter holding = X, Shareholding filing
        says Y. Scoped to the SAME evidence_type (same rationale as
        `corroborating_sources`) - two DIFFERENT concepts (e.g. promoter
        ownership vs. promoter pledge) having different values is not a
        conflict, it's just two different facts. Never silently resolved
        here - Phase 3C's task engine decides how to act on a
        CONTRADICTORY_EVIDENCE status; this layer only detects and
        represents the conflict."""
        pairs = []
        for i, a in enumerate(self.evidence):
            for b in self.evidence[i + 1:]:
                if a.evidence_type == b.evidence_type and a.normalized_value is not None \
                        and b.normalized_value is not None and a.normalized_value != b.normalized_value:
                    pairs.append((a, b))
        return pairs

    def classify(self) -> Tuple[EvidenceStatus, Confidence]:
        """Generic, task-agnostic status/confidence derivation from the
        collected evidence + source-availability record. This is the ONE
        place these rules live - a scoring function built on top of this
        bundle never needs to know filename/company/page layout, only this
        bundle's already-classified status+confidence+evidence list."""
        if any(a == SourceAvailability.NOT_APPLICABLE for a in self.source_availability.values()) \
                and not self.evidence and not any(
                    a in (SourceAvailability.SEARCHED_FOUND, SourceAvailability.SEARCHED_NOT_FOUND)
                    for a in self.source_availability.values()):
            return EvidenceStatus.NOT_APPLICABLE, Confidence(ConfidenceTier.HIGH, 1.0, "sector/structure gate")

        searched = [a for a in self.source_availability.values()
                    if a in (SourceAvailability.SEARCHED_FOUND, SourceAvailability.SEARCHED_NOT_FOUND)]
        failed = [a for a in self.source_availability.values() if a == SourceAvailability.SEARCH_FAILED]
        unavailable = [a for a in self.source_availability.values() if a == SourceAvailability.SOURCE_UNAVAILABLE]

        if not self.evidence:
            if searched:
                # Every applicable source that COULD be reached was
                # reached, and none of them had the item - genuinely
                # NOT_DISCLOSED, not a search failure.
                conf = ConfidenceTier.HIGH if not failed and not unavailable else ConfidenceTier.MEDIUM
                return EvidenceStatus.NOT_DISCLOSED, Confidence(conf, None, "searched, nothing found")
            if failed or unavailable:
                return EvidenceStatus.INSUFFICIENT_EVIDENCE, Confidence(
                    ConfidenceTier.LOW, None, "no source could be searched")
            return EvidenceStatus.INSUFFICIENT_EVIDENCE, Confidence(
                ConfidenceTier.UNKNOWN, None, "no source availability recorded")

        # Scoped per evidence_type (concept) - a bundle legitimately holds
        # multiple distinct concepts for one task (e.g. promoter_ownership
        # PRESENT alongside promoter_pledge ABSENT is not a conflict, it's
        # two different facts). Only flag CONTRADICTORY_EVIDENCE when the
        # SAME concept has both an absent and a present claim.
        by_concept: Dict[str, List[QualitativeEvidence]] = {}
        for e in self.evidence:
            by_concept.setdefault(e.evidence_type, []).append(e)
        concept_conflict = False
        all_absent = all(e.status == EvidenceStatus.VERIFIED_ABSENT for e in self.evidence
                          if e.status != EvidenceStatus.ERROR)
        for concept_evidence in by_concept.values():
            c_absent = [e for e in concept_evidence if e.status == EvidenceStatus.VERIFIED_ABSENT]
            c_present = [e for e in concept_evidence if e.status not in
                         (EvidenceStatus.VERIFIED_ABSENT, EvidenceStatus.ERROR)]
            if c_absent and c_present:
                concept_conflict = True
        if concept_conflict:
            return EvidenceStatus.CONTRADICTORY_EVIDENCE, Confidence(
                ConfidenceTier.MEDIUM, None, "explicit absence conflicts with other present evidence for the same concept")
        if all_absent and self.evidence:
            absent = [e for e in self.evidence if e.status == EvidenceStatus.VERIFIED_ABSENT]
            conf = ConfidenceTier.HIGH if len(absent) > 1 else ConfidenceTier.MEDIUM
            return EvidenceStatus.VERIFIED_ABSENT, Confidence(conf, None, "filing explicitly states the negative")

        if self.contradicting_pairs():
            return EvidenceStatus.CONTRADICTORY_EVIDENCE, Confidence(
                ConfidenceTier.MEDIUM, None, "sources disagree on normalized_value")
        if self.corroborating_sources():
            return EvidenceStatus.VERIFIED, Confidence(ConfidenceTier.HIGH, None, "corroborated across sources")

        present = [e for e in self.evidence if e.status not in
                   (EvidenceStatus.VERIFIED_ABSENT, EvidenceStatus.ERROR)]
        distinct_types = {e.source_document_type for e in present}
        if len(present) >= 2 and len(distinct_types) == 1:
            # Multiple excerpts, but all from the SAME source document type -
            # not independent corroboration, still just one source.
            return EvidenceStatus.PARTIALLY_VERIFIED, Confidence(
                ConfidenceTier.MEDIUM, None, "multiple excerpts, single source type")
        return EvidenceStatus.PARTIALLY_VERIFIED, Confidence(
            ConfidenceTier.LOW if len(present) == 1 else ConfidenceTier.MEDIUM,
            None, "single source, not cross-verified")
