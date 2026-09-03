"""
Section L - Financial policy & capital structure behavior. Deterministic
(no-LLM) scorers over Annual Report MD&A / Notes text, same pattern as
tools.regulatory_legal_scoring (section J).

L1.1 Leverage policy, L1.2 Covenant management, L2.1 Refinancing history,
L2.2 Covenant breaches/remedies, L3.1 Dividend consistency, L3.2 Rationale
for changes, L4.1 Lease commitments, L4.2 Structured/off-balance-sheet
arrangements.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier, classify_status

_LEVERAGE_POLICY_SPECIFIC_RE = re.compile(
    r"(?:target|maintain)\w*\s+(?:a\s+)?debt[- ]to[- ]equity\s+(?:ratio\s+)?(?:of|below|under)\s+\d+(?:\.\d+)?|"
    r"net\s+debt\s*/\s*ebitda\s+(?:of|below|under|target)\s+\d+(?:\.\d+)?",
    re.I,
)
_LEVERAGE_POLICY_GENERIC_RE = re.compile(
    r"prudent\s+(?:leverage|debt)\s+(?:policy|management)|conservative\s+capital\s+structure|"
    # Ind AS 1's own mandated Capital Management note boilerplate
    # ("The Company monitors capital using Debt-Equity ratio...") is a
    # real, universal disclosure of HOW leverage is monitored, just
    # without a specific numeric target - confirmed real on Prime Fresh
    # Limited. A genuine mid-tier (not "specific target") signal, not an
    # absence of any leverage-policy disclosure at all.
    r"monitors?\s+(?:its\s+|the\s+)?capital\s+using\s+(?:the\s+)?debt[- ]equity",
    re.I,
)

_COVENANT_COMPLIANT_RE = re.compile(r"(?:in\s+)?compliance\s+with\s+(?:all\s+)?(?:financial\s+)?covenants?|covenant\s+headroom", re.I)
_COVENANT_BREACH_RE = re.compile(r"covenant\s+(?:breach|default|violation)|breach\s+of\s+(?:financial\s+)?covenant", re.I)

_REFINANCE_EVENT_RE = re.compile(r"refinanc\w+\s+(?:of|the)\s+(?:existing\s+)?(?:debt|loan|facility|borrowings?)", re.I)
_REFINANCE_GENERIC_RE = re.compile(r"refinanc\w+", re.I)

_COVENANT_BREACH_STATUS_RE = re.compile(r"covenant\s+(?:breach|default)\s+(?:was\s+)?(?:remedied|waived|cured)|waiver\s+(?:was\s+)?obtained", re.I)
_COVENANT_HISTORICAL_RE = re.compile(r"covenant\s+(?:breach|default)", re.I)

_DIVIDEND_CONSISTENT_RE = re.compile(r"consistent(?:ly)?\s+(?:paid|declared)\s+dividends?|uninterrupted\s+dividend|dividend\s+(?:every|each)\s+year", re.I)
# "No Dividend was declared...because the Company retains its earnings for
# future growth" is a real, common, EXPLICIT dividend disclosure (a
# deliberate no-payout-for-growth policy) - confirmed missing on Prime
# Fresh Limited: the direct-adjacency `dividend\s+declared` pattern never
# matched "Dividend WAS declared" (the standard Companies Act 2013 Board's
# Report phrasing always inserts "was"/"is"/"has been" between the two
# words), silently treating an explicit "no dividend" answer identically
# to "topic never addressed at all".
_DIVIDEND_GENERIC_RE = re.compile(
    r"dividend\s+(?:policy|payout)|"
    r"dividend\s+(?:was|is|has\s+been)?\s*(?:declared|recommended|paid)|"
    r"no\s+dividend\s+(?:was|is|has\s+been)?\s*(?:declared|recommended|paid)", re.I,
)

_DIVIDEND_RATIONALE_RE = re.compile(r"dividend\s+(?:policy|payout)\s+(?:is\s+)?(?:based\s+on|linked\s+to|guided\s+by)", re.I)

_LEASE_PCT_RE = re.compile(
    r"lease\s+liabilit(?:y|ies)\s+of\s+(?:inr|rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)|"
    r"right[- ]of[- ]use\s+asset",
    re.I,
)
_LEASE_GENERIC_RE = re.compile(r"lease\s+(?:liabilit|commitment|obligation)", re.I)

_STRUCTURED_ARRANGEMENT_RE = re.compile(r"securitisation|securitization|structured\s+finance|off[- ]balance[- ]sheet\s+(?:arrangement|financing)", re.I)
_STRUCTURED_NONE_RE = re.compile(r"no\s+(?:material\s+)?off[- ]balance[- ]sheet\s+(?:arrangements?|financing)", re.I)


def score_leverage_policy(text):
    specific, score = score_evidence_tier(text, _LEVERAGE_POLICY_SPECIFIC_RE, _LEVERAGE_POLICY_GENERIC_RE)
    return {"specific_target_disclosed": specific, "leverage_trend_score": score}


def score_covenant_management(text):
    if not text:
        return {"covenant_status": None, "covenant_score": None}
    if _COVENANT_BREACH_RE.search(text):
        return {"covenant_status": "breach", "covenant_score": 2}
    if _COVENANT_COMPLIANT_RE.search(text):
        return {"covenant_status": "compliant", "covenant_score": 4}
    return {"covenant_status": None, "covenant_score": None}


def score_refinancing_history(text):
    specific, score = score_evidence_tier(text, _REFINANCE_EVENT_RE, _REFINANCE_GENERIC_RE)
    return {"event_disclosed": specific, "refinancing_history_score": score}


def classify_covenant_breach_status(text):
    status = classify_status(text, [
        ("Historical", _COVENANT_BREACH_STATUS_RE),
        ("Recent", _COVENANT_HISTORICAL_RE),
    ])
    return {"breach_status": status}


def score_dividend_consistency(text):
    specific, score = score_evidence_tier(text, _DIVIDEND_CONSISTENT_RE, _DIVIDEND_GENERIC_RE)
    return {"consistency_disclosed": specific, "dividend_consistency_score": score}


def score_dividend_rationale(text):
    if not text:
        return {"rationale_disclosed": None, "policy_rationale_score": None}
    if _DIVIDEND_RATIONALE_RE.search(text):
        return {"rationale_disclosed": True, "policy_rationale_score": 4}
    return {"rationale_disclosed": None, "policy_rationale_score": None}


def score_lease_commitments(text):
    specific, score = score_evidence_tier(text, _LEASE_PCT_RE, _LEASE_GENERIC_RE)
    return {"specific_disclosed": specific, "lease_exposure_score": score}


def score_structured_arrangements(text):
    if not text:
        return {"structured_arrangement_disclosed": None, "off_balance_sheet_risk_score": None}
    if _STRUCTURED_NONE_RE.search(text):
        return {"structured_arrangement_disclosed": False, "off_balance_sheet_risk_score": 5}
    if _STRUCTURED_ARRANGEMENT_RE.search(text):
        return {"structured_arrangement_disclosed": True, "off_balance_sheet_risk_score": 3}
    return {"structured_arrangement_disclosed": None, "off_balance_sheet_risk_score": None}
