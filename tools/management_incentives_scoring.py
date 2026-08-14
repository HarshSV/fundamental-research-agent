"""
B.2.1-B.2.4 — Management incentives: deterministic (no-LLM) scorers.

Same design as tools/founder_track_record_scoring.py (B.1) and
tools/moat_brand_scoring.py (A.2.A): regex/keyword pattern matching against
real Annual Report text only, no LLM call. Every number traces to a
literal matched figure in the source text - a value is only ever computed
from a real disclosed figure, never guessed or interpolated.
"""

import re

_NUM = r"\d[\d,]*\.?\d*"


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _band_score_pct(pct):
    """Shared 0-100% -> 1-5 banding (>=80=5, 65-79=4, 50-64=3, 30-49=2,
    <30=1), same thresholds as B.1's spec-given bands - used here as a
    reasonable default where the B.2 spec asks for a 1-5 score but doesn't
    give explicit thresholds of its own."""
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
# B.2.1 - Pay structure: Fixed vs Variable Compensation Mix
# ---------------------------------------------------------------------------

_FIXED_LABEL = re.compile(r"\bfixed\b[^.\n]{0,40}?\b(?:commission|pay|salary|remuneration|compensation)\b", re.I)
_VARIABLE_LABEL = re.compile(r"\b(?:variable|performance[- ]linked)\b[^.\n]{0,40}?\b(?:commission|pay|bonus|remuneration|incentive|compensation)\b", re.I)
_NUM_NEAR = re.compile(_NUM)


def _first_number_after(text, pos, max_chars=150):
    """Returns (value, absolute_start_pos) for the first number found, or
    None. The absolute position lets the caller dedupe two labels that
    both happen to point at the SAME figure (e.g. a column header "Fixed
    Commission" immediately followed by a row label "Base Fixed Commission
    ... 25.00" - both match the label pattern but there's only one real
    number between them, which must not be counted twice)."""
    window = text[pos:pos + max_chars]
    m = _NUM_NEAR.search(window)
    if not m:
        return None
    # Reject a "N." immediately followed by a newline+capital letter - a
    # numbered-list marker (e.g. "1.\nNext Item"), not a real amount. A
    # genuine amount is never followed by a fresh capitalized line right
    # after its own decimal point with nothing else on that line.
    tail = window[m.end():m.end() + 3]
    if re.match(r"\.\s*\n[A-Z]", tail) or re.match(r"\.\s*\n[A-Z]", window[m.end() - 1:m.end() + 3]):
        return None
    v = _to_float(m.group(0))
    if v is None:
        return None
    return v, pos + m.start()


def extract_pay_mix(text):
    """Finds every explicit "Fixed <Commission/Pay/Salary>" and "Variable/
    Performance-linked <Commission/Pay/Bonus>" label in `text` and takes the
    first real amount figure following each (a label sits on its own line
    in PDF-linearized tables, with the number a short distance below/after
    it - not necessarily the same sentence). Sums each bucket separately.
    Returns {'fixed_amount','variable_amount','fixed_pct'} or all-None if
    no explicit fixed/variable component amount was found."""
    if not text:
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    fixed_total, variable_total = 0.0, 0.0
    fixed_found, variable_found = False, False
    seen_positions = set()
    for m in _FIXED_LABEL.finditer(text):
        r = _first_number_after(text, m.end())
        if r is not None and r[1] not in seen_positions:
            fixed_total += r[0]
            fixed_found = True
            seen_positions.add(r[1])
    for m in _VARIABLE_LABEL.finditer(text):
        r = _first_number_after(text, m.end())
        if r is not None and r[1] not in seen_positions:
            variable_total += r[0]
            variable_found = True
            seen_positions.add(r[1])
    if not (fixed_found and variable_found):
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    total = fixed_total + variable_total
    if total <= 0:
        return {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    return {
        "fixed_amount": round(fixed_total, 2), "variable_amount": round(variable_total, 2),
        "fixed_pct": round(100 * fixed_total / total, 1),
    }


# ---------------------------------------------------------------------------
# B.2.2 - Equity ownership: Management Ownership Score
# ---------------------------------------------------------------------------

# A row naming a Director/KMP with an explicit "% of total shares"/"% of
# paid-up capital" figure nearby - summed across all such rows found.
_PCT_OF_SHARES = re.compile(rf"({_NUM})\s*%\s*(?:of\s+(?:total|paid[- ]up)\s+(?:shares|equity|capital))", re.I)
_DIRECTOR_KMP_ROLE = re.compile(r"\b(?:Director|KMP|Key Managerial Personnel|Chief Executive|Chief Financial|Managing Director|Executive Director|Company Secretary)\b", re.I)


def score_equity_ownership(shareholding_text):
    """Sums every explicit "X% of total/paid-up shares" figure that appears
    within 200 chars of a Director/KMP role mention in `shareholding_text`
    - a promoter-group holding table (parent company, unrelated to
    individual directors) is NOT what this counts; only rows tied to a
    named director/KMP role. Management Ownership Score (1-5) bands the
    summed % using this codebase's own thresholds (no explicit band given
    in the spec for this sub-point): >=5%=5, 2-5%=4, 1-2%=3, 0.1-1%=2,
    <0.1%=1. Returns {'management_ownership_pct','ownership_score'} or
    all-None if no such figure was found."""
    if not shareholding_text:
        return {"management_ownership_pct": None, "ownership_score": None}
    total_pct = 0.0
    found = False
    for m in _PCT_OF_SHARES.finditer(shareholding_text):
        window = shareholding_text[max(0, m.start() - 200):m.start()]
        if _DIRECTOR_KMP_ROLE.search(window):
            v = _to_float(m.group(1))
            if v is not None and 0 <= v <= 100:
                total_pct += v
                found = True
    if not found:
        return {"management_ownership_pct": None, "ownership_score": None}
    total_pct = round(min(total_pct, 100.0), 2)
    score = 5 if total_pct >= 5 else 4 if total_pct >= 2 else 3 if total_pct >= 1 else 2 if total_pct >= 0.1 else 1
    return {"management_ownership_pct": total_pct, "ownership_score": score}


# ---------------------------------------------------------------------------
# B.2.3 - Vesting structure: Long-term Incentive Score
# ---------------------------------------------------------------------------

_VESTED_LABEL = re.compile(r"\b(?:already\s+)?vested\b(?!\s+in)", re.I)
_UNVESTED_LABEL = re.compile(r"\b(?:un[- ]?vested|yet\s+to\s+vest|not\s+yet\s+vested)\b", re.I)


def _first_count_after(text, pos, max_chars=100):
    window = text[pos:pos + max_chars]
    m = _NUM_NEAR.search(window)
    if not m:
        return None
    v = _to_float(m.group(0))
    return v if v is not None and v >= 1 else None


def score_vesting_structure(esop_text):
    """Finds every explicit "vested"/"unvested" option-COUNT figure in
    `esop_text` (a label sits near its count in an ESOP disclosure table).
    Long-term Incentive Score (1-5) is banded on the UNVESTED share of
    total options found - a higher unvested proportion means more of the
    incentive still depends on future service/performance, i.e. more
    forward-looking retention pull (this scoring DIRECTION is this
    engine's own documented interpretation - the spec doesn't state one).
    Returns {'vested_count','unvested_count','unvested_pct',
    'vesting_score'} or all-None if no explicit vested/unvested count was
    found."""
    if not esop_text:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    vested_total, unvested_total = 0.0, 0.0
    vested_found, unvested_found = False, False
    for m in _UNVESTED_LABEL.finditer(esop_text):
        v = _first_count_after(esop_text, m.end())
        if v is not None:
            unvested_total += v
            unvested_found = True
    for m in _VESTED_LABEL.finditer(esop_text):
        # Skip a match that's actually part of an "unvested" token (the
        # unvested pattern already consumed those; this guards the rare
        # case the two patterns' spans could otherwise double-count).
        if esop_text[max(0, m.start() - 3):m.start()].lower().endswith(("un", "un-", "un ")):
            continue
        v = _first_count_after(esop_text, m.end())
        if v is not None:
            vested_total += v
            vested_found = True
    if not (vested_found and unvested_found):
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    total = vested_total + unvested_total
    if total <= 0:
        return {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    unvested_pct = round(100 * unvested_total / total, 1)
    return {
        "vested_count": round(vested_total), "unvested_count": round(unvested_total),
        "unvested_pct": unvested_pct, "vesting_score": _band_score_pct(unvested_pct),
    }


# ---------------------------------------------------------------------------
# B.2.4 - Long-term orientation: Long-term vs Short-term Incentives
# ---------------------------------------------------------------------------

_LONG_TERM_KEYWORDS = re.compile(
    r"\blong[- ]term incentive\b|\bLTIP\b|\bstock option\b|\bESOP\b|\bperformance share\b|"
    r"\bdeferred (?:bonus|pay|compensation)\b|\bmulti[- ]year vesting\b|\brestricted stock\b", re.I
)
_SHORT_TERM_KEYWORDS = re.compile(
    r"\bshort[- ]term incentive\b|\bSTI\b|\bannual bonus\b|\bcash bonus\b|"
    r"\bannual performance (?:pay|bonus)\b|\bannual incentive\b", re.I
)


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def score_long_term_orientation(policy_text):
    """Classifies each sentence of `policy_text` (Remuneration Policy)
    mentioning a long-term-incentive keyword (LTIP/ESOP/stock options/
    deferred pay/performance shares) vs a short-term-incentive keyword
    (annual bonus/STI/cash bonus) - a sentence naming both is counted in
    both buckets (deliberately, since the policy is genuinely describing
    a mix in that sentence). Long-term Alignment Score (1-5) bands the
    long-term share of total tagged sentences. Returns
    {'long_term_count','short_term_count','long_term_pct',
    'alignment_score'} or all-None if the policy text names neither."""
    if not policy_text:
        return {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None}
    long_n, short_n = 0, 0
    for sent in _sentences(policy_text):
        if _LONG_TERM_KEYWORDS.search(sent):
            long_n += 1
        if _SHORT_TERM_KEYWORDS.search(sent):
            short_n += 1
    total = long_n + short_n
    if total == 0:
        return {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None}
    pct = round(100 * long_n / total, 1)
    return {
        "long_term_count": long_n, "short_term_count": short_n,
        "long_term_pct": pct, "alignment_score": _band_score_pct(pct),
    }
