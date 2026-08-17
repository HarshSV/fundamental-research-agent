"""
B.6.1-B.6.4 - Culture: deterministic (no-LLM) scorers.

Same design as tools/communication_quality_scoring.py: regex/keyword
pattern matching against real Annual Report text (R&D/Innovation section,
Corporate Governance Report's Vigil Mechanism/Internal Controls, Human
Resources section, BRSR employee-turnover disclosure), no LLM call.
Generic keyword sets, not ticker-specific.
"""

import re


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _band_score_pct(pct):
    if pct is None:
        return None
    if pct >= 80:
        return 5
    if pct >= 65:
        return 4
    if pct >= 50:
        return 3
    if pct >= 30:
        return 2
    return 1


# ---------------------------------------------------------------------------
# B.6.1 - Innovation focus (R&D / Innovation / Digital Transformation).
# ---------------------------------------------------------------------------

_INNOVATION_KEYWORD = re.compile(
    r"\binnovation\b|\bR&D\b|research and development|digital transformation|"
    r"\bpatent(?:s|ed)?\b|new product(?:s)? launch", re.I
)
_QUANTIFIED_MARKER = re.compile(r"\d+(?:\.\d+)?\s*%|₹\s*\d|\$\s*\d|\bcrore\b|\bmillion\b|\bbillion\b|\d+\s*(?:new )?(?:products?|patents?)\b", re.I)
_INNOVATION_QUANTIFIED = re.compile(
    r"\d+(?:\.\d+)?\s*%|₹\s*\d|\$\s*\d|\bcrore\b|\bmillion\b|\bbillion\b|"
    r"\d+\+?\s*(?:new )?(?:products?|patents?|scientists|researchers|factories|labs?|"
    r"centres?|centers?|launches?|innovations?)", re.I
)
_GENERIC_INNOVATION_BOILERPLATE = re.compile(
    r"committed to innovation|focus(?:ed)? on innovation|innovation (?:is|remains) (?:a |at )?(?:key|core|central)|"
    r"culture of innovation|innovation[- ]led growth strategy|drives? innovation|cultivate innovation|"
    r"leverage(?:s)? .{0,30}(?:to )?(?:drive|deliver|cultivate) innovation|drive innovation and", re.I
)


def score_innovation_focus(innovation_text):
    """An innovation-keyword sentence is "Innovation-led" if it names a
    QUANTIFIED figure (₹ R&D spend, patent count, new-product count, % of
    revenue from new products) in the same sentence - not just generic
    innovation language. "Traditional" if it matches known innovation
    boilerplate with no specifics. Returns {'innovation_led_count',
    'traditional_count','innovation_pct','innovation_score'} or all-None
    if no innovation-keyword sentence carries either signal."""
    if not innovation_text:
        return {"innovation_led_count": None, "traditional_count": None, "innovation_pct": None, "innovation_score": None}
    led, traditional = 0, 0
    for sent in _sentences(innovation_text):
        if not _INNOVATION_KEYWORD.search(sent):
            continue
        if _INNOVATION_QUANTIFIED.search(sent):
            led += 1
        elif _GENERIC_INNOVATION_BOILERPLATE.search(sent):
            traditional += 1
    total = led + traditional
    if total == 0:
        return {"innovation_led_count": None, "traditional_count": None, "innovation_pct": None, "innovation_score": None}
    pct = round(100 * led / total, 1)
    return {"innovation_led_count": led, "traditional_count": traditional, "innovation_pct": pct, "innovation_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# B.6.2 - Compliance orientation (Vigil Mechanism / Internal Controls).
# ---------------------------------------------------------------------------

_COMPLIANCE_KEYWORD = re.compile(
    r"vigil mechanism|whistle[- ]?blower|internal financial controls|internal controls?\b", re.I
)
_STRONG_COMPLIANCE_MARKER = re.compile(
    r"(?:established|adopted|operates?|in place|implemented)[^.]{0,40}?(?:vigil mechanism|whistle[- ]?blower|internal (?:financial )?controls?)|"
    r"(?:vigil mechanism|whistle[- ]?blower policy|internal (?:financial )?controls?)[^.]{0,60}?(?:established|adopted|in place|operating effectively|adequate)", re.I
)
_WEAK_COMPLIANCE_MARKER = re.compile(
    r"material weakness|significant deficienc|qualified opinion|adverse opinion|"
    r"non[- ]compliance|lapses? in internal control", re.I
)


def score_compliance_orientation(compliance_text):
    """A compliance-keyword sentence is "Strong" if it explicitly confirms
    an established/operating vigil-mechanism or internal-controls system
    (the standard Corporate Governance Report / Auditor's Report
    confirmatory language). "Weak" if it names a material
    weakness/deficiency/qualified opinion. Returns
    {'strong_count','weak_count','compliance_pct','compliance_score'} or
    all-None if no compliance-keyword sentence carries either signal."""
    if not compliance_text:
        return {"strong_count": None, "weak_count": None, "compliance_pct": None, "compliance_score": None}
    strong, weak = 0, 0
    for sent in _sentences(compliance_text):
        if not _COMPLIANCE_KEYWORD.search(sent):
            continue
        if _WEAK_COMPLIANCE_MARKER.search(sent):
            weak += 1
        elif _STRONG_COMPLIANCE_MARKER.search(sent):
            strong += 1
    total = strong + weak
    if total == 0:
        return {"strong_count": None, "weak_count": None, "compliance_pct": None, "compliance_score": None}
    pct = round(100 * strong / total, 1)
    return {"strong_count": strong, "weak_count": weak, "compliance_pct": pct, "compliance_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# B.6.3 - Employee morale (Human Resources / employee engagement).
# ---------------------------------------------------------------------------

_HR_KEYWORD = re.compile(
    r"employee engagement|employee satisfaction|employee wellbeing|workforce\b|"
    r"employee experience|talent (?:retention|management)", re.I
)
_HR_QUANTIFIED = re.compile(
    r"\d+(?:\.\d+)?\s*%|₹\s*\d|\bcrore\b|\bmillion\b|\bbillion\b|"
    r"\d+\+?\s*(?:hours?|training (?:hours|sessions)|employees?|workforce members?)", re.I
)
_GENERIC_HR_BOILERPLATE = re.compile(
    r"we value our (?:employees|people)|committed to (?:employee|our people)|"
    r"people are our (?:greatest|biggest|most important) asset|fostering an? (?:inclusive|engaged) (?:workplace|culture)|"
    r"high-performing workforce|employer of choice|boost employee satisfaction|"
    r"strengthen(?:s|ed)? employee engagement|nurture(?:s)? (?:a )?(?:high-performing )?workforce|"
    r"drives? (?:innovation,? )?performance", re.I
)


def score_employee_morale(hr_text):
    """An HR-keyword sentence is "Engaged" (evidence-backed) if it names a
    QUANTIFIED figure (an engagement survey score, training coverage %,
    headcount metric) in the same sentence - not just generic
    people-culture language. "Disengaged" is only inferred from known
    generic HR boilerplate with no specifics, mirroring the
    detailed-vs-generic pattern used for B.4.1/B.6.1. Returns
    {'engaged_count','disengaged_count','engagement_pct',
    'engagement_score'} or all-None if no HR-keyword sentence carries
    either signal."""
    if not hr_text:
        return {"engaged_count": None, "disengaged_count": None, "engagement_pct": None, "engagement_score": None}
    engaged, disengaged = 0, 0
    for sent in _sentences(hr_text):
        if not _HR_KEYWORD.search(sent):
            continue
        if _HR_QUANTIFIED.search(sent):
            engaged += 1
        elif _GENERIC_HR_BOILERPLATE.search(sent):
            disengaged += 1
    total = engaged + disengaged
    if total == 0:
        return {"engaged_count": None, "disengaged_count": None, "engagement_pct": None, "engagement_score": None}
    pct = round(100 * engaged / total, 1)
    return {"engaged_count": engaged, "disengaged_count": disengaged, "engagement_pct": pct, "engagement_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# B.6.4 - Attrition evidence (BRSR turnover-rate disclosure).
# ---------------------------------------------------------------------------

# BRSR's mandated "Turnover rate for permanent employees and workers"
# section states Voluntary/Involuntary attrition as two separate
# percentages, e.g. "Voluntary: 12.3%; Involuntary: 6.2%" - a structured,
# registry-wide disclosure format (SEBI's top-1000-by-market-cap mandate),
# not one company's specific wording.
_BRSR_TURNOVER = re.compile(r"Voluntary:\s*([\d.]+)\s*%;?\s*Involuntary:\s*([\d.]+)\s*%", re.I)
# Fallback: a plainly-stated single attrition/turnover rate.
_PLAIN_ATTRITION_RATE = re.compile(r"(?:attrition|(?:employee )?turnover) rate (?:of |was |is |stood at )?([\d.]+)\s*%", re.I)


def score_attrition_evidence(attrition_text):
    """Extracts the company's own disclosed employee turnover/attrition
    rate - preferring BRSR's structured Voluntary+Involuntary breakdown
    (summed to a total rate), falling back to a plainly-stated single
    rate. Attrition Stability Score bands how LOW the rate is (lower
    attrition = more stable workforce; no universal 'good' number, but a
    lower rate is directionally better across most industries). Returns
    {'turnover_rate_pct','retained_pct','attrition_stability_score'} or
    all-None if no explicit turnover/attrition percentage is disclosed."""
    if not attrition_text:
        return {"turnover_rate_pct": None, "retained_pct": None, "attrition_stability_score": None}
    m = _BRSR_TURNOVER.search(attrition_text)
    rate = None
    if m:
        try:
            rate = round(float(m.group(1)) + float(m.group(2)), 1)
        except (ValueError, TypeError):
            rate = None
    if rate is None:
        m2 = _PLAIN_ATTRITION_RATE.search(attrition_text)
        if m2:
            try:
                rate = float(m2.group(1))
            except (ValueError, TypeError):
                rate = None
    if rate is None:
        return {"turnover_rate_pct": None, "retained_pct": None, "attrition_stability_score": None}
    rate = max(0.0, min(100.0, rate))
    if rate <= 10:
        score = 5
    elif rate <= 15:
        score = 4
    elif rate <= 20:
        score = 3
    elif rate <= 30:
        score = 2
    else:
        score = 1
    return {"turnover_rate_pct": round(rate, 1), "retained_pct": round(100 - rate, 1), "attrition_stability_score": score}
