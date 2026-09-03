"""
Section M - M&A & inorganic growth behaviour. Deterministic (no-LLM)
scorers over Annual Report MD&A / Notes text, same pattern as
tools.regulatory_legal_scoring (section J).

M1.1 M&A frequency, M1.3 Acquisitive vs disciplined pattern,
M2.1 Related-party acquisitions, M2.2 Assets sold to affiliates,
M3.1 M&A pipeline, M3.2 Value-creation rationale.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_ACQUISITION_EVENT_RE = re.compile(
    r"acqui(?:red|sition\s+of)\s+[\w\s]{2,60}(?:for|at)\s+(?:inr|rs\.?|₹)?\s*[\d,]+|"
    r"completed\s+the\s+acquisition\s+of",
    re.I,
)
_ACQUISITION_GENERIC_RE = re.compile(r"acquisition|business\s+combination", re.I)

_DISCIPLINED_RE = re.compile(r"disciplined\s+(?:acquisition|m&a|capital\s+allocation)|strategic\s+fit\s+(?:criteria|assessment)", re.I)
_ACQUISITIVE_RE = re.compile(r"(?:active|aggressive)\s+(?:acquisition|inorganic\s+growth)\s+strategy", re.I)

_RP_ACQUISITION_RE = re.compile(r"acqui(?:red|sition)\s+(?:from|of)\s+(?:a\s+)?related\s+part(?:y|ies)|acquisition\s+from\s+(?:promoter|group\s+compan)", re.I)
_ASSET_TO_AFFILIATE_RE = re.compile(r"(?:asset|business|undertaking)\s+(?:sold|transferred|disposed)\s+to\s+(?:a\s+)?(?:related\s+part|affiliate|subsidiar)", re.I)

_MA_PIPELINE_RE = re.compile(r"(?:letter\s+of\s+intent|memorandum\s+of\s+understanding|definitive\s+agreement)\s+(?:to\s+)?acqui|pending\s+acquisition|proposed\s+acquisition", re.I)

_VALUE_CREATION_RE = re.compile(r"(?:synerg(?:y|ies)|value\s+creation|strategic\s+rationale)\s+(?:from|of|for)\s+(?:the\s+)?acquisition", re.I)
_VALUE_CREATION_GENERIC_RE = re.compile(r"strategic\s+(?:rationale|fit)|synerg(?:y|ies)", re.I)


def score_ma_frequency(text):
    specific, score = score_evidence_tier(text, _ACQUISITION_EVENT_RE, _ACQUISITION_GENERIC_RE)
    return {"event_disclosed": specific, "ma_frequency_score": score}


def score_ma_discipline(text):
    if not text:
        return {"pattern": None, "ma_discipline_score": None}
    if _DISCIPLINED_RE.search(text):
        return {"pattern": "disciplined", "ma_discipline_score": 4}
    if _ACQUISITIVE_RE.search(text):
        return {"pattern": "acquisitive", "ma_discipline_score": 3}
    return {"pattern": None, "ma_discipline_score": None}


def score_related_party_acquisitions(text):
    if not text:
        return {"related_party_ma_flag": None, "related_party_acquisition_score": None}
    if _RP_ACQUISITION_RE.search(text):
        return {"related_party_ma_flag": "Present", "related_party_acquisition_score": 2}
    return {"related_party_ma_flag": None, "related_party_acquisition_score": None}


def score_affiliate_disposals(text):
    if not text:
        return {"disposal_disclosed": None, "affiliate_disposal_exposure_score": None}
    if _ASSET_TO_AFFILIATE_RE.search(text):
        return {"disposal_disclosed": True, "affiliate_disposal_exposure_score": 3}
    return {"disposal_disclosed": None, "affiliate_disposal_exposure_score": None}


def score_ma_pipeline(text):
    if not text:
        return {"pipeline_disclosed": None, "pipeline_count_score": None}
    if _MA_PIPELINE_RE.search(text):
        return {"pipeline_disclosed": True, "pipeline_count_score": 3}
    return {"pipeline_disclosed": None, "pipeline_count_score": None}


def score_value_creation_rationale(text):
    specific, score = score_evidence_tier(text, _VALUE_CREATION_RE, _VALUE_CREATION_GENERIC_RE)
    return {"specific_disclosed": specific, "value_creation_score": score}
