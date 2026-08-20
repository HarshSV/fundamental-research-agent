"""
F.4.1/F.4.2 - Regulatory or trade barriers protecting or exposing the
company. Deterministic (no-LLM) scorers over real Annual Report MD&A
text. Generic keyword/regex logic, not ticker-specific.

Real Indian ARs (CIPLA, TATASTEEL, ITC confirmed by direct inspection)
each disclose real, distinct barrier language: CIPLA discusses USFDA/
WHO/ANVISA/PMDA/EMA approvals and "licence to operate"; TATASTEEL
discusses mining leases and US Section 232 tariffs/anti-dumping; ITC
discusses import duties/tariffs on tobacco and agri-commodity exports.
This intentionally overlaps in scope with F.5.2 (import competition) -
the spec itself points both sub-points at the same DGFT/ITC(HS) source.
"""
import re

_REGULATORY_BARRIER_DIMENSIONS = {
    "regulatory_approval_regime": re.compile(
        r"\busfda\b|\bwho[\s-]geneva\b|\banvisa\b|\bpmda\b|\bema\b|\bregulatory\s+approvals?\b",
        re.I,
    ),
    "licence_to_operate": re.compile(r"\blicen[cs]e\s+to\s+operate\b", re.I),
    "mining_or_resource_lease": re.compile(r"\bmining\s+leases?\b|\bmining\s+licen[cs]es?\b", re.I),
    "mandatory_standards": re.compile(
        r"\bindustrial\s+standards\b|\bmandatory\s+standards?\b|\bBIS\s+certif\w*\b|\bquality\s+control\s+order\b",
        re.I,
    ),
}

_TRADE_BARRIER_DIMENSIONS = {
    "tariffs": re.compile(r"\btariffs?\b", re.I),
    "import_export_duties": re.compile(r"\bimport\s+dut(?:y|ies)\b|\bexport\s+dut(?:y|ies)\b", re.I),
    "anti_dumping": re.compile(r"\banti[\s-]dumping\b|\banti[\s-]circumvention\b|\bsafeguard\s+duty\b", re.I),
    "trade_policy": re.compile(
        r"\bforeign\s+trade\s+policy\b|\bITC\s*\(\s*HS\s*\)\b|\bexport\s+incentives?\b|\bimport\s+quotas?\b",
        re.I,
    ),
}


def _score_from_dimensions(found):
    if not found:
        return None
    return {1: 2, 2: 3, 3: 4}.get(len(found), 5)


def score_regulatory_barriers(text):
    """F.4.1 - Regulatory barriers. Spec: Barrier Score (1-5): strength
    and durability of regulatory barriers. Deterministic (no LLM) -
    counted across four real, generic dimensions (regulatory-approval
    regime, licence-to-operate language, mining/resource lease
    dependence, mandatory standards/certification). Returns
    {'regulatory_barrier_dimensions','regulatory_barrier_score'} or
    all-None if none of the four dimensions were found (a real, common
    case for lightly-regulated businesses)."""
    if not text:
        return {"regulatory_barrier_dimensions": None, "regulatory_barrier_score": None}
    found = [dim for dim, pat in _REGULATORY_BARRIER_DIMENSIONS.items() if pat.search(text)]
    score = _score_from_dimensions(found)
    if score is None:
        return {"regulatory_barrier_dimensions": None, "regulatory_barrier_score": None}
    return {"regulatory_barrier_dimensions": found, "regulatory_barrier_score": score}


def score_trade_barriers(text):
    """F.4.2 - Trade barriers. Spec: Trade Barrier Exposure Score
    (1-5). Deterministic (no LLM) - counted across four real, generic
    dimensions (tariffs, import/export duties, anti-dumping/safeguard
    duty, trade-policy references including ITC(HS)/Foreign Trade
    Policy/export incentives/import quotas). Returns
    {'trade_barrier_dimensions','trade_barrier_score'} or all-None if
    none of the four dimensions were found (a real, common case for
    domestically-focused, non-traded businesses)."""
    if not text:
        return {"trade_barrier_dimensions": None, "trade_barrier_score": None}
    found = [dim for dim, pat in _TRADE_BARRIER_DIMENSIONS.items() if pat.search(text)]
    score = _score_from_dimensions(found)
    if score is None:
        return {"trade_barrier_dimensions": None, "trade_barrier_score": None}
    return {"trade_barrier_dimensions": found, "trade_barrier_score": score}
