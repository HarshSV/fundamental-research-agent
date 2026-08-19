"""
E.6.1 - Off-market transactions, non-arm's length contracts, side-
letters or sweetheart deals. Deterministic (no-LLM) scorer over real
NSE Corporate Announcements + Annual Report Notes to Accounts text.
Generic keyword/regex logic, not ticker-specific.

E.6.2 (non-arm's-length contracts) has no separate scoring module here
- it reuses tools.rpt_leakage_scoring.score_payment_rationale directly
(the same real arm's-length/Audit-Committee-approval signal already
built for E.1.3, over the same Related Party Disclosures note text),
since the spec's own sourcing path for E.6.2 ("Related Party
Disclosures - contractual terms, pricing basis and approval") is
identical to E.1.3's.
"""
import re

_OFF_MARKET_KEYWORD = re.compile(
    r"off[- ]market\b|inter[- ]se transfer|block deal|bulk deal|"
    r"preferential (?:issue|allotment)|negotiated (?:deal|transaction)",
    re.I,
)
# A real counterparty name near the match - a capitalized multi-word
# entity ending in a common corporate suffix, or "Mr/Ms/Mrs <Name>" for
# an individual, or "promoter" explicitly named.
_NAMED_COUNTERPARTY = re.compile(
    r"\b(?:[A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,4}\s+(?:Private\s+)?(?:Limited|Ltd\.?|LLP))\b|"
    r"\b(?:Mr|Ms|Mrs)\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?\b|"
    r"\bpromoter(?:s)?(?:\s+group)?\b",
    re.I,
)
_RATIONALE_MARKER = re.compile(
    r"\bpursuant to\b|\bconsideration\b|\bpurpose of\b|\bin order to\b|"
    r"\bfor the purpose\b|\bcommercial rationale\b|\bstrategic\b", re.I,
)
# Audit Committee charter/terms-of-reference boilerplate enumerates
# "public issue, rights issue, preferential issue, etc." as EXAMPLE
# issue types the committee generically reviews - not a real,
# specific preferential-issue/off-market event that occurred this
# year. Confirmed real false positive on SUZLON: "...reviewing...the
# statement of uses/application of funds raised through an issue
# (public issue, rights issue, preferential issue, etc.)..." - same
# class of boilerplate already guarded against for D.5/E.1.
_GOVERNANCE_BOILERPLATE = re.compile(
    # Two real separator styles confirmed on the SAME company (SUZLON):
    # comma-separated ("public issue, rights issue, preferential
    # issue, etc.") and "or"-separated ("public issue or rights issue
    # or preferential issue or qualified institutions placement") -
    # both are the identical Audit Committee terms-of-reference
    # enumeration, just worded differently.
    r"public issue\s*(?:,|or)\s*rights issue\s*(?:,|or)\s*preferential issue|"
    r"statement of uses\s*/?\s*application of funds|"
    r"reviewing,?\s*with the management|terms of reference|"
    r"monitoring agency monitoring the utilisation", re.I,
)


def classify_off_market_announcements(announcements):
    """Scans real NSE Corporate Announcements (as returned by
    tools.nse_announcements.fetch_announcements) for off-market
    transfer/block-deal/bulk-deal/preferential-issue/inter-se-transfer
    language. Returns a list of real matched rows
    {'desc','an_dt','evidence','has_named_counterparty','has_rationale'},
    never a guess at ones that don't literally match."""
    out = []
    for row in announcements or []:
        text = f"{row.get('desc') or ''} {row.get('attchmntText') or ''}"
        if not text.strip() or not _OFF_MARKET_KEYWORD.search(text):
            continue
        if _GOVERNANCE_BOILERPLATE.search(text):
            continue
        out.append({
            "desc": row.get("desc"), "an_dt": row.get("an_dt"),
            "evidence": text.strip()[:300],
            "has_named_counterparty": bool(_NAMED_COUNTERPARTY.search(text)),
            "has_rationale": bool(_RATIONALE_MARKER.search(text)),
        })
    return out


def score_off_market_transactions(announcement_matches, rpt_text=None):
    """E.6.1 - Transaction Risk Score (1-5) based on disclosure,
    counterparty and commercial rationale. A real off-market/block-deal
    disclosure that names its counterparty AND states a commercial
    rationale scores highest (well-disclosed, judgeable); one that
    discloses the transaction but omits counterparty or rationale
    scores lower (real, but opaque); no disclosure at all is genuinely
    unavailable - the ABSENCE of an off-market transaction disclosure
    is not itself evidence of anything (most companies simply never
    have one), so this returns all-None rather than a fabricated
    "clean" score. Also checks the Related Party Disclosures note text
    (rpt_text) for the same off-market keywords, since some off-market
    transfers are disclosed there instead of/alongside a standalone
    announcement. Returns {'transaction_count','named_counterparty_count',
    'rationale_disclosed_count','risk_score'} or all-None."""
    matches = list(announcement_matches or [])
    if rpt_text:
        for m in _OFF_MARKET_KEYWORD.finditer(rpt_text):
            window = rpt_text[max(0, m.start() - 200):m.end() + 200]
            if _GOVERNANCE_BOILERPLATE.search(window):
                continue
            matches.append({
                "desc": "Related Party Disclosures note", "an_dt": None,
                "evidence": window[:300],
                "has_named_counterparty": bool(_NAMED_COUNTERPARTY.search(window)),
                "has_rationale": bool(_RATIONALE_MARKER.search(window)),
            })
            break
    if not matches:
        return {"transaction_count": None, "named_counterparty_count": None, "rationale_disclosed_count": None, "risk_score": None}
    named_count = sum(1 for m in matches if m["has_named_counterparty"])
    rationale_count = sum(1 for m in matches if m["has_rationale"])
    if named_count == len(matches) and rationale_count == len(matches):
        score = 5
    elif named_count > 0 and rationale_count > 0:
        score = 4
    elif named_count > 0 or rationale_count > 0:
        score = 3
    else:
        score = 2
    return {
        "transaction_count": len(matches), "named_counterparty_count": named_count,
        "rationale_disclosed_count": rationale_count, "risk_score": score,
    }
