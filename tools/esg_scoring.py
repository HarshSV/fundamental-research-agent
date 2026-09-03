"""
Section N - ESG, social license & sustainability (qualitative).
Deterministic (no-LLM) scorers over uploaded BRSR/ESG report text where
available (extra_manual_document_types), falling back to Annual Report
ESG/sustainability sections - same pattern as tools.regulatory_legal_scoring
(section J).

N1.1 ESG targets, N2.1 Community impact, N2.2 Displacement/resettlement,
N3.1 Pollution/environmental incidents, N3.2 Hazardous waste,
N3.3 Pending clearances, N4.1 Union/collective bargaining exposure,
N4.2 Strikes/disputes, N4.3 Employee grievances,
N5.1 Human-rights policy/supplier screening, N5.2 Forced/child labour incidents.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier, classify_status

_ESG_TARGET_QUANTIFIED_RE = re.compile(
    r"(?:net[- ]zero|carbon\s+neutral)\s+by\s+20\d{2}|"
    r"reduce\s+(?:ghg\s+)?emissions?\s+(?:by\s+)?\d{1,3}%\s+by\s+20\d{2}|"
    r"\d{1,3}%\s+renewable\s+energy\s+by\s+20\d{2}",
    re.I,
)
_ESG_TARGET_GENERIC_RE = re.compile(r"esg\s+(?:targets?|roadmap|ambition)|sustainability\s+goals?", re.I)

_COMMUNITY_IMPACT_RE = re.compile(r"csr\s+(?:spend|expenditure|activities)|community\s+development\s+program|beneficiaries", re.I)

_DISPLACEMENT_HIGH_RE = re.compile(r"displacement|resettlement\s+of\s+(?:communities|villagers|residents)", re.I)
_DISPLACEMENT_NONE_RE = re.compile(r"no\s+(?:material\s+)?displacement|no\s+resettlement", re.I)

_POLLUTION_INCIDENT_RE = re.compile(r"environmental\s+(?:incident|violation|non[- ]compliance)|pollution\s+(?:incident|control\s+board\s+notice)", re.I)
_POLLUTION_NONE_RE = re.compile(r"no\s+(?:material\s+)?environmental\s+(?:incident|violation)", re.I)

_HAZARDOUS_WASTE_RE = re.compile(r"hazardous\s+waste\s+(?:management|generated|disposed)", re.I)

_CLEARANCE_PENDING_RE = re.compile(r"(?:environmental|forest|wildlife)\s+clearance\s+(?:is\s+)?pending|application\s+(?:under|for)\s+(?:environmental\s+)?clearance\s+(?:is\s+)?(?:pending|under\s+process)", re.I)
_CLEARANCE_CLEARED_RE = re.compile(r"(?:environmental|forest|wildlife)\s+clearance\s+(?:has\s+been\s+)?(?:obtained|granted|received)", re.I)

_UNION_RE = re.compile(r"(?:employees?|workers?)\s+(?:are\s+)?(?:represented\s+by|members?\s+of)\s+(?:a\s+)?(?:trade\s+)?union|collective\s+bargaining\s+agreement", re.I)
_STRIKE_RE = re.compile(r"\bstrike\b|labour\s+(?:unrest|dispute|disruption)|industrial\s+action", re.I)
_STRIKE_NONE_RE = re.compile(r"no\s+(?:material\s+)?(?:strikes?|labour\s+disputes?)", re.I)

_GRIEVANCE_RATE_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:employee\s+)?(?:grievances|complaints)\s+(?:were\s+)?resolved|"
    r"grievance\s+redressal\s+mechanism",
    re.I,
)

_HUMAN_RIGHTS_POLICY_RE = re.compile(r"human\s+rights?\s+policy|supplier\s+(?:code\s+of\s+conduct|screening|assessment)", re.I)

_FORCED_LABOUR_INCIDENT_RE = re.compile(r"(?:forced|child)\s+labou?r\s+(?:incident|found|identified)", re.I)
_FORCED_LABOUR_NONE_RE = re.compile(r"no\s+(?:incidents?\s+of\s+)?(?:forced|child)\s+labou?r", re.I)


def score_esg_targets(text):
    specific, score = score_evidence_tier(text, _ESG_TARGET_QUANTIFIED_RE, _ESG_TARGET_GENERIC_RE, high_score=5, mid_score=3)
    return {"quantified": specific, "target_coverage_score": score}


def score_community_impact(text):
    if not text:
        return {"disclosed": None, "community_impact_score": None}
    if _COMMUNITY_IMPACT_RE.search(text):
        return {"disclosed": True, "community_impact_score": 4}
    return {"disclosed": None, "community_impact_score": None}


def classify_displacement_risk(text):
    status = classify_status(text, [
        ("High", _DISPLACEMENT_HIGH_RE),
        ("Low", _DISPLACEMENT_NONE_RE),
    ])
    return {"displacement_risk": status}


def score_environmental_incidents(text):
    if not text:
        return {"incident_disclosed": None, "environmental_incident_score": None}
    if _POLLUTION_NONE_RE.search(text):
        return {"incident_disclosed": False, "environmental_incident_score": 5}
    if _POLLUTION_INCIDENT_RE.search(text):
        return {"incident_disclosed": True, "environmental_incident_score": 2}
    return {"incident_disclosed": None, "environmental_incident_score": None}


def score_hazardous_waste(text):
    if not text:
        return {"disclosed": None, "hazardous_waste_score": None}
    if _HAZARDOUS_WASTE_RE.search(text):
        return {"disclosed": True, "hazardous_waste_score": 3}
    return {"disclosed": None, "hazardous_waste_score": None}


def classify_clearance_status(text):
    status = classify_status(text, [
        ("Pending", _CLEARANCE_PENDING_RE),
        ("Cleared", _CLEARANCE_CLEARED_RE),
    ])
    return {"clearance_status": status}


def score_union_exposure(text):
    if not text:
        return {"union_disclosed": None, "labour_relations_score": None}
    if _UNION_RE.search(text):
        return {"union_disclosed": True, "labour_relations_score": 3}
    return {"union_disclosed": None, "labour_relations_score": None}


def score_strikes_disputes(text):
    if not text:
        return {"strike_disclosed": None, "labour_disruption_score": None}
    if _STRIKE_NONE_RE.search(text):
        return {"strike_disclosed": False, "labour_disruption_score": 5}
    if _STRIKE_RE.search(text):
        return {"strike_disclosed": True, "labour_disruption_score": 2}
    return {"strike_disclosed": None, "labour_disruption_score": None}


def score_employee_grievances(text):
    if not text:
        return {"resolution_rate_pct": None}
    m = _GRIEVANCE_RATE_RE.search(text)
    if m and m.group(1):
        return {"resolution_rate_pct": float(m.group(1))}
    if m:
        return {"resolution_rate_pct": None, "generic_disclosure": True}
    return {"resolution_rate_pct": None}


def score_human_rights_policy(text):
    if not text:
        return {"disclosed": None, "human_rights_supplychain_score": None}
    if _HUMAN_RIGHTS_POLICY_RE.search(text):
        return {"disclosed": True, "human_rights_supplychain_score": 4}
    return {"disclosed": None, "human_rights_supplychain_score": None}


def classify_forced_labour_status(text):
    status = classify_status(text, [
        ("Incidents", _FORCED_LABOUR_INCIDENT_RE),
        ("None disclosed", _FORCED_LABOUR_NONE_RE),
    ])
    return {"incident_status": status}
