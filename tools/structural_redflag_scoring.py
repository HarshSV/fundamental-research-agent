"""
Section Q - Financial statement quality & structural red flags
(non-numeric cues). Deterministic (no-LLM) scorers over Annual Report
Notes/Corporate Governance text, same pattern as
tools.regulatory_legal_scoring (section J).

Q1.2 CFO/finance leadership churn, Q3.1 Group structure opacity,
Q3.2 Dormant/non-operating entities, Q4.1 Year-end transaction
concentration, Q4.2 Explanation quality.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_CFO_CHANGE_RE = re.compile(r"(?:appointment|resignation)\s+of\s+(?:the\s+)?(?:new\s+)?(?:chief\s+financial\s+officer|cfo)", re.I)

_GROUP_OPACITY_LAYERED_RE = re.compile(r"step[- ]down\s+subsidiar|multi[- ]layer(?:ed)?\s+(?:group\s+)?structure|indirect\s+subsidiar", re.I)
_GROUP_OPACITY_GENERIC_RE = re.compile(r"group\s+structure|subsidiaries\s+and\s+associates", re.I)

_DORMANT_ENTITY_RE = re.compile(r"dormant\s+(?:company|entity|subsidiary)|non[- ]operating\s+(?:subsidiary|entity)", re.I)
# Form AOC-1's own mandated field ("Names of subsidiaries which are yet
# to commence operations") - a real "None"/"N.A."/"Nil" answer is the
# cleanest possible finding (no dormant/shell entities in the group),
# not an absence of data. Confirmed real on Prime Fresh Limited.
_DORMANT_ENTITY_NONE_RE = re.compile(
    r"yet\s+to\s+commence\s+operations\.?\s*[-–—]?\s*(?:none|n\.?a\.?|nil)\b", re.I,
)

_YEAR_END_CONCENTRATION_RE = re.compile(r"(?:significant|material)\s+transactions?\s+(?:close\s+to|near|at)\s+(?:the\s+)?(?:financial\s+)?year[- ]end", re.I)

_EXPLANATION_QUALITY_RE = re.compile(r"(?:the\s+)?(?:transaction|reason)\s+(?:was|is)\s+(?:explained|justified)\s+(?:by|as)", re.I)


def score_cfo_churn(text):
    if not text:
        return {"change_count_disclosed": None, "finance_leadership_churn_score": None}
    matches = len(_CFO_CHANGE_RE.findall(text))
    if matches == 0:
        return {"change_count_disclosed": None, "finance_leadership_churn_score": None}
    score = 5 if matches <= 1 else 3 if matches == 2 else 2
    return {"change_count_disclosed": matches, "finance_leadership_churn_score": score}


def score_group_structure_opacity(text, entities=None):
    """Q.3.1 - lower score = more opaque (step-down/multi-layer chains),
    higher = simpler/more transparent. `entities` (optional) is the SAME
    real, structurally-extracted group-entity list P.4.3 already sources
    from AOC-1/RPT tables (tools.group_structure_scoring.
    extract_group_entities) - when it's genuinely available and none of
    the named entities carry a step-down/indirect relationship, that IS
    real evidence of a simple, direct group structure (the best case,
    score 5), not an absence of data. Without this, a company whose
    Annual Report never happens to use the generic phrase "group
    structure" but DOES clearly name a small, flat set of direct
    subsidiaries/associates (confirmed real on Prime Fresh Limited: 2
    subsidiaries + 1 associate, all directly held) was scored
    indistinguishably from a company with no group-structure disclosure
    at all."""
    specific, score = score_evidence_tier(text, _GROUP_OPACITY_LAYERED_RE, _GROUP_OPACITY_GENERIC_RE, high_score=2, mid_score=4)
    if score is None and entities:
        step_down = any("step" in (e.get("relationship") or "").lower() for e in entities)
        if not step_down and len(entities) <= 8:
            return {"layered_structure_disclosed": False, "structure_opacity_score": 5}
    return {"layered_structure_disclosed": specific, "structure_opacity_score": score}


def score_dormant_entities(text):
    if not text:
        return {"dormant_disclosed": None, "dormant_entity_score": None}
    if _DORMANT_ENTITY_RE.search(text):
        return {"dormant_disclosed": True, "dormant_entity_score": 3}
    if _DORMANT_ENTITY_NONE_RE.search(text):
        return {"dormant_disclosed": False, "dormant_entity_score": 5}
    return {"dormant_disclosed": None, "dormant_entity_score": None}


def score_year_end_concentration(text):
    if not text:
        return {"disclosed": None, "year_end_concentration_score": None}
    if _YEAR_END_CONCENTRATION_RE.search(text):
        return {"disclosed": True, "year_end_concentration_score": 2}
    return {"disclosed": None, "year_end_concentration_score": None}


def score_explanation_quality(text):
    if not text:
        return {"disclosed": None, "explanation_score": None}
    if _EXPLANATION_QUALITY_RE.search(text):
        return {"disclosed": True, "explanation_score": 4}
    return {"disclosed": None, "explanation_score": None}
