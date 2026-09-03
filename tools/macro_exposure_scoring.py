"""
Section K - Macro & external exposures (qualitative). Deterministic
(no-LLM) scorers over the Annual Report's MD&A/Risk Factors/Notes text,
same established pattern as tools.regulatory_legal_scoring (section J) -
generic keyword/regex logic, not ticker-specific, per CLAUDE.md.

K1.1 Commodity input dependence, K2.1 Export/import dependence,
K2.2 Geopolitical trade risk, K3.1 Interest-rate sensitivity,
K3.2 Economic cyclicality, K4.2 Hedging protection.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_COMMODITY_SPECIFIC_RE = re.compile(
    r"(?:crude\s+oil|copper|aluminium|aluminum|steel|zinc|natural\s+gas|naphtha)\s+prices?\s+"
    r"(?:constitute|account for|represent)|"
    r"raw\s+material\s+cost\s+(?:of|constitutes)\s+(?:approximately\s+|about\s+)?\d{1,3}%",
    re.I,
)
_COMMODITY_GENERIC_RE = re.compile(
    r"commodity\s+price\s+(?:risk|volatility|fluctuation)|raw\s+material\s+price\s+fluctuation|"
    r"dependent\s+on\s+(?:key\s+)?commodit(?:y|ies)|"
    # A company's specific input commodity is often named directly instead
    # of the generic word "commodity" (e.g. an agri/food business discusses
    # "food-price volatility"/"agricultural commodity price"/"crop price"
    # rather than literally "commodity price volatility") - generic across
    # any sector's own input-price-risk phrasing, not tied to one company.
    r"(?:food|agricultural|crop|farm)[- ]price\s+(?:volatility|fluctuation|risk)|"
    r"input\s+cost\s+(?:volatility|fluctuation)",
    re.I,
)

_EXPORT_PCT_RE = re.compile(
    r"export\s+revenue\s+(?:of|constitut\w*|account\w*\s+for)\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%|"
    r"(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:our\s+|the\s+company.s\s+)?revenue\s+(?:is|was)\s+(?:from\s+)?export",
    re.I,
)
_EXPORT_GENERIC_RE = re.compile(r"export\s+sales|export\s+market|import[- ]dependent\s+inputs?", re.I)

_GEOPOLITICAL_SPECIFIC_RE = re.compile(
    r"(?:trade\s+war|sanctions?|tariff\s+war|export\s+restrictions?|geopolitical\s+tensions?)\s+"
    r"(?:in|affecting|impacting)\s+[\w\s]{2,40}(?:market|region|country|trade)",
    re.I,
)
_GEOPOLITICAL_GENERIC_RE = re.compile(r"geopolitical\s+(?:risk|uncertaint\w+|tensions?)|trade\s+tensions?", re.I)

_FLOATING_RATE_RE = re.compile(
    r"floating[- ]rate\s+(?:debt|borrowings?)\s+(?:of|constitut\w*)\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%|"
    r"(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:our\s+)?(?:total\s+)?(?:debt|borrowings?)\s+(?:is|are)\s+(?:on\s+a\s+)?floating",
    re.I,
)
_INTEREST_RATE_GENERIC_RE = re.compile(r"interest\s+rate\s+risk|interest\s+rate\s+fluctuation|floating[- ]rate\s+(?:debt|loan)", re.I)

_CYCLICALITY_SPECIFIC_RE = re.compile(
    r"(?:demand|revenue|sales)\s+(?:is|are)\s+(?:closely\s+)?(?:linked|correlated|tied)\s+to\s+(?:the\s+)?"
    r"(?:economic\s+cycle|gdp\s+growth|industrial\s+production)",
    re.I,
)
_CYCLICALITY_GENERIC_RE = re.compile(r"cyclical\s+(?:nature|industry|demand)|economic\s+(?:downturn|slowdown)\s+(?:may|could)\s+(?:affect|impact)", re.I)

_HEDGE_COVERAGE_RE = re.compile(
    r"hedged\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:our\s+)?(?:foreign\s+currency\s+)?exposure|"
    r"forward\s+contracts?\s+(?:covering|to\s+hedge)\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
_HEDGE_GENERIC_RE = re.compile(r"hedging\s+(?:policy|strategy|instruments?)|forward\s+contracts?|currency\s+(?:derivative|hedge)", re.I)
# SEBI LODR Schedule V Part A(2A)'s mandated commodity-hedging disclosure
# routinely answers "no" - a real, explicit "we do not hedge" finding
# (not a formal risk-management framework, no derivative instruments
# used), not an absence of any hedging-related disclosure at all.
# Confirmed real on Prime Fresh Limited.
_HEDGE_NONE_RE = re.compile(
    r"has\s+not\s+(?:formulated|undertaken)\s+(?:any\s+)?(?:formal\s+)?"
    r"(?:risk\s+management\s+framework|commodity\s+hedging\s+activit\w*)", re.I,
)


def score_commodity_input_dependence(text):
    specific, score = score_evidence_tier(text, _COMMODITY_SPECIFIC_RE, _COMMODITY_GENERIC_RE)
    return {"specific_disclosed": specific, "commodity_dependency_score": score}


def score_export_import_dependence(text):
    if not text:
        return {"export_pct": None, "external_trade_exposure_pct": None}
    m = _EXPORT_PCT_RE.search(text)
    if m:
        pct = float(next(g for g in m.groups() if g))
        return {"export_pct": pct, "external_trade_exposure_pct": pct}
    if _EXPORT_GENERIC_RE.search(text):
        return {"export_pct": None, "external_trade_exposure_pct": None, "generic_disclosure": True}
    return {"export_pct": None, "external_trade_exposure_pct": None}


def score_geopolitical_trade_risk(text):
    specific, score = score_evidence_tier(text, _GEOPOLITICAL_SPECIFIC_RE, _GEOPOLITICAL_GENERIC_RE)
    return {"specific_disclosed": specific, "geopolitical_trade_risk_score": score}


def score_interest_rate_sensitivity(text):
    if not text:
        return {"floating_rate_pct": None, "interest_rate_exposure_pct": None}
    m = _FLOATING_RATE_RE.search(text)
    if m:
        pct = float(next(g for g in m.groups() if g))
        return {"floating_rate_pct": pct, "interest_rate_exposure_pct": pct}
    if _INTEREST_RATE_GENERIC_RE.search(text):
        return {"floating_rate_pct": None, "interest_rate_exposure_pct": None, "generic_disclosure": True}
    return {"floating_rate_pct": None, "interest_rate_exposure_pct": None}


def score_economic_cyclicality(text):
    specific, score = score_evidence_tier(text, _CYCLICALITY_SPECIFIC_RE, _CYCLICALITY_GENERIC_RE)
    return {"specific_disclosed": specific, "cyclicality_score": score}


def score_hedging_protection(text):
    if not text:
        return {"hedge_coverage_pct": None}
    m = _HEDGE_COVERAGE_RE.search(text)
    if m:
        pct = float(next(g for g in m.groups() if g))
        return {"hedge_coverage_pct": pct}
    if _HEDGE_NONE_RE.search(text):
        return {"hedge_coverage_pct": 0.0, "generic_disclosure": True, "hedging_undertaken": False}
    if _HEDGE_GENERIC_RE.search(text):
        return {"hedge_coverage_pct": None, "generic_disclosure": True}
    return {"hedge_coverage_pct": None}
