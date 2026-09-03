"""
Section R - Early-warning behavioural red flags. Deterministic (no-LLM)
scorers over Annual Report / Corporate Announcements text, same pattern
as tools.regulatory_legal_scoring (section J).

R1.1 Sudden departures, R1.2 Succession response, R2.1 Rapid insider
selling, R2.2 Concentrated block sales, R3.1 Capital raise frequency,
R3.2 Discount/pricing, R4.1 One-off transaction frequency,
R4.2 Transfer pricing/rationale, R5.1 Auditor resignation,
R5.2 Internal control issues, R6.1 Response cadence,
R6.2 Substance of response.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_SUDDEN_DEPARTURE_RE = re.compile(r"(?:resign(?:ed|ation)|ceased\s+to\s+be\s+a\s+director)\s+(?:with\s+)?(?:immediate\s+effect|effective\s+immediately)", re.I)
_DEPARTURE_GENERIC_RE = re.compile(r"resignation\s+of\s+(?:a\s+)?director|cessation\s+of\s+directorship", re.I)

_SUCCESSOR_NAMED_RE = re.compile(r"(?:appointed|named)\s+(?:as\s+)?(?:the\s+)?(?:new|successor)\s+(?:director|ceo|managing\s+director)", re.I)

_CAPITAL_RAISE_RE = re.compile(r"(?:rights\s+issue|qualified\s+institutions?\s+placement|qip|preferential\s+issue)\s+(?:of|for|raising)", re.I)
_CAPITAL_RAISE_GENERIC_RE = re.compile(r"rights\s+issue|preferential\s+(?:issue|allotment)|qip\b", re.I)

_DISCOUNT_PRICING_RE = re.compile(r"issue\s+price\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+(?:\.\d+)?\s+per\s+share", re.I)

_ONEOFF_TXN_RE = re.compile(r"(?:sale|disposal)\s+of\s+(?:an?\s+)?(?:asset|business|undertaking)\s+for\s+(?:inr|rs\.?|₹)?\s*[\d,]+", re.I)

_TRANSFER_PRICING_RE = re.compile(r"transfer\s+pricing\s+(?:study|report|documentation|rationale)", re.I)

_AUDITOR_RESIGNATION_RE = re.compile(r"auditor\s+(?:has\s+)?resigned|resignation\s+of\s+(?:the\s+)?(?:statutory\s+)?auditor", re.I)

_INTERNAL_CONTROL_ISSUE_RE = re.compile(r"material\s+weakness\s+in\s+internal\s+(?:financial\s+)?controls?|internal\s+control\s+(?:deficienc|weakness)", re.I)
_INTERNAL_CONTROL_ADEQUATE_RE = re.compile(r"internal\s+(?:financial\s+)?controls?\s+(?:are|were)\s+adequate", re.I)

_RESPONSE_CADENCE_RE = re.compile(r"(?:board|company)\s+(?:promptly\s+)?(?:responded|addressed)\s+(?:the\s+)?(?:matter|concern|issue)", re.I)
_RESPONSE_SUBSTANCE_RE = re.compile(r"(?:remedial|corrective)\s+(?:action|measures?)\s+(?:plan\s+)?(?:were\s+)?(?:implemented|taken)", re.I)


def score_sudden_departures(text):
    specific, score = score_evidence_tier(text, _SUDDEN_DEPARTURE_RE, _DEPARTURE_GENERIC_RE, high_score=2, mid_score=3)
    return {"disclosed": specific, "departure_risk_score": score}


def score_succession_response(text):
    if not text:
        return {"successor_named": None, "succession_coverage": None}
    if _SUCCESSOR_NAMED_RE.search(text):
        return {"successor_named": True, "succession_coverage": 1.0}
    return {"successor_named": None, "succession_coverage": None}


def score_rapid_insider_selling(sell_events_within_window):
    """R2.1 - Rapid insider selling. Reuses the same structured Regulation
    7(2) transaction list D.1.x already fetches (tools.
    insider_trading_scraper.fetch_insider_trades) - never re-derived from
    free text, since the spec requires actual transaction dates."""
    if sell_events_within_window is None:
        return {"rapid_selling_flag": None}
    return {"rapid_selling_flag": "Present" if sell_events_within_window >= 2 else "None"}


def score_concentrated_block_sales(largest_sale_value, total_sales_value):
    if not largest_sale_value or not total_sales_value:
        return {"block_sale_concentration_pct": None}
    return {"block_sale_concentration_pct": round(largest_sale_value / total_sales_value * 100, 2)}


def score_capital_raise_frequency(text):
    specific, score = score_evidence_tier(text, _CAPITAL_RAISE_RE, _CAPITAL_RAISE_GENERIC_RE)
    return {"event_disclosed": specific, "capital_raise_frequency_score": score}


def score_discount_pricing(text):
    if not text:
        return {"price_disclosed": None, "pricing_score": None}
    if _DISCOUNT_PRICING_RE.search(text):
        return {"price_disclosed": True, "pricing_score": 4}
    return {"price_disclosed": None, "pricing_score": None}


def score_oneoff_transaction_frequency(text):
    if not text:
        return {"disclosed": None, "oneoff_frequency_score": None}
    if _ONEOFF_TXN_RE.search(text):
        return {"disclosed": True, "oneoff_frequency_score": 3}
    return {"disclosed": None, "oneoff_frequency_score": None}


def score_transfer_pricing_rationale(text):
    if not text:
        return {"disclosed": None, "transaction_rationale_score": None}
    if _TRANSFER_PRICING_RE.search(text):
        return {"disclosed": True, "transaction_rationale_score": 4}
    return {"disclosed": None, "transaction_rationale_score": None}


def score_auditor_resignation(text):
    if not text:
        return {"resignation_flag": None}
    if _AUDITOR_RESIGNATION_RE.search(text):
        return {"resignation_flag": "Recent"}
    return {"resignation_flag": None}


def score_internal_control_issues(text):
    if not text:
        return {"issue_disclosed": None, "control_issue_score": None}
    if _INTERNAL_CONTROL_ADEQUATE_RE.search(text):
        return {"issue_disclosed": False, "control_issue_score": 5}
    if _INTERNAL_CONTROL_ISSUE_RE.search(text):
        return {"issue_disclosed": True, "control_issue_score": 2}
    return {"issue_disclosed": None, "control_issue_score": None}


def score_response_cadence(text):
    if not text:
        return {"disclosed": None, "response_cadence_score": None}
    if _RESPONSE_CADENCE_RE.search(text):
        return {"disclosed": True, "response_cadence_score": 4}
    return {"disclosed": None, "response_cadence_score": None}


def score_response_substance(text):
    if not text:
        return {"disclosed": None, "response_substance_score": None}
    if _RESPONSE_SUBSTANCE_RE.search(text):
        return {"disclosed": True, "response_substance_score": 4}
    return {"disclosed": None, "response_substance_score": None}
