"""
Section S - Sector-specific considerations. Deterministic (no-LLM)
scorers over Annual Report text, same pattern as
tools.regulatory_legal_scoring (section J). Each S-block only applies to
its own sector (tools.nse_sector_map.get_nse_sector) - every other
company gets NOT_APPLICABLE, never a forced score (Phase 16).

S1 Financials/banks, S2 Pharma, S3 Auto, S4 Tech/IT, S5 Consumer goods.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

SECTOR_APPLICABILITY = {
    "S.1": {"Banks", "NBFC"},
    "S.2": {"Pharmaceuticals"},
    "S.3": {"Automobile & Auto Components"},
    "S.4": {"Information Technology"},
    "S.5": {"Fast Moving Consumer Goods (FMCG)", "Consumer Durables"},
}


def is_sector_applicable(point_id, sector):
    """point_id is the S.n point-level id (e.g. 'S.1') whose applicable-
    sector set every child sub-point (S.1.1, S.1.2, ...) shares."""
    applicable = SECTOR_APPLICABILITY.get(point_id)
    return bool(applicable) and sector in applicable


_ASSET_QUALITY_RE = re.compile(r"gross\s+npa\s+(?:of|at)\s+\d+(?:\.\d+)?%|asset\s+quality\s+(?:review|remained\s+stable)", re.I)
_RPT_EXPOSURE_RE = re.compile(r"related\s+party\s+exposure|loans?\s+(?:and\s+advances\s+)?to\s+related\s+part", re.I)
_REG_CAPITAL_RE = re.compile(r"capital\s+adequacy\s+ratio\s+(?:of|at)\s+\d+(?:\.\d+)?%|car\s+(?:of|at)\s+\d+(?:\.\d+)?%", re.I)
_UNDERWRITING_RE = re.compile(r"loan\s+underwriting|credit\s+appraisal\s+(?:process|policy)", re.I)

_PATENT_CLIFF_RE = re.compile(r"patent\s+(?:expiry|expiration|cliff)|loss\s+of\s+(?:patent\s+)?exclusivity", re.I)
_INSPECTION_RE = re.compile(r"usfda\s+(?:inspection|warning\s+letter)|regulatory\s+inspection", re.I)
_PRICE_CONTROL_RE = re.compile(r"drug\s+price\s+control\s+order|nppa|price\s+control\s+(?:mechanism|regime)", re.I)

_MODEL_REFRESH_RE = re.compile(r"new\s+model\s+launch|model\s+refresh\s+cycle", re.I)
_CHANNEL_INVENTORY_RE = re.compile(r"dealer\s+(?:channel\s+)?inventory|channel\s+stock", re.I)
_EXPORT_DEP_S3_RE = re.compile(r"export\s+revenue\s+(?:of|constitut\w*)\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%", re.I)

_CLIENT_CONCENTRATION_RE = re.compile(r"top\s+(?:5|10|client)\s+client\w*\s+(?:contribut\w*|account\w*\s+for)\s+(?:approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%", re.I)
_CONTRACT_RENEWAL_RISK_RE = re.compile(r"contract\s+renewal\s+risk|non[- ]renewal\s+of\s+(?:key\s+)?contracts?", re.I)
_VISA_DEPENDENCE_RE = re.compile(r"visa\s+(?:restrictions?|dependency|regulations?)|immigration\s+(?:policy|restriction)", re.I)

_BRAND_STRENGTH_RE = re.compile(r"(?:leading|market[- ]leading)\s+brand|brand\s+recall|brand\s+equity", re.I)
_DISTRIBUTION_DEPTH_RE = re.compile(r"(\d{1,3}(?:,\d{3})*)\s+(?:retail\s+)?(?:outlets|dealers|distributors)", re.I)
_COMMODITY_VOLATILITY_S5_RE = re.compile(r"input\s+cost\s+volatility|raw\s+material\s+price\s+volatility", re.I)


def score_asset_quality(text):
    if not text:
        return {"disclosed": None, "asset_quality_score": None}
    if _ASSET_QUALITY_RE.search(text):
        return {"disclosed": True, "asset_quality_score": 4}
    return {"disclosed": None, "asset_quality_score": None}


def score_rpt_exposure_bank(text):
    if not text:
        return {"disclosed": None, "rpt_exposure_score": None}
    if _RPT_EXPOSURE_RE.search(text):
        return {"disclosed": True, "rpt_exposure_score": 3}
    return {"disclosed": None, "rpt_exposure_score": None}


def score_regulatory_capital(text):
    if not text:
        return {"disclosed": None, "capital_adequacy_score": None}
    if _REG_CAPITAL_RE.search(text):
        return {"disclosed": True, "capital_adequacy_score": 4}
    return {"disclosed": None, "capital_adequacy_score": None}


def score_underwriting_quality(text):
    if not text:
        return {"disclosed": None, "underwriting_quality_score": None}
    if _UNDERWRITING_RE.search(text):
        return {"disclosed": True, "underwriting_quality_score": 3}
    return {"disclosed": None, "underwriting_quality_score": None}


def score_patent_cliffs(text):
    if not text:
        return {"disclosed": None, "patent_cliff_risk_score": None}
    if _PATENT_CLIFF_RE.search(text):
        return {"disclosed": True, "patent_cliff_risk_score": 2}
    return {"disclosed": None, "patent_cliff_risk_score": None}


def score_regulatory_inspections(text):
    if not text:
        return {"disclosed": None, "inspection_risk_score": None}
    if _INSPECTION_RE.search(text):
        return {"disclosed": True, "inspection_risk_score": 2}
    return {"disclosed": None, "inspection_risk_score": None}


def score_price_controls(text):
    if not text:
        return {"disclosed": None, "price_control_exposure_score": None}
    if _PRICE_CONTROL_RE.search(text):
        return {"disclosed": True, "price_control_exposure_score": 3}
    return {"disclosed": None, "price_control_exposure_score": None}


def score_model_refresh_cycle(text):
    if not text:
        return {"disclosed": None, "refresh_strength_score": None}
    if _MODEL_REFRESH_RE.search(text):
        return {"disclosed": True, "refresh_strength_score": 4}
    return {"disclosed": None, "refresh_strength_score": None}


def score_channel_inventory(text):
    if not text:
        return {"disclosed": None, "channel_inventory_risk_score": None}
    if _CHANNEL_INVENTORY_RE.search(text):
        return {"disclosed": True, "channel_inventory_risk_score": 3}
    return {"disclosed": None, "channel_inventory_risk_score": None}


def score_export_dependency_s3(text):
    if not text:
        return {"export_pct": None}
    m = _EXPORT_DEP_S3_RE.search(text)
    if m:
        return {"export_pct": float(m.group(1))}
    return {"export_pct": None}


def score_client_concentration(text):
    if not text:
        return {"top_client_pct": None}
    m = _CLIENT_CONCENTRATION_RE.search(text)
    if m:
        return {"top_client_pct": float(m.group(1))}
    return {"top_client_pct": None}


def score_contract_renewal_risk(text):
    if not text:
        return {"disclosed": None, "renewal_risk_score": None}
    if _CONTRACT_RENEWAL_RISK_RE.search(text):
        return {"disclosed": True, "renewal_risk_score": 2}
    return {"disclosed": None, "renewal_risk_score": None}


def score_visa_dependence(text):
    if not text:
        return {"disclosed": None, "visa_risk_score": None}
    if _VISA_DEPENDENCE_RE.search(text):
        return {"disclosed": True, "visa_risk_score": 3}
    return {"disclosed": None, "visa_risk_score": None}


def score_brand_strength_s5(text):
    if not text:
        return {"disclosed": None, "brand_strength_score": None}
    if _BRAND_STRENGTH_RE.search(text):
        return {"disclosed": True, "brand_strength_score": 4}
    return {"disclosed": None, "brand_strength_score": None}


def score_distribution_depth_s5(text):
    if not text:
        return {"outlet_count": None}
    m = _DISTRIBUTION_DEPTH_RE.search(text)
    if m:
        return {"outlet_count": int(m.group(1).replace(",", ""))}
    return {"outlet_count": None}


def score_commodity_volatility_s5(text):
    if not text:
        return {"disclosed": None, "commodity_volatility_score": None}
    if _COMMODITY_VOLATILITY_S5_RE.search(text):
        return {"disclosed": True, "commodity_volatility_score": 3}
    return {"disclosed": None, "commodity_volatility_score": None}
