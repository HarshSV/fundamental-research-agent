"""
Shared deterministic (no-LLM) evidence-tier scorer, factoring out the
pattern already used independently across tools.regulatory_legal_scoring
and friends: a "specific" regex (a named, quantified, dated claim) scores
higher than a "generic" regex (boilerplate mention of the topic with no
specifics), and no match at all returns None - never a fabricated middle
score. Sections K-U (see tools/qualitative_task_registry.py) reuse this
single helper instead of re-implementing the same two-tier logic per
sub-point.
"""


def score_evidence_tier(text, specific_re=None, generic_re=None, high_score=4, mid_score=3):
    """Returns (specific_disclosed, score). specific_disclosed is True when
    `specific_re` matches (a concrete, quantified or named claim), False
    when only `generic_re` matches (topic mentioned but no specifics), and
    None (score None too) when neither matches - genuinely not disclosed,
    never guessed."""
    if not text:
        return None, None
    if specific_re is not None and specific_re.search(text):
        return True, high_score
    if generic_re is not None and generic_re.search(text):
        return False, mid_score
    return None, None


def classify_status(text, status_patterns):
    """`status_patterns` is an ordered list of (status_label, compiled_re)
    pairs, most-specific-first (mirrors
    regulatory_legal_scoring.classify_competition_investigation_status's
    ordered-check approach). Returns the first matching status_label, or
    None if nothing matches - never a default/fabricated status."""
    if not text:
        return None
    for status_label, pattern in status_patterns:
        if pattern.search(text):
            return status_label
    return None
