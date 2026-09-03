"""
C.6.1-C.6.4 - Auditor relationships. Deterministic (no-LLM) regex/
structural scorers over real, multi-year Annual Report text (the
Independent Auditor's Report's own signature block, opinion paragraph,
and Key Audit Matters / Emphasis of Matter sections). Generic Companies
Act / Standards on Auditing vocabulary, not ticker-specific.
"""

import re


def _band_score_pct(pct):
    if pct is None:
        return None
    if pct >= 80:
        return 5
    if pct >= 65:
        return 4
    if pct >= 50:
        return 3
    if pct >= 30:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Shared: auditor name extraction (the Auditor's Report signature block).
# ---------------------------------------------------------------------------

_AUDITOR_SIGNATURE = re.compile(
    # Literal capitalized "For" only (not re.I) - a case-insensitive match
    # would also fire on a lowercase "for" mid-sentence anywhere earlier in
    # the text, greedily swallowing everything up to the next "Chartered
    # Accountants" into the captured name.
    r"For\s+([A-Z][A-Za-z\s&'\.]{2,60}?(?:LLP|& Co\.?|& Associates|and Associates|and Co\.?))\s*\n?\s*Chartered Accountants"
)
# The "true and fair view" opinion is on the STANDALONE/CONSOLIDATED
# financial statements specifically - anchoring the signature search to
# the nearest one AFTER this phrase avoids picking up an unrelated
# Chartered Accountants signature elsewhere in the same excerpt window
# (e.g. a separate BRSR/sustainability assurance provider, which also
# signs "For <Firm> \n Chartered Accountants" but is not the statutory
# auditor).
_OPINION_ANCHOR = re.compile(r"in our opinion[^.]{0,300}?true and fair view", re.I)


def extract_auditor_name(text):
    """The Independent Auditor's Report's own signature block - "For
    <Firm Name>\\nChartered Accountants". The statutory auditor signs
    MULTIPLE sections of the same Annual Report (the opinion itself, the
    Internal Financial Controls annexure, sometimes a CARO annexure), so
    the most-frequently-appearing signed firm name in the excerpt window
    is a more reliable pick than the first match - which can land on an
    unrelated one-off signer (e.g. a separate BRSR/sustainability
    assurance provider, who also signs "For <Firm>\\nChartered
    Accountants" but only once). Returns the firm name (normalized
    whitespace) or None if not found."""
    if not text:
        return None
    matches = [re.sub(r"\s+", " ", m.group(1)).strip() for m in _AUDITOR_SIGNATURE.finditer(text)]
    if not matches:
        return None
    counts = {}
    for name in matches:
        counts[name] = counts.get(name, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# C.6.1 - Auditor tenure.
# ---------------------------------------------------------------------------

def score_auditor_tenure(years_auditors):
    """years_auditors: [{'fiscal_year', 'auditor_name'}] oldest->newest.
    Tenure = number of consecutive most-recent years (from the latest
    backward) with the SAME auditor firm name. Returns
    {'current_auditor','tenure_years','tenure_classification',
    'tenure_score'} or all-None if no auditor name was found in the
    latest year."""
    resolved = [y for y in (years_auditors or []) if y.get("auditor_name")]
    if not resolved:
        return {"current_auditor": None, "tenure_years": None, "tenure_classification": None, "tenure_score": None}
    current = resolved[-1]["auditor_name"]
    tenure = 0
    for y in reversed(resolved):
        if y["auditor_name"] == current:
            tenure += 1
        else:
            break
    if tenure >= 5:
        classification, score = "Long", 5
    elif tenure >= 3:
        classification, score = "Moderate", 4
    else:
        classification, score = "Short", 3
    return {"current_auditor": current, "tenure_years": tenure, "tenure_classification": classification, "tenure_score": score}


# ---------------------------------------------------------------------------
# C.6.2 - Auditor switches.
# ---------------------------------------------------------------------------

def score_auditor_switches(years_auditors):
    """years_auditors: [{'fiscal_year', 'auditor_name'}] oldest->newest.
    Counts year-over-year auditor-name changes across the available
    window (up to 5 years - a real, if shorter than the spec's 10-year
    ask, window; NSE Annual Report history beyond ~5 years isn't
    reliably available). Returns {'switch_count','years_covered',
    'switch_by_year','switch_score'} (higher score = fewer switches) or
    all-None if fewer than 2 years have a resolved auditor name."""
    resolved = [y for y in (years_auditors or []) if y.get("auditor_name")]
    if len(resolved) < 2:
        return {"switch_count": None, "years_covered": None, "switch_by_year": None, "switch_score": None}
    switch_by_year = []
    switches = 0
    for i in range(1, len(resolved)):
        changed = resolved[i]["auditor_name"] != resolved[i - 1]["auditor_name"]
        if changed:
            switches += 1
        switch_by_year.append({"fiscal_year": resolved[i]["fiscal_year"], "changed": changed})
    if switches == 0:
        score = 5
    elif switches == 1:
        score = 3
    else:
        score = 1
    return {"switch_count": switches, "years_covered": len(resolved), "switch_by_year": switch_by_year, "switch_score": score}


# ---------------------------------------------------------------------------
# C.6.3 - Qualifications in audit reports (opinion type).
# ---------------------------------------------------------------------------

# Standards on Auditing (SA 700/705) report section HEADINGS - a clean
# report's basis section is titled exactly "Basis for Opinion"; a modified
# report's is "Basis for Qualified/Adverse Opinion" or "Basis for
# Disclaimer of Opinion" instead. Anchoring to these exact headings (rather
# than a loose "in our opinion...true and fair view" phrase search, which
# also fires on unrelated Directors'-Responsibility/internal-controls
# boilerplate mentioning "true and fair view" elsewhere in the same
# report) is far more reliable.
_UNMODIFIED_MARKER = re.compile(r"basis for opinion\b", re.I)
_MODIFIED_MARKER = re.compile(
    r"basis for qualified opinion|basis for adverse opinion|basis for disclaimer of opinion|"
    r"\bqualified opinion\b|\badverse opinion\b|\bdisclaimer of opinion\b",
    re.I
)


def score_audit_opinion(opinion_text):
    """Classifies the Independent Auditor's Report's own opinion
    paragraph as Unmodified (clean "true and fair view" statement, no
    qualification language) or Modified (explicit qualified/adverse/
    disclaimer language). Returns {'opinion_type','audit_qualification_score'}
    or all-None if neither signal is found."""
    if not opinion_text:
        return {"opinion_type": None, "audit_qualification_score": None}
    if _MODIFIED_MARKER.search(opinion_text):
        return {"opinion_type": "Modified", "audit_qualification_score": 1}
    if _UNMODIFIED_MARKER.search(opinion_text):
        return {"opinion_type": "Unmodified", "audit_qualification_score": 5}
    return {"opinion_type": None, "audit_qualification_score": None}


# ---------------------------------------------------------------------------
# C.6.4 - Reservations / emphasis of matter.
# ---------------------------------------------------------------------------

_KAM_HEADING = re.compile(r"how (?:our audit|we) addressed the key audit matter", re.I)
_EOM_MARKER = re.compile(r"emphasis of matter|material uncertainty related to going concern", re.I)
# SA 701's own explicit "zero KAMs" outcome - the auditor determined there
# are none to communicate at all, so the per-matter "How our audit
# addressed..." subheading (which only exists to introduce each KAM one
# by one) never appears, not because the Key Audit Matters section itself
# is missing. Confirmed real on Prime Fresh Limited: "We have determined
# that there are no key audit matters to communicate in our report." -
# without this, a genuinely clean, explicit zero-KAM finding was treated
# identically to "the Auditor's Report text wasn't fetched at all."
_NO_KAM_RE = re.compile(r"(?:no|none)\s+key\s+audit\s+matters?\s+to\s+communicate", re.I)


def score_audit_observations(opinion_text):
    """Counts distinct Key Audit Matters (via the report's own "How our
    audit addressed the key audit matter(s)" subheading, one per KAM)
    and flags an explicit Emphasis of Matter / Material Uncertainty
    paragraph (a real, recurring-concern signal distinct from a routine
    KAM). Returns {'kam_count','has_emphasis_of_matter',
    'observation_classification','audit_observation_score'} - a genuine,
    explicit "no KAMs to communicate" finding scores as a real
    kam_count=0 (the cleanest possible outcome), never conflated with
    all-None, which is reserved for when the Independent Auditor's Report
    text itself isn't present (no KAM heading, no explicit zero-KAM
    statement, AND no EOM marker at all)."""
    if not opinion_text:
        return {"kam_count": None, "has_emphasis_of_matter": None, "observation_classification": None, "audit_observation_score": None}
    kam_count = len(_KAM_HEADING.findall(opinion_text))
    has_eom = bool(_EOM_MARKER.search(opinion_text))
    explicit_zero_kam = kam_count == 0 and bool(_NO_KAM_RE.search(opinion_text))
    if kam_count == 0 and not has_eom and not explicit_zero_kam:
        return {"kam_count": None, "has_emphasis_of_matter": None, "observation_classification": None, "audit_observation_score": None}
    if has_eom:
        classification, score = "Recurring Observation", 2
    else:
        classification, score = "No Material Observation", 5
    return {"kam_count": kam_count, "has_emphasis_of_matter": has_eom,
            "observation_classification": classification, "audit_observation_score": score}
