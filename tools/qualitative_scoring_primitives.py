"""
Reusable qualitative scoring/interpretation primitives (Phase 3, final
pass, spec section 4).

Consolidates the MECHANICS the ~42 duplicated `*_scoring.py` two-tier
regex modules share (specific-claim-vs-generic-mention-vs-nothing) behind
named, reusable functions - built ON TOP of the ONE genuinely shared helper
that already existed (`tools.qualitative_evidence_scoring.score_evidence_tier`/
`classify_status`, already reused by ~12 of the 54 modules), rather than
inventing a second parallel mechanism. Task-specific differences (the
actual regex patterns, category labels, thresholds) stay in the registry
contract / task-specific call site - this module supplies the SHAPE
(explicit yes/no, categorical classification, threshold, evidence-count),
never a specific business rule for an individual task.

Every function here is a pure function of already-extracted text/values -
no I/O, no company/filename knowledge, no PDF layout awareness (spec
section 11's "the interpreter should NOT know anything about PDF layout").
"""

import re
from typing import List, Optional, Tuple

from tools.qualitative_evidence_scoring import score_evidence_tier, classify_status

# Standard audit-opinion categories (SA 700/705, universal across every
# Indian Annual Report, never company-specific) - a concrete, non-fabricated
# categorical rule, in the exact priority order a real opinion paragraph
# should be checked (most severe first, so "adverse" is never masked by a
# coincidental "qualified" substring elsewhere in the same paragraph).
AUDIT_OPINION_CATEGORIES: List[Tuple[str, "re.Pattern"]] = [
    ("Disclaimer", re.compile(r"disclaimer of opinion", re.I)),
    ("Adverse", re.compile(r"adverse opinion", re.I)),
    ("Qualified", re.compile(r"qualified opinion|basis for qualified opinion", re.I)),
    ("Unmodified", re.compile(r"unmodified opinion|unqualified opinion|true and fair view", re.I)),
]


def interpret_explicit_yes_no(text: Optional[str], yes_re: "re.Pattern", no_re: "re.Pattern") -> Optional[bool]:
    """Generic explicit yes/no interpreter (spec section 11). Returns True/
    False only on an unambiguous match, None if neither pattern matches -
    never guessed from absence."""
    if not text:
        return None
    if no_re.search(text):
        return False
    if yes_re.search(text):
        return True
    return None


def interpret_categorical(text: Optional[str], categories: List[Tuple[str, "re.Pattern"]]) -> Optional[str]:
    """Generic categorical classifier - thin wrapper over the existing
    `qualitative_evidence_scoring.classify_status` (never re-implemented),
    exposed under a name matching this module's vocabulary (spec section
    11's 'categorical classification' interpreter)."""
    status_patterns = [(label, pattern) for label, pattern in categories]
    return classify_status(text, status_patterns)


def interpret_audit_opinion(text: Optional[str]) -> Optional[str]:
    """Concrete, non-fabricated categorical rule (spec section 5/6) - the
    universal SA 700/705 opinion taxonomy, same for every company."""
    return interpret_categorical(text, AUDIT_OPINION_CATEGORIES)


# Severity-ordered 1-5 mapping, directly encoding the registry's own C.6.3
# formula_or_matrix text: "unmodified opinion = highest; material
# qualifications reduce score according to severity" - Disclaimer (auditor
# could not even form an opinion) is the most severe, Adverse next, then
# Qualified. Deliberately does NOT attempt the formula's "...and
# recurrence" clause - that needs a multi-year opinion history this
# evidence layer doesn't collect yet; scoring only the severity component
# is a real (partial) implementation of the stated rule, not a fabricated
# full one - documented here rather than silently claimed complete.
AUDIT_OPINION_SEVERITY_SCORE = {
    "Unmodified": 5,
    "Qualified": 3,
    "Adverse": 2,
    "Disclaimer": 1,
}


def interpret_audit_opinion_severity_score(text: Optional[str]) -> Optional[int]:
    """The registry's own 1-5 scale for this rule, derived from
    `interpret_audit_opinion`'s categorical result - never a second,
    independent classification that could disagree with it."""
    category = interpret_audit_opinion(text)
    if category is None:
        return None
    return AUDIT_OPINION_SEVERITY_SCORE.get(category)


def interpret_threshold(value: Optional[float], threshold: float, above_label: str,
                         at_or_below_label: str) -> Optional[str]:
    """Generic threshold classifier (spec section 11) - e.g. segment
    concentration's 90% rule, capacity utilisation bands, or any other
    task whose formula_or_matrix is a plain numeric cutoff. The threshold
    itself is supplied by the CALLER (from the task's own
    `formula_or_matrix`), never hardcoded here."""
    if value is None:
        return None
    return above_label if value >= threshold else at_or_below_label


def interpret_evidence_tier(text: Optional[str], specific_re: Optional["re.Pattern"] = None,
                             generic_re: Optional["re.Pattern"] = None,
                             high_score: int = 4, mid_score: int = 3) -> Tuple[Optional[bool], Optional[int]]:
    """Direct pass-through to the existing shared tier scorer - kept under
    this module's naming convention so callers reach every primitive
    through ONE module rather than importing qualitative_evidence_scoring
    directly for some concepts and this module for others."""
    return score_evidence_tier(text, specific_re=specific_re, generic_re=generic_re,
                                high_score=high_score, mid_score=mid_score)


def interpret_evidence_count(evidence_list: List) -> int:
    """Generic evidence-count scoring primitive (spec section 4's list) -
    the number of independent, non-duplicate evidence items found for a
    concept. Never a proxy for QUALITY (a single strong disclosure and five
    boilerplate mentions are not equivalent) - callers combine this with a
    tier/categorical interpretation, never use the raw count alone as a
    score."""
    return len(evidence_list or [])
