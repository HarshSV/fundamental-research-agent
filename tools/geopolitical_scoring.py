"""
Section T - Country / geopolitical & cross-border risks. Deterministic
(no-LLM) scorers over Annual Report MD&A/Risk Factors text, same pattern
as tools.regulatory_legal_scoring (section J).

T1.1 Sanctions/embargo exposure, T1.2 Tariff exposure, T2.1 GST
sensitivity, T2.2 Import duty sensitivity, T3.1 Convertibility risk,
T3.2 Repatriation risk.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_SANCTIONS_RE = re.compile(r"sanctions?\s+(?:imposed|regime)|embargo\w*", re.I)
_SANCTIONS_NONE_RE = re.compile(r"no\s+(?:material\s+)?(?:exposure\s+to\s+)?sanctions?", re.I)

_TARIFF_RE = re.compile(r"tariff\w*\s+(?:imposed|increase|exposure)", re.I)

_GST_RE = re.compile(r"gst\s+(?:rate\s+)?(?:change|revision)|goods\s+and\s+services\s+tax\s+(?:change|impact)", re.I)

_IMPORT_DUTY_RE = re.compile(r"import\s+dut(?:y|ies)\s+(?:change|increase|impact)|customs?\s+duty\s+(?:change|revision)", re.I)

_CONVERTIBILITY_RE = re.compile(r"currency\s+convertibility\s+(?:risk|restriction)|capital\s+controls?", re.I)

_REPATRIATION_RE = re.compile(r"repatriation\s+(?:of\s+(?:profits?|dividends?|funds?)\s+)?(?:risk|restriction)", re.I)


def score_sanctions_exposure(text):
    if not text:
        return {"disclosed": None, "sanctions_exposure_score": None}
    if _SANCTIONS_NONE_RE.search(text):
        return {"disclosed": False, "sanctions_exposure_score": 5}
    if _SANCTIONS_RE.search(text):
        return {"disclosed": True, "sanctions_exposure_score": 2}
    return {"disclosed": None, "sanctions_exposure_score": None}


def score_tariff_exposure(text):
    if not text:
        return {"disclosed": None, "tariff_exposure_score": None}
    if _TARIFF_RE.search(text):
        return {"disclosed": True, "tariff_exposure_score": 3}
    return {"disclosed": None, "tariff_exposure_score": None}


def score_gst_sensitivity(text):
    if not text:
        return {"disclosed": None, "gst_sensitivity_score": None}
    if _GST_RE.search(text):
        return {"disclosed": True, "gst_sensitivity_score": 3}
    return {"disclosed": None, "gst_sensitivity_score": None}


def score_import_duty_sensitivity(text):
    if not text:
        return {"disclosed": None, "import_duty_sensitivity_score": None}
    if _IMPORT_DUTY_RE.search(text):
        return {"disclosed": True, "import_duty_sensitivity_score": 3}
    return {"disclosed": None, "import_duty_sensitivity_score": None}


def score_convertibility_risk(text):
    if not text:
        return {"disclosed": None, "convertibility_risk_score": None}
    if _CONVERTIBILITY_RE.search(text):
        return {"disclosed": True, "convertibility_risk_score": 2}
    return {"disclosed": None, "convertibility_risk_score": None}


def score_repatriation_risk(text):
    if not text:
        return {"disclosed": None, "repatriation_risk_score": None}
    if _REPATRIATION_RE.search(text):
        return {"disclosed": True, "repatriation_risk_score": 2}
    return {"disclosed": None, "repatriation_risk_score": None}
