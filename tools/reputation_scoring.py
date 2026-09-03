"""
Section O - Reputational & media signals. Deterministic (no-LLM) scorers
over Annual Report / Corporate Announcements text, same pattern as
tools.regulatory_legal_scoring (section J).

O1.1 Material controversies, O1.2 Stakeholder complaints, O2.2 Safety
incidents, O2.3 Negative campaigns/reputation response, O3.1 Regulatory
fines, O3.2 Public investigations.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier, classify_status

_CONTROVERSY_RE = re.compile(r"controvers(?:y|ies)|public\s+backlash|media\s+scrutiny", re.I)
_CONTROVERSY_NONE_RE = re.compile(r"no\s+(?:material\s+)?controvers(?:y|ies)", re.I)

_COMPLAINT_RESOLVED_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:investor|shareholder|stakeholder)\s+complaints?\s+(?:were\s+)?resolved|"
    r"all\s+(?:investor|shareholder)\s+complaints?\s+(?:were\s+)?resolved",
    re.I,
)
# SEBI LODR Schedule V Part C's own mandated three-line disclosure
# ("Number of complaints filed.../disposed.../pending...") - a genuine
# NIL across all three is the cleanest possible real answer (nothing was
# ever filed, so nothing needed resolving), not an absence of data.
# Confirmed real on Prime Fresh Limited.
_COMPLAINT_NIL_RE = re.compile(
    r"complaints?\s+(?:filed|received)[^.]{0,60}:\s*nil.{0,200}?"
    r"complaints?\s+(?:disposed|resolved)[^.]{0,60}:\s*nil.{0,200}?"
    r"complaints?\s+pending[^.]{0,60}:\s*nil", re.I,
)

_SAFETY_INCIDENT_RE = re.compile(r"(?:fatal|lost[- ]time)\s+(?:accident|incident)|safety\s+incident", re.I)
_SAFETY_NONE_RE = re.compile(r"zero\s+(?:fatal|lost[- ]time)\s+(?:accident|incident)|no\s+(?:material\s+)?safety\s+incident", re.I)

_NEGATIVE_CAMPAIGN_RE = re.compile(r"product\s+recall|negative\s+(?:campaign|publicity)", re.I)
_REPUTATION_RESPONSE_RE = re.compile(r"(?:corrective|remedial)\s+(?:action|measures?)\s+(?:were\s+)?(?:taken|implemented)", re.I)

_FINE_QUANTIFIED_RE = re.compile(
    r"(?:fine|penalty)\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+(?:\.\d+)?\s*(?:crore|lakh|million)?\s+"
    r"(?:was\s+)?imposed",
    re.I,
)
_FINE_GENERIC_RE = re.compile(r"regulatory\s+fine|penalty\s+imposed", re.I)

_INVESTIGATION_ORDER_RE = re.compile(r"order\s+(?:was\s+)?passed\s+by\s+(?:the\s+)?regulator|regulatory\s+order", re.I)
_INVESTIGATION_ACTIVE_RE = re.compile(r"under\s+investigation\s+by\s+(?:the\s+)?regulator|regulatory\s+(?:inquiry|investigation)", re.I)
_INVESTIGATION_NONE_RE = re.compile(r"no\s+(?:material\s+)?(?:regulatory\s+)?(?:inquiry|investigation)", re.I)


def score_material_controversies(text):
    if not text:
        return {"disclosed": None, "controversy_score": None}
    if _CONTROVERSY_NONE_RE.search(text):
        return {"disclosed": False, "controversy_score": 5}
    if _CONTROVERSY_RE.search(text):
        return {"disclosed": True, "controversy_score": 2}
    return {"disclosed": None, "controversy_score": None}


def score_stakeholder_complaints(text):
    if not text:
        return {"resolution_rate_pct": None, "complaint_resolution_score": None}
    m = _COMPLAINT_RESOLVED_RE.search(text)
    if m:
        pct = float(m.group(1)) if m.group(1) else 100.0
        score = 5 if pct >= 95 else 4 if pct >= 80 else 3
        return {"resolution_rate_pct": pct, "complaint_resolution_score": score}
    if _COMPLAINT_NIL_RE.search(text):
        return {"resolution_rate_pct": None, "complaint_resolution_score": 5}
    return {"resolution_rate_pct": None, "complaint_resolution_score": None}


def score_safety_incidents(text):
    if not text:
        return {"incident_disclosed": None, "safety_incident_score": None}
    if _SAFETY_NONE_RE.search(text):
        return {"incident_disclosed": False, "safety_incident_score": 5}
    if _SAFETY_INCIDENT_RE.search(text):
        return {"incident_disclosed": True, "safety_incident_score": 2}
    return {"incident_disclosed": None, "safety_incident_score": None}


def score_reputation_response(text):
    if not text or not _NEGATIVE_CAMPAIGN_RE.search(text):
        return {"campaign_disclosed": None, "reputation_response_score": None}
    if _REPUTATION_RESPONSE_RE.search(text):
        return {"campaign_disclosed": True, "reputation_response_score": 4}
    return {"campaign_disclosed": True, "reputation_response_score": 2}


def score_regulatory_fines(text):
    specific, score = score_evidence_tier(text, _FINE_QUANTIFIED_RE, _FINE_GENERIC_RE)
    return {"quantified": specific, "fine_frequency_score": score}


def classify_public_investigation_status(text):
    status = classify_status(text, [
        ("Order", _INVESTIGATION_ORDER_RE),
        ("Investigation", _INVESTIGATION_ACTIVE_RE),
        ("None", _INVESTIGATION_NONE_RE),
    ])
    return {"investigation_status": status}
