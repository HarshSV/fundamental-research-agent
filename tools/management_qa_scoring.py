"""
Section U - Questions to ask management (qualitative prompts).
Deterministic (no-LLM) scorers over Earnings Call Transcript / Investor
Presentation / Annual Report MD&A text (where management's own stated
view is captured), same pattern as tools.regulatory_legal_scoring
(section J). These score whether management has PUBLICLY, EXPLICITLY
addressed the question already (in a transcript/AR), not a live Q&A -
this workflow has no way to ask management anything new.

U1.1 Top management-identified risk, U2.1 Capital allocation framework,
U3.1 Management-named competitors, U4.1/U4.2 Revenue/margin sensitivity,
U5.1 Management explanation of material RPTs, U6.1/U6.2 CEO/CFO
succession.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_TOP_RISK_RE = re.compile(r"(?:our|the)\s+(?:key|principal|top|biggest)\s+risks?\s+(?:is|are|include)", re.I)

_CAPITAL_ALLOCATION_RE = re.compile(r"capital\s+allocation\s+(?:framework|priorit(?:y|ies)|policy)", re.I)

_NAMED_COMPETITORS_RE = re.compile(r"(?:our\s+)?(?:key\s+)?competitors?\s+(?:include|are)\s+[A-Z][\w&\s,]{2,80}", re.I)

_REVENUE_SENSITIVITY_RE = re.compile(r"revenue\s+(?:is\s+)?sensitive\s+to|key\s+revenue\s+risks?\s+(?:include|are)", re.I)
_MARGIN_SENSITIVITY_RE = re.compile(r"margin\s+(?:is\s+)?sensitive\s+to|key\s+margin\s+risks?\s+(?:include|are)", re.I)

_RPT_EXPLANATION_MGMT_RE = re.compile(r"(?:management|the\s+board)\s+(?:has\s+)?explained\s+(?:the\s+)?related\s+party\s+transaction", re.I)

_CEO_SUCCESSION_RE = re.compile(r"ceo\s+succession\s+(?:plan|planning)|succession\s+plan\s+for\s+(?:the\s+)?(?:chief\s+executive|ceo)", re.I)
_CFO_SUCCESSION_RE = re.compile(r"cfo\s+succession\s+(?:plan|planning)|succession\s+plan\s+for\s+(?:the\s+)?(?:chief\s+financial\s+officer|cfo)", re.I)


def score_top_risk(text):
    if not text:
        return {"disclosed": None, "risk_alignment_score": None}
    if _TOP_RISK_RE.search(text):
        return {"disclosed": True, "risk_alignment_score": 4}
    return {"disclosed": None, "risk_alignment_score": None}


def score_capital_allocation_framework(text):
    if not text:
        return {"disclosed": None}
    if _CAPITAL_ALLOCATION_RE.search(text):
        return {"disclosed": True}
    return {"disclosed": None}


def score_named_competitors(text):
    if not text:
        return {"named": None, "competitor_evidence_score": None}
    m = _NAMED_COMPETITORS_RE.search(text)
    if m:
        return {"named": True, "competitor_evidence_score": 4}
    return {"named": None, "competitor_evidence_score": None}


def score_revenue_sensitivity(text):
    if not text:
        return {"disclosed": None, "revenue_risk_coverage_score": None}
    if _REVENUE_SENSITIVITY_RE.search(text):
        return {"disclosed": True, "revenue_risk_coverage_score": 4}
    return {"disclosed": None, "revenue_risk_coverage_score": None}


def score_margin_sensitivity(text):
    if not text:
        return {"disclosed": None, "margin_risk_coverage_score": None}
    if _MARGIN_SENSITIVITY_RE.search(text):
        return {"disclosed": True, "margin_risk_coverage_score": 4}
    return {"disclosed": None, "margin_risk_coverage_score": None}


def score_rpt_management_explanation(text):
    if not text:
        return {"disclosed": None, "explanation_quality_score": None}
    if _RPT_EXPLANATION_MGMT_RE.search(text):
        return {"disclosed": True, "explanation_quality_score": 4}
    return {"disclosed": None, "explanation_quality_score": None}


def score_ceo_succession(text):
    if not text:
        return {"disclosed": None, "ceo_succession_score": None}
    if _CEO_SUCCESSION_RE.search(text):
        return {"disclosed": True, "ceo_succession_score": 4}
    return {"disclosed": None, "ceo_succession_score": None}


def score_cfo_succession(text):
    if not text:
        return {"disclosed": None, "cfo_succession_score": None}
    if _CFO_SUCCESSION_RE.search(text):
        return {"disclosed": True, "cfo_succession_score": 4}
    return {"disclosed": None, "cfo_succession_score": None}
