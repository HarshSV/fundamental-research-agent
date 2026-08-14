"""
B.1.1-B.1.3 — Founders/CEO track record: deterministic (no-LLM) scorers.

Same design as tools/moat_brand_scoring.py (A.2.A): regex/keyword pattern
matching against real Annual Report text only, no LLM call. Chosen because
this codebase currently has no active LLM API key wired for qualitative
analysis - every score here traces to a literal matched sentence, never a
paraphrase, and is fully reproducible without any external API dependency.

Cruder than an LLM read (can't catch phrasing outside its keyword lists),
but that crudeness is explicit and auditable: a sub-point either finds a
literal match or reports "not found", never invents/guesses.
"""

import re

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ABBREV_PROTECT = re.compile(r"\b(Mr|Mrs|Ms|Dr|Shri|Smt|Prof|Sr|Jr|w\.e\.f|No)\.")


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    # Protect common abbreviations (Mr./Ms./Dr./w.e.f./...) from being
    # mistaken for sentence-ending periods before splitting - otherwise
    # "Mr. Ravi Shankar, CEO..." splits into "Mr." + "Ravi Shankar, CEO...",
    # silently dropping the name from the sentence a role/date is found in.
    protected = _ABBREV_PROTECT.sub(lambda m: m.group(1) + "․", normalized)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [s.replace("․", ".").strip() for s in parts if s.strip()]


def _band_score_pct(pct):
    """Shared 0-100% -> 1-5 banding, per the spec's fixed thresholds."""
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
# B.1.1 - Past successes / failures
# ---------------------------------------------------------------------------

# A sentence must carry an INITIATIVE keyword before its outcome is judged at
# all - otherwise generic narrative ("we remain committed to excellence")
# would get swept in as a false "ongoing" initiative.
_INITIATIVE_KEYWORDS = re.compile(
    r"\b(?:commission(?:ed|ing)?|expansion|expand(?:ed|ing)?|acquisition|acquir(?:ed|ing)?|"
    r"divest(?:ed|iture|ment)?|restructur(?:ed|ing)?|greenfield|brownfield|new plant|"
    r"new facility|capacity addition|capex project|launch(?:ed|ing)?\s+(?:of\s+)?(?:a|the|our)?\s*new|"
    r"turnaround|joint venture|merger)\b", re.I
)

# Outcome keyword tiers, checked in this priority order per sentence so a
# negative/uncertain signal is never masked by an incidental positive word
# in the same sentence (e.g. "the expansion was delayed despite strong
# demand" must classify as delayed, not success).
_OUTCOME_PATTERNS = [
    ("failed", re.compile(r"\b(?:failed|discontinued|shut down|written off|impair(?:ed|ment)|abandon(?:ed|ing)?|called off|scrapped)\b", re.I)),
    ("delayed", re.compile(r"\b(?:delayed|postponed|deferred|pushed back|behind schedule|slippage)\b", re.I)),
    ("ongoing", re.compile(r"\b(?:underway|in progress|on track|is being|continues? to|expected to (?:complete|commission)|will be commissioned|planned for (?:FY|20))\b", re.I)),
    ("success", re.compile(r"\b(?:successfully|completed|achieved|commissioned|delivered|record\b|on time and on budget|ahead of schedule|exceeded)\b", re.I)),
]


def classify_initiatives(text):
    """Returns a list of {label, outcome} for every sentence in `text` that
    names a strategic initiative AND states a classifiable outcome. A
    sentence naming an initiative with no matched outcome keyword is
    skipped entirely (never guessed into a bucket)."""
    out = []
    for sent in _sentences(text):
        if not _INITIATIVE_KEYWORDS.search(sent):
            continue
        outcome = None
        for label, pat in _OUTCOME_PATTERNS:
            if pat.search(sent):
                outcome = label
                break
        if outcome is None:
            continue
        out.append({"label": sent[:220].strip(), "outcome": outcome})
    return out


def score_initiative_success_rate(year_texts):
    """`year_texts`: list of {'fiscal_year', 'milestones_text'}. Returns
    {'initiative_success_rate_pct', 'execution_score', 'initiatives',
    'successful_count','delayed_count','failed_count','ongoing_count'} or
    all-None fields if no classifiable initiative is found in any year."""
    initiatives = []
    for yt in year_texts or []:
        for it in classify_initiatives(yt.get("milestones_text") or ""):
            initiatives.append({**it, "fiscal_year": yt.get("fiscal_year")})
    initiatives = initiatives[:25]
    if not initiatives:
        return {
            "initiative_success_rate_pct": None, "execution_score": None, "initiatives": [],
            "successful_count": 0, "delayed_count": 0, "failed_count": 0, "ongoing_count": 0,
        }
    successful = sum(1 for it in initiatives if it["outcome"] == "success")
    delayed = sum(1 for it in initiatives if it["outcome"] == "delayed")
    failed = sum(1 for it in initiatives if it["outcome"] == "failed")
    ongoing = sum(1 for it in initiatives if it["outcome"] == "ongoing")
    total = len(initiatives)
    pct = round(100 * successful / total, 1)
    return {
        "initiative_success_rate_pct": pct, "execution_score": _band_score_pct(pct), "initiatives": initiatives,
        "successful_count": successful, "delayed_count": delayed, "failed_count": failed, "ongoing_count": ongoing,
    }


# ---------------------------------------------------------------------------
# B.1.2 - Management tenure
# ---------------------------------------------------------------------------

_ROLE_PATTERNS = [
    ("CEO", re.compile(r"\bChief Executive Officer\b|\bCEO\b")),
    ("CFO", re.compile(r"\bChief Financial Officer\b|\bCFO\b")),
    ("Managing Director", re.compile(r"\bManaging Director\b")),
    ("Executive Director", re.compile(r"\bExecutive Director\b")),
]

# Deliberately restricted to an explicit APPOINTMENT DATE/YEAR pattern near
# the role - NOT a bare "N years" phrase, since that's routinely used for
# total career/industry experience (confirmed false-positive from live
# testing: "30 years of experience across FMCG..." is NOT company tenure).
_SINCE_YEAR = re.compile(r"\bsince\s+(?:\w+\s+)?(\d{4})\b", re.I)
_WEF_DATE = re.compile(r"\bw\.?e\.?f\.?\s*(?:\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s+)?(\d{4})\b", re.I)
_APPOINTED_YEAR = re.compile(r"\bappointed\b[^.]{0,60}?\b(?:on|in|w\.?e\.?f\.?)?\s*(?:\w+\s+)?(\d{4})\b", re.I)
_NAME_NEAR = re.compile(r"\b(?:Mr\.?|Ms\.?|Mrs\.?|Shri|Smt\.?|Dr\.?)\s+([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,3})")


def extract_key_executive_tenure(tenure_text, fiscal_year):
    """Finds named individuals EXPLICITLY holding a CEO/CFO/Managing
    Director/Executive Director role with an EXPLICIT appointment
    year/date nearby (since/w.e.f./appointed <year>) and computes their
    tenure as (fiscal_year - appointment_year). Returns a list of
    {'name','role','tenure_years','detail'} - empty if none found. Never
    guesses a date, and only counts a company-tenure signal (appointment
    date), never a bare years-of-experience phrase."""
    if not tenure_text or not fiscal_year:
        return []
    out = []
    seen = set()
    for sent in _sentences(tenure_text):
        role = None
        for role_label, pat in _ROLE_PATTERNS:
            if pat.search(sent):
                role = role_label
                break
        if not role:
            continue
        year = None
        for pat in (_SINCE_YEAR, _WEF_DATE, _APPOINTED_YEAR):
            m = pat.search(sent)
            if m:
                year = int(m.group(1))
                break
        if year is None or year < 1950 or year > fiscal_year:
            continue
        name_m = _NAME_NEAR.search(sent)
        name = name_m.group(0).strip() if name_m else f"Unnamed {role}"
        key = (name, role)
        if key in seen:
            continue
        seen.add(key)
        tenure_years = round(max(0.0, fiscal_year - year), 1)
        out.append({
            "name": name, "role": role, "tenure_years": tenure_years,
            "detail": sent[:220].strip(),
        })
    return out[:10]


def score_management_tenure(tenure_text, fiscal_year):
    """Returns {'average_tenure_years','tenure_score','executives'} or
    all-None if no named CEO/CFO/Executive Director tenure was located."""
    execs = extract_key_executive_tenure(tenure_text, fiscal_year)
    if not execs:
        return {"average_tenure_years": None, "tenure_score": None, "executives": []}
    avg = round(sum(e["tenure_years"] for e in execs) / len(execs), 1)
    score = 5 if avg > 10 else 4 if avg >= 7 else 3 if avg >= 4 else 2 if avg >= 2 else 1
    return {"average_tenure_years": avg, "tenure_score": score, "executives": execs}


# ---------------------------------------------------------------------------
# B.1.3 - Relevance to current strategy
# ---------------------------------------------------------------------------

# Fixed taxonomy of common strategic-priority areas Indian ARs actually use,
# each with (a) a "priority" phrasing pattern to detect the company STATING
# it as a current focus, and (b) an "experience" phrasing pattern to detect
# a director's background EXPLICITLY in that same area. A category counts
# as a "matched priority" only when BOTH fire.
_STRATEGY_CATEGORIES = {
    "Digital / technology": {
        "priority": re.compile(r"\bdigital(?:\s+transformation|\s+strategy|\s+initiatives?)?\b|\btechnology\s+(?:strategy|led|focus|adoption)\b|\bartificial intelligence\b|\bAI\b", re.I),
        "experience": re.compile(r"\bdigital\b.{0,40}\bexperience\b|\btechnology\b.{0,40}\bexperience\b|\bIT\s+industry\b|\bsoftware\b.{0,30}\bexperience\b", re.I),
    },
    "Retail / consumer": {
        "priority": re.compile(r"\bretail\s+(?:expansion|strategy|footprint|focus)\b|\bconsumer\s+(?:business|segment|focus)\b", re.I),
        "experience": re.compile(r"\bretail\b.{0,40}\bexperience\b|\bconsumer (?:goods|products)\b.{0,40}\bexperience\b|\bFMCG\b", re.I),
    },
    "Manufacturing / operations": {
        "priority": re.compile(r"\bmanufacturing\s+(?:excellence|expansion|strategy|capacity)\b|\boperational excellence\b", re.I),
        "experience": re.compile(r"\bmanufacturing\b.{0,40}\bexperience\b|\boperations\b.{0,40}\bexperience\b|\bplant\b.{0,30}\bexperience\b", re.I),
    },
    "Exports / international": {
        "priority": re.compile(r"\bexport\s+(?:growth|markets?|strategy)\b|\binternational\s+(?:expansion|markets?|business)\b|\bglobal\s+expansion\b", re.I),
        "experience": re.compile(r"\binternational\b.{0,40}\bexperience\b|\bglobal\b.{0,40}\bexperience\b|\boverseas\b.{0,30}\bexperience\b", re.I),
    },
    "Energy transition / sustainability": {
        "priority": re.compile(r"\benergy transition\b|\brenewable(?:s|energy)?\b|\bsustainab(?:le|ility)\b|\bnet[- ]zero\b|\bESG\b", re.I),
        "experience": re.compile(r"\brenewable\b.{0,40}\bexperience\b|\benergy (?:sector|industry)\b.{0,40}\bexperience\b|\bsustainability\b.{0,40}\bexperience\b", re.I),
    },
    "Capacity expansion": {
        "priority": re.compile(r"\bcapacity\s+(?:expansion|addition|augmentation)\b|\bgreenfield\b|\bbrownfield\b", re.I),
        "experience": re.compile(r"\bproject (?:execution|management)\b.{0,40}\bexperience\b|\bcapex\b.{0,40}\bexperience\b", re.I),
    },
    "Finance / M&A": {
        "priority": re.compile(r"\bcapital allocation\b|\bmergers?\s*(?:&|and)\s*acquisitions?\b|\bM&A\b|\bdeleveraging\b", re.I),
        "experience": re.compile(r"\bfinance\b.{0,40}\bexperience\b|\binvestment banking\b|\bcorporate finance\b.{0,40}\bexperience\b", re.I),
    },
    "Brand / marketing": {
        "priority": re.compile(r"\bbrand building\b|\biconic brands?\b|\bmarketing (?:strategy|moats?|capabilit)\b|\bpremiumi[sz]ation\b|\bportfolio of brands\b", re.I),
        "experience": re.compile(r"\bmarketing\b.{0,40}\bexperience\b|\bbrand (?:management|building)\b.{0,40}\bexperience\b|\bconsumer marketing\b", re.I),
    },
    "R&D / innovation": {
        "priority": re.compile(r"\bpurposeful innovation\b|\bR&D\b|\bresearch\s*(?:&|and)\s*development\b|\bproduct innovation\b|\btechnology[- ]led innovation\b", re.I),
        "experience": re.compile(r"\bR&D\b.{0,40}\bexperience\b|\binnovation\b.{0,40}\bexperience\b|\bproduct development\b.{0,40}\bexperience\b", re.I),
    },
    "Route-to-market / distribution": {
        "priority": re.compile(r"\broute[- ]to[- ]market\b|\bdistribution (?:network|strategy|reach)\b|\bchannel (?:expansion|strategy|moats?)\b|\be-commerce\b|\bomnichannel\b", re.I),
        "experience": re.compile(r"\bdistribution\b.{0,40}\bexperience\b|\bsales\b.{0,40}\bexperience\b|\bsupply chain\b.{0,40}\bexperience\b|\bgo-to-market\b", re.I),
    },
}


def classify_strategy_alignment(strategy_text):
    """Returns {'strategic_priorities','matched_areas'} using the fixed
    taxonomy above - a category is a 'priority' only if the priority
    pattern fires anywhere in the text, and 'matched' only if the
    experience pattern ALSO fires. Never fabricates a category outside
    this fixed, auditable list."""
    if not strategy_text:
        return {"strategic_priorities": [], "matched_areas": []}
    priorities, matched = [], []
    for label, pats in _STRATEGY_CATEGORIES.items():
        if pats["priority"].search(strategy_text):
            priorities.append(label)
            if pats["experience"].search(strategy_text):
                matched.append(label)
    return {"strategic_priorities": priorities, "matched_areas": matched}


def score_strategy_alignment(strategy_text):
    """Returns {'strategy_alignment_pct','alignment_score','alignment',
    'strategic_priorities','matched_areas'} - all None/empty if the text
    names no priority from the fixed taxonomy."""
    c = classify_strategy_alignment(strategy_text)
    priorities, matched = c["strategic_priorities"], c["matched_areas"]
    if not priorities:
        return {
            "strategy_alignment_pct": None, "alignment_score": None, "alignment": None,
            "strategic_priorities": [], "matched_areas": [],
        }
    pct = round(100 * len(matched) / len(priorities), 1)
    score = _band_score_pct(pct)
    label = "High" if score >= 4 else "Moderate" if score == 3 else "Low"
    return {
        "strategy_alignment_pct": pct, "alignment_score": score, "alignment": label,
        "strategic_priorities": priorities, "matched_areas": matched,
    }
