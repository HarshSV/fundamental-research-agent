"""
Section H - Product, IP & technology. Deterministic (no-LLM) scorers over
real Annual Report MD&A / Intangible Assets / Corporate Governance / Risk
Management / BRSR text, mirroring the established dimension/evidence-
counting pattern used for F.2.1/G-section (tools/entry_barrier_scoring.py,
tools/channel_distribution_scoring.py) - generic keyword/regex logic, not
ticker-specific, per CLAUDE.md.

H1.2 Patent/trademark expiry, H2.1 R&D pipeline depth, H3.1 Legacy
technology dependence, H3.2 Cybersecurity posture, H4.1 Third-party
technology dependence, H4.2 License continuity risk.
"""
import re

_IP_EXPIRY_RE = re.compile(
    r"patents?\s+(?:expir|due\s+to\s+expire)|trademarks?\s+(?:expir|due\s+to\s+expire)|"
    r"expiry\s+of\s+(?:patents?|trademarks?|intellectual\s+property)|"
    r"renewal\s+of\s+(?:patents?|trademarks?)",
    re.I,
)
_IP_PRESENCE_RE = re.compile(
    r"\bpatents?\b|\btrademarks?\b|intellectual\s+property|\bcopyrights?\b|\bip\s+portfolio\b",
    re.I,
)

_RD_PIPELINE_RE = re.compile(
    r"(?:products?|projects?)\s+(?:under|in)\s+development|research\s+and\s+development\s+pipeline|"
    r"\br&d\s+pipeline\b|new\s+product\s+launch(?:es)?|pipeline\s+of\s+(?:new\s+)?products?|"
    r"upcoming\s+launches?",
    re.I,
)
_RD_PRESENCE_RE = re.compile(r"research\s+and\s+development|\br&d\b|innovation\s+(?:centre|center|lab)", re.I)

_LEGACY_RISK_RE = re.compile(
    r"legacy\s+(?:system|infrastructure|technology|it\s+system)s?|"
    r"outdated\s+(?:system|technology|infrastructure)s?|ageing\s+(?:it\s+)?infrastructure",
    re.I,
)
_MODERNIZATION_RE = re.compile(
    r"digital\s+transformation|it\s+moderni[sz]ation|cloud\s+migration|"
    r"modern(?:i[sz]ed)?\s+(?:technology\s+)?(?:stack|infrastructure|platform)|"
    r"technology\s+upgrade|system\s+upgrade",
    re.I,
)

_CYBERSECURITY_GOVERNANCE_RE = re.compile(
    r"iso\s*27001|soc\s*2\b|cybersecurity\s+(?:framework|policy|governance|committee)|"
    r"information\s+security\s+(?:framework|policy|management)|"
    r"data\s+protection\s+(?:policy|framework)|incident\s+response\s+(?:plan|team)|"
    r"penetration\s+test(?:ing)?|security\s+audit",
    re.I,
)
_CYBERSECURITY_PRESENCE_RE = re.compile(r"cybersecurity|cyber\s*security|information\s+security|data\s+privacy|data\s+breach", re.I)

_THIRDPARTY_TECH_RE = re.compile(
    r"cloud\s+(?:service|platform|infrastructure)\s+provider|saas\s+(?:platform|provider)|"
    r"licen[sc]ed\s+technology|third[\s-]party\s+(?:software|technology|platform)|"
    r"dependent\s+on\s+(?:third[\s-]party|external)\s+(?:technology|vendors?|providers?)|"
    r"key\s+technology\s+vendor",
    re.I,
)

_LICENSE_TERM_RE = re.compile(
    r"licen[sc]e\s+(?:agreement|period|term)\s+(?:of|for)\s+(\d{1,3})\s*(?:year|yr)s?|"
    r"(\d{1,3})[\s-]?year\s+licen[sc]e",
    re.I,
)
_LICENSE_RISK_LANGUAGE_RE = re.compile(
    r"licen[sc]e\s+(?:renewal|termination|continuity)|termination\s+clause|"
    r"material\s+licen[sc]e|dependen(?:ce|t)\s+on\s+(?:the\s+)?licen[sc]e",
    re.I,
)


def score_ip_expiry(text):
    """H.1.2 - Patent/trademark expiry. Explicit expiry/renewal
    disclosure scores highest (real, evidenced risk assessment
    possible); mere IP presence (patents/trademarks mentioned but no
    expiry language) scores a neutral mid; nothing found returns None."""
    if not text:
        return {"expiry_disclosed": None, "ip_expiry_score": None}
    if _IP_EXPIRY_RE.search(text):
        return {"expiry_disclosed": True, "ip_expiry_score": 4}
    if _IP_PRESENCE_RE.search(text):
        return {"expiry_disclosed": False, "ip_expiry_score": 3}
    return {"expiry_disclosed": None, "ip_expiry_score": None}


def score_rd_pipeline(text):
    """H.2.1 - R&D pipeline depth. Specific in-development/pipeline
    language scores highest; generic R&D/innovation-center presence
    without pipeline specifics scores mid; nothing found returns None."""
    if not text:
        return {"pipeline_evidence": None, "rd_pipeline_score": None}
    if _RD_PIPELINE_RE.search(text):
        return {"pipeline_evidence": "specific", "rd_pipeline_score": 4}
    if _RD_PRESENCE_RE.search(text):
        return {"pipeline_evidence": "generic", "rd_pipeline_score": 3}
    return {"pipeline_evidence": None, "rd_pipeline_score": None}


def score_legacy_dependence(text):
    """H.3.1 - Legacy technology dependence. IMPORTANT: the framework's
    own scale is inverted - "higher score meaning LOWER legacy risk".
    Disclosed modernization/digital-transformation language (without
    legacy-risk language) scores highest (5); explicit legacy-system
    dependency language scores lowest (2, not 1 - a company that at
    least DISCLOSES the dependency is more transparent than one with no
    evidence either way); both present scores a balanced middle; neither
    found returns None."""
    if not text:
        return {"legacy_risk_disclosed": None, "modernization_disclosed": None, "legacy_dependence_score": None}
    legacy = bool(_LEGACY_RISK_RE.search(text))
    modern = bool(_MODERNIZATION_RE.search(text))
    if not legacy and not modern:
        return {"legacy_risk_disclosed": None, "modernization_disclosed": None, "legacy_dependence_score": None}
    if legacy and modern:
        score = 3
    elif modern:
        score = 5
    else:
        score = 2
    return {"legacy_risk_disclosed": legacy, "modernization_disclosed": modern, "legacy_dependence_score": score}


def score_cybersecurity_posture(text):
    """H.3.2 - Cybersecurity posture. Specific governance/controls
    (ISO 27001, SOC2, named framework, incident-response plan) scores
    highest; generic cybersecurity-topic presence without specifics
    scores mid; nothing found returns None."""
    if not text:
        return {"governance_specifics_found": None, "cybersecurity_score": None}
    if _CYBERSECURITY_GOVERNANCE_RE.search(text):
        return {"governance_specifics_found": True, "cybersecurity_score": 4}
    if _CYBERSECURITY_PRESENCE_RE.search(text):
        return {"governance_specifics_found": False, "cybersecurity_score": 3}
    return {"governance_specifics_found": None, "cybersecurity_score": None}


def score_thirdparty_tech_dependence(text):
    """H.4.1 - Third-party technology dependence. Explicit dependency
    language on a named category (cloud/SaaS/licensed tech/key vendor)
    is itself the evidence needed - this is a risk-presence sub-point,
    not a positive/negative moat factor, so a real disclosed dependency
    scores mid (documented, real risk) and no disclosure returns None
    (never assumed absent)."""
    if not text:
        return {"dependency_disclosed": None, "thirdparty_tech_score": None}
    if _THIRDPARTY_TECH_RE.search(text):
        return {"dependency_disclosed": True, "thirdparty_tech_score": 3}
    return {"dependency_disclosed": None, "thirdparty_tech_score": None}


def score_license_continuity_risk(text):
    """H.4.2 - License continuity risk. A specific license term
    (X years) scores highest (clear, checkable renewal horizon);
    generic renewal/termination-risk language without a term scores
    mid; nothing found returns None."""
    if not text:
        return {"specific_term_disclosed": None, "license_risk_score": None}
    m = _LICENSE_TERM_RE.search(text)
    if m:
        return {"specific_term_disclosed": True, "license_risk_score": 4}
    if _LICENSE_RISK_LANGUAGE_RE.search(text):
        return {"specific_term_disclosed": False, "license_risk_score": 3}
    return {"specific_term_disclosed": None, "license_risk_score": None}
