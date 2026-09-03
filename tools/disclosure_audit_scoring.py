"""
Section P - Accounting, disclosure & audit quality (qualitative).
Deterministic (no-LLM) scorers over Annual Report Notes/Audit Report text,
same pattern as tools.regulatory_legal_scoring (section J).

P1.1 Disclosure detail, P1.2 Timeliness/frequency, P2.1 RPT completeness,
P2.2 RPT explanation quality, P3.1 Audit opinion, P3.2 Emphasis of
matter/KAM, P3.3 Restatements, P4.1 Financial statement complexity,
P4.2 Multiple currencies, P4.3 Subsidiary complexity.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier, classify_status

_DISCLOSURE_DETAIL_RE = re.compile(r"notes\s+to\s+(?:the\s+)?(?:financial\s+)?(?:accounts|statements)|significant\s+accounting\s+policies", re.I)

_RPT_COMPLETE_RE = re.compile(r"related\s+party\s+(?:transactions?|disclosures?).{0,60}(?:nature\s+of\s+relationship|name\s+of\s+related\s+part)", re.I)
_RPT_GENERIC_RE = re.compile(r"related\s+party\s+(?:transactions?|disclosures?)", re.I)

_RPT_EXPLANATION_RE = re.compile(
    r"related\s+party\s+transactions?\s+(?:were\s+)?(?:carried\s+out|entered\s+into)\s+(?:in\s+)?(?:the\s+)?(?:ordinary\s+course|arm.s\s+length)|"
    # Real, common phrasing puts "during the financial year were on an
    # arm's length basis and were in the ordinary course" between
    # "entered into" and the actual qualifier - confirmed real on Prime
    # Fresh Limited: "...transactions entered into during the financial
    # year were on an arm's length basis and were in the ordinary course
    # of business...". Bounded to 80 chars so it can't bridge unrelated
    # sentences.
    r"related\s+party\s+transactions?\s+entered\s+into.{0,80}\b(?:ordinary\s+course|arm.s\s+length)",
    re.I,
)

_AUDIT_UNMODIFIED_RE = re.compile(r"unmodified\s+opinion|(?:in\s+our\s+opinion|present\s+fairly).{0,120}(?:give\s+a\s+true\s+and\s+fair\s+view)", re.I)
_AUDIT_QUALIFIED_RE = re.compile(r"qualified\s+opinion|except\s+for\s+the\s+(?:effects?\s+of|matters?)", re.I)
_AUDIT_ADVERSE_RE = re.compile(r"adverse\s+opinion", re.I)
_AUDIT_DISCLAIMER_RE = re.compile(r"disclaimer\s+of\s+opinion", re.I)

_KAM_RE = re.compile(r"key\s+audit\s+matters?|emphasis\s+of\s+matter|material\s+uncertainty", re.I)

_RESTATEMENT_RE = re.compile(
    r"restat\w+\s+(?:of\s+)?(?:prior\s+period|comparative)\s+(?:figures?|financial\s+statements?)|"
    # Real, common phrasing for a genuine restatement (Ind AS 8 prior-
    # period-error correction), just with "considering the effects of"/
    # similar prose sitting between "restated" and "prior period" -
    # confirmed real on Prime Fresh Limited: "ratios have been restated
    # considering the effects of prior period errors and omission...".
    # Bounded to 60 chars so it can't bridge two unrelated sentences.
    r"restat\w+.{0,60}prior\s+period\s+errors?", re.I,
)
_RESTATEMENT_NONE_RE = re.compile(r"no\s+(?:material\s+)?restatement", re.I)

_CURRENCY_COUNT_RE = re.compile(r"functional\s+currency\s+(?:is|of)\s+([A-Z]{3})", re.I)

_SUBSIDIARY_COUNT_RE = re.compile(r"(\d{1,3})\s+subsidiar(?:y|ies)|list\s+of\s+subsidiaries.{0,200}", re.I)


def score_disclosure_detail(text):
    if not text:
        return {"disclosed": None, "disclosure_quality_score": None}
    if _DISCLOSURE_DETAIL_RE.search(text):
        return {"disclosed": True, "disclosure_quality_score": 4}
    return {"disclosed": None, "disclosure_quality_score": None}


def score_disclosure_timeliness(filing_date, period_end_date):
    """P1.2 - Timeliness/frequency. Spec formula: Filing Date - Period End
    Date. Both dates must be independently known (not text-searched) - if
    either is unavailable this returns None, never guessed."""
    if not filing_date or not period_end_date:
        return {"days_to_file": None}
    return {"days_to_file": (filing_date - period_end_date).days}


def score_rpt_completeness(text):
    specific, score = score_evidence_tier(text, _RPT_COMPLETE_RE, _RPT_GENERIC_RE)
    return {"specific_disclosed": specific, "rpt_disclosure_completeness_score": score}


def score_rpt_explanation_quality(text):
    if not text:
        return {"disclosed": None, "rpt_explanation_score": None}
    if _RPT_EXPLANATION_RE.search(text):
        return {"disclosed": True, "rpt_explanation_score": 4}
    return {"disclosed": None, "rpt_explanation_score": None}


def classify_audit_opinion(text):
    status = classify_status(text, [
        ("Adverse", _AUDIT_ADVERSE_RE),
        ("Disclaimer", _AUDIT_DISCLAIMER_RE),
        ("Qualified", _AUDIT_QUALIFIED_RE),
        ("Unmodified", _AUDIT_UNMODIFIED_RE),
    ])
    return {"audit_opinion_status": status}


def score_emphasis_of_matter(text):
    if not text:
        return {"disclosed": None, "audit_attention_score": None}
    if _KAM_RE.search(text):
        return {"disclosed": True, "audit_attention_score": 3}
    return {"disclosed": None, "audit_attention_score": None}


def score_restatements(text):
    if not text:
        return {"restatement_disclosed": None, "restatement_score": None}
    if _RESTATEMENT_NONE_RE.search(text):
        return {"restatement_disclosed": False, "restatement_score": 5}
    if _RESTATEMENT_RE.search(text):
        return {"restatement_disclosed": True, "restatement_score": 2}
    return {"restatement_disclosed": None, "restatement_score": None}


def score_financial_statement_complexity(subsidiary_count, currency_count):
    """P4.1 - Financial statement complexity. Reuses the same raw counts
    computed for P4.2/P4.3 rather than re-deriving from text - the spec
    explicitly says structural complexity, not subjective text scanning."""
    if subsidiary_count is None and currency_count is None:
        return {"complexity_score": None}
    entities = (subsidiary_count or 0) + (currency_count or 1) - 1
    score = 5 if entities <= 2 else 4 if entities <= 5 else 3 if entities <= 10 else 2
    return {"complexity_score": score}


def score_multiple_currencies(text):
    if not text:
        return {"currency_count": None}
    currencies = set(m.upper() for m in _CURRENCY_COUNT_RE.findall(text))
    if not currencies:
        return {"currency_count": None}
    return {"currency_count": len(currencies), "currencies": sorted(currencies)}


def score_subsidiary_complexity(text, entities=None):
    """`entities` (optional) is the SAME named-entity list
    tools.group_structure_scoring.extract_group_entities already builds
    for C.4.2/C.4.3/C.4.4 (handles both the inline "Name (NN%)" format
    and the SEBI LODR annexure-caption format) - reused here instead of
    a second, narrower implementation. Most Annual Reports list named
    subsidiaries WITHOUT ever stating an explicit "the Company has N
    subsidiaries" sentence (the only thing `_SUBSIDIARY_COUNT_RE`'s
    primary branch could match) - counting the real named entities is
    the correct, generic count regardless of whether that summary
    sentence exists. The regex's own "list of subsidiaries..." fallback
    branch had no capture group at all, so it could never actually
    produce a usable count even when it matched - a real, separate bug,
    now superseded by the entities-based count."""
    if entities:
        return {"subsidiary_count": len(entities)}
    if not text:
        return {"subsidiary_count": None}
    m = _SUBSIDIARY_COUNT_RE.search(text)
    if m and m.group(1):
        return {"subsidiary_count": int(m.group(1))}
    return {"subsidiary_count": None}
