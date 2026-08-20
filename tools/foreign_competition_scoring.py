"""
F.5.1/F.5.2 - Foreign competitors: ability of global players to enter
India or export competition. Deterministic (no-LLM) scorers over real
Annual Report MD&A text. Generic keyword/regex logic, not
ticker-specific.

Real Indian ARs (TATASTEEL, CIPLA, ULTRACEMCO confirmed by direct
inspection) discuss foreign/import competition unevenly by sector -
TATASTEEL explicitly discusses "excessive imports" and China's export
volumes pressuring domestic prices; ULTRACEMCO (cement, not
economically tradable over long distances) barely mentions import
competition at all. That sector-driven unevenness is real and expected,
not a fetch bug.
"""
import re

_FOREIGN_PRESENCE_DIMENSIONS = {
    "named_country_source": re.compile(
        r"\bimports?\s+from\s+china\b|\bchinese\s+(?:players|competitors|companies|imports|manufacturers)\b",
        re.I,
    ),
    "global_players": re.compile(
        r"\bglobal\s+players\b|\bmultinational\s+(?:companies|corporations)\b|"
        r"\binternational\s+competitors?\b|\bforeign\s+(?:players|competitors|companies)\b",
        re.I,
    ),
    "export_competition": re.compile(
        r"\bexport\s+markets?\b.{0,60}\b(?:competit|pressure)|\bexport\s+levels?\b.{0,40}\bpressure",
        re.I | re.S,
    ),
    "import_pressure": re.compile(
        r"\bexcessive\s+imports\b|\bimport\s+(?:pressures?|surge)\b",
        re.I,
    ),
}

_IMPORT_COMPETITION_DIMENSIONS = {
    "cheap_imports": re.compile(r"\bcheap(?:er)?\s+imports?\b|\blow[\s-]cost\s+imports?\b", re.I),
    "anti_dumping": re.compile(r"\banti[\s-]dumping\b|\bdumping\s+(?:duty|from|by)\b|\bsafeguard\s+duty\b", re.I),
    "import_duty_policy": re.compile(
        r"\bimport\s+dut(?:y|ies)\b|\bimport\s+quotas?\b|\bimport\s+polic(?:y|ies)\b|"
        r"\bcustoms?\s+duty\s+on\s+imports?\b|\bITC\s*\(\s*HS\s*\)\b",
        re.I,
    ),
    "import_pressure": re.compile(
        r"\bexcessive\s+imports\b|\bimport\s+(?:pressures?|surge)\b|\bimport\s+substitution\b",
        re.I,
    ),
}


def _score_from_dimensions(found):
    if not found:
        return None
    return {1: 2, 2: 3, 3: 4}.get(len(found), 5)


def score_foreign_competitor_presence(text):
    """F.5.1 - Foreign Competitor Presence. Spec: Foreign Competition
    Score (1-5). Deterministic (no LLM) - counted across four real,
    generic dimensions (named foreign/China-sourced competition, global/
    multinational player mentions, export-market competitive pressure,
    general import pressure language) rather than requiring named
    international competitors, which real Indian AR MD&A rarely
    provides. Returns {'presence_dimensions','foreign_competition_score'}
    or all-None if none of the four dimensions were found (a real,
    common case for domestically-consumed, non-tradable products)."""
    if not text:
        return {"presence_dimensions": None, "foreign_competition_score": None}
    found = [dim for dim, pat in _FOREIGN_PRESENCE_DIMENSIONS.items() if pat.search(text)]
    score = _score_from_dimensions(found)
    if score is None:
        return {"presence_dimensions": None, "foreign_competition_score": None}
    return {"presence_dimensions": found, "foreign_competition_score": score}


def score_import_competition(text):
    """F.5.2 - Import competition. Spec: Import Competition Score (1-5).
    Deterministic (no LLM) - counted across four real, generic
    dimensions (cheap/low-cost imports, anti-dumping/safeguard duty,
    import duty/quota/policy references including ITC(HS), general
    import pressure/substitution language). Returns
    {'import_dimensions','import_competition_score'} or all-None if none
    of the four dimensions were found (a real, common case)."""
    if not text:
        return {"import_dimensions": None, "import_competition_score": None}
    found = [dim for dim, pat in _IMPORT_COMPETITION_DIMENSIONS.items() if pat.search(text)]
    score = _score_from_dimensions(found)
    if score is None:
        return {"import_dimensions": None, "import_competition_score": None}
    return {"import_dimensions": found, "import_competition_score": score}
