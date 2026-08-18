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
# "expand(?:ed|ing)?" alone is deliberately excluded - confirmed real false
# positive: "India's young and expanding population continues to fuel
# consumption" matched as an "ongoing initiative" via bare "expanding" +
# "continues to", though it names no company initiative at all. Only the
# noun "expansion" (still generic, but rarer as a false match) and
# capacity/plant/facility-qualified expansion phrasing are kept.
_INITIATIVE_KEYWORDS = re.compile(
    r"\b(?:commission(?:ed|ing)?|expansion|capacity expansion|expand(?:ed|ing)?\s+(?:capacity|our\s+plant|the\s+plant|production|manufacturing)|"
    r"acquisition|acquir(?:ed|ing)?|"
    r"divest(?:ed|iture|ment)?|restructur(?:ed|ing)?|greenfield|brownfield|new plant|"
    r"new facility|capacity addition|capex project|launch(?:ed|ing)?\s+(?:of\s+)?(?:a|the|our)?\s*new|"
    r"turnaround|joint venture|merger)\b", re.I
)

# Outcome keyword tiers, checked in this priority order per sentence so a
# negative/uncertain signal is never masked by an incidental positive word
# in the same sentence (e.g. "the expansion was delayed despite strong
# demand" must classify as delayed, not success). "continues? to" alone is
# deliberately excluded from "ongoing" - too generic, matches any continuous
# action (a macro/demographic remark, not necessarily a company initiative).
_OUTCOME_PATTERNS = [
    ("failed", re.compile(r"\b(?:failed|discontinued|shut down|written off|impair(?:ed|ment)|abandon(?:ed|ing)?|called off|scrapped)\b", re.I)),
    ("delayed", re.compile(r"\b(?:delayed|postponed|deferred|pushed back|behind schedule|slippage)\b", re.I)),
    ("ongoing", re.compile(r"\b(?:underway|in progress|on track|is being commissioned|is being built|expected to (?:complete|commission)|will be commissioned|planned for (?:FY|20))\b", re.I)),
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

_TENURE_BUCKETS = [(">10Y", 10, None), ("7-10Y", 7, 10), ("4-7Y", 4, 7), ("2-4Y", 2, 4), ("<2Y", 0, 2)]


def _tenure_bucket_for(years):
    for label, lo, hi in _TENURE_BUCKETS:
        if hi is None:
            if years > lo:
                return label
        elif (lo <= years < hi) if lo > 0 else (years < hi):
            return label
    return "<2Y"


_ROLE_PATTERNS = [
    ("CEO", re.compile(r"\bChief Executive Officer\b|\bCEO\b")),
    ("CFO", re.compile(r"\bChief Financial Officer\b|\bCFO\b")),
    # "Non Managing Director" / "Non-Managing Director" (opposite meaning)
    # excluded the same way as "Non-Executive Director" below - confirmed
    # real false-positive (WIPRO).
    ("Managing Director", re.compile(r"(?<!non-)(?<!non )(?<!non\s)Managing Director")),
    # Negative lookbehind excludes "Non-Executive Director" - a board
    # classification meaning NOT part of day-to-day management, the
    # opposite of what this role label is meant to capture. Confirmed real
    # false-positive from live testing (TCS: an Independent, Non-Executive
    # Director was being counted as an "Executive Director").
    ("Executive Director", re.compile(r"(?<!Non-)(?<!Non )\bExecutive Director\b")),
]

# Deliberately restricted to an explicit APPOINTMENT DATE/YEAR pattern near
# the role - NOT a bare "N years" phrase, since that's routinely used for
# total career/industry experience (confirmed false-positive from live
# testing: "30 years of experience across FMCG..." is NOT company tenure).
_SINCE_YEAR = re.compile(r"\bsince\s+(?:\w+\s+)?(\d{4})\b", re.I)
_WEF_DATE = re.compile(r"\bw\.?e\.?f\.?\s*(?:\d{1,2}(?:st|nd|rd|th)?\s+\w+,?\s+)?(\d{4})\b", re.I)
_APPOINTED_YEAR = re.compile(r"\bappointed\b[^.]{0,60}?\b(?:on|in|w\.?e\.?f\.?)?\s*(?:\w+\s+)?(\d{4})\b", re.I)
# [ \t]+ (not \s+) between words - a bare \s+ lets this swallow the NEXT
# LINE's text across a newline in PDF-linearized tables (confirmed real
# bug: "Ms. Tulsi Naidu\nNon-Executive..." matched "Ms. Tulsi Naidu\nNon"
# as one name, pulling in the next row's leading word). Same fix already
# applied to _PLAIN_NAME below.
_NAME_NEAR = re.compile(r"\b(?:Mr\.?|Ms\.?|Mrs\.?|Shri|Smt\.?|Dr\.?)[ \t]+([A-Z][A-Za-z.]+(?:[ \t]+[A-Z][A-Za-z.]+){0,3})")

# A Board of Directors / KMP table routinely lists a bare date (16/02/2020,
# "16th February, 2020", OR month-first "June 1, 2023" - confirmed all three
# in real filings) with NO "since"/"w.e.f."/"appoint" wording anywhere near
# the individual row at all (that phrasing, if present, is usually only in
# a column HEADER once, far outside any single row's proximity window). The
# _fetch_ar_text_sections anchor that located this text already required a
# governance/appointment-context phrase (see _FOUNDER_TRACK_RECORD_ANCHORS'
# "tenure" anchors) to find this excerpt in the first place, so a bare full
# date next to a named role here is not read in isolation - it's already
# inside a section established to be about director appointments.
_BARE_DATE_NUMERIC = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.](\d{4})\b")
_MONTHS = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
_BARE_DATE_DAY_MONTH = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTHS})\.?,?\s+(\d{{4}})\b", re.I)
_BARE_DATE_MONTH_DAY = re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)

# Marks a resignation/cessation notice - the nearby date is when someone
# LEFT the role, not when they joined it.
_CESSATION_CTX = re.compile(r"\bceas(?:ed|ation|es)\b|\bstepped down\b|\bresign(?:ed|ation)\b|\bretir(?:ed|ement)\b(?!\s+benefit)", re.I)

# "as on <date>" / "as at <date>" marks a REPORT snapshot date ("shareholding
# as on March 31, 2026"), not an appointment date - confirmed real
# false-positive (RELIANCE: "Directorships of other Boards as on March 31,
# 2026" near an unrelated director's OTHER-company directorship was read as
# a Reliance appointment date).
_REPORT_DATE_CTX = re.compile(r"\bas\s+(?:on|at)\b", re.I)

# A plain (no Mr./Ms./Shri prefix) Title-Case name - the common table format
# ("Rajesh Gopinathan  00029794  CEO & MD  16/02/2020") has no honorific,
# and a DIN/number often sits BETWEEN the name and the role, so this is
# searched across the whole window (not just immediately-before) and the
# CLOSEST match to the role wins. Requires lowercase letters after the
# first (real names are Title Case) so it can't match an all-caps table
# header token like "DIN" or "CEO" itself, and a stopword filter excludes
# generic table-header phrases ("Date Of", "Name Of", ...). The first token
# may also be a bare single-letter initial ("K Krithivasan", "N
# Chandrasekaran") - a common Indian-AR naming convention confirmed missed
# entirely by the full-word-only version during live testing.
_PLAIN_NAME = re.compile(r"\b([A-Z](?:[a-z]+|\.)?(?:[ \t]+[A-Z][a-z]+){1,3})\b")
_NAME_STOPWORD_PHRASES = (
    "date of", "name of", "chief executive", "chief financial", "managing director",
    "executive director", "board of", "key managerial", "annual report",
    "corporate governance", "particulars of", "listed unlisted", "limited executive",
    # Recurring "area of expertise" / table-header phrases near director
    # tables that are NOT names, confirmed real false-positives from live
    # testing (INFY's "Information Technology" expertise tag matched as if
    # it were a director's name).
    "information technology", "human resources", "risk management",
    "financial services", "capital markets", "term ending", "areas of",
    "date of appointment", "date of reappointment", "areas of expertise",
    "audit committee", "remuneration committee", "stakeholders relationship",
    # AGM Notice / resolution boilerplate, confirmed real false-positive
    # (RELIANCE: "Ordinary Resolution" matched as if it were a name).
    "ordinary resolution", "special resolution", "item no", "notice of",
    "postal ballot", "explanatory statement",
)
# A candidate ending in a company-entity suffix is a company name, not a
# person - confirmed real false-positive (INFY: "Infosys Limited" matched
# as if it were a director's name from a directorship-listing table).
_NAME_ENTITY_SUFFIX = re.compile(r"\b(?:Limited|Ltd\.?|LLP|Inc\.?|Corp\.?|Pvt\.?)\b", re.I)
_NAME_STOPWORD_FIRST_WORDS = {
    "date", "name", "designation", "appointment", "particulars", "director",
    "key", "board", "annual", "report", "corporate", "company", "membership",
    "chairpersonship", "committee", "listed", "unlisted", "nominee", "din",
}


def _find_appointment_year(window, fiscal_year):
    """Returns the appointment year found in `window` via any of: an
    explicit since/w.e.f./appointed-<year> phrase, or a bare full date
    (numeric DD/MM/YYYY, "DDth Month YYYY", or "Month DD, YYYY") near the
    role - the caller already only scans windows around a named
    CEO/CFO/Managing/Executive Director role INSIDE a section anchored on
    governance/appointment context, so a bare date there is not read in
    total isolation. Never a bare YEAR alone with no date/since/w.e.f.
    structure (too easy to collide with an unrelated year mention)."""
    for pat in (_SINCE_YEAR, _WEF_DATE, _APPOINTED_YEAR):
        m = pat.search(window)
        if m:
            return int(m.group(1))
    for pat in (_BARE_DATE_NUMERIC, _BARE_DATE_DAY_MONTH, _BARE_DATE_MONTH_DAY):
        for m in pat.finditer(window):
            # A "as on"/"as at" phrase immediately before THIS specific date
            # match marks it as a report-snapshot date, not an appointment
            # date - checked locally (not window-wide) since the window can
            # legitimately contain both kinds of date in different spots.
            local_before = window[max(0, m.start() - 20):m.start()]
            if _REPORT_DATE_CTX.search(local_before):
                continue
            y = int(m.group(1))
            if 1950 <= y <= fiscal_year:
                return y
    return None


def _closest_name(window, role_pos_in_window):
    """Every honorific-prefixed and plain-Title-Case name candidate in
    `window`, whichever is closest (by character distance) to the role
    mention wins - guards against a window with two directors' names both
    present picking up the WRONG one (e.g. the CFO's name when scoring the
    CEO's row). A candidate BEFORE the role match is preferred over one
    AFTER it at the same distance (a director listing's own name routinely
    precedes its role/designation text; a long multi-title designation
    string - e.g. "Executive Director, Chief Executive Officer and
    Managing Director" - can push the row's OWN name further back than
    the NEXT row's name sitting just after the match, which would
    otherwise win purely on raw distance - confirmed real bug live)."""
    candidates = []
    for m in _NAME_NEAR.finditer(window):
        before = m.start() < role_pos_in_window
        candidates.append((abs(m.start() - role_pos_in_window), 0 if before else 1, m.group(0).strip()))
    for m in _PLAIN_NAME.finditer(window):
        cand = m.group(1).strip()
        low = cand.lower()
        if any(sw in low for sw in _NAME_STOPWORD_PHRASES):
            continue
        if low.split()[0] in _NAME_STOPWORD_FIRST_WORDS:
            continue
        if _NAME_ENTITY_SUFFIX.search(cand):
            continue
        before = m.start() < role_pos_in_window
        candidates.append((abs(m.start() - role_pos_in_window), 0 if before else 1, cand))
    if not candidates:
        return None
    candidates = [(dist + (300 if side else 0), c) for dist, side, c in candidates]
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def extract_key_executive_tenure(tenure_text, fiscal_year):
    """Finds named individuals EXPLICITLY holding a CEO/CFO/Managing
    Director/Executive Director role with an EXPLICIT appointment
    year/date nearby (since/w.e.f./appointed <year>, OR a bare date next to
    an "appoint" context word - covers a separate appointment-date TABLE,
    not just a bio paragraph) and computes their tenure as (fiscal_year -
    appointment_year). Returns a list of {'name','role','tenure_years',
    'detail'} - empty if none found. Never guesses a date, and only counts
    a company-tenure signal (appointment date), never a bare
    years-of-experience phrase. Scans the raw text with a character-window
    proximity search (not sentence-bound) since PDF-linearized table rows
    routinely lack real sentence punctuation. Window is kept tight (150
    chars) specifically to avoid pulling in an ADJACENT director's name/date
    in a multi-row table.
    """
    if not tenure_text or not fiscal_year:
        return []
    out = []
    seen_names = set()
    text = tenure_text
    for role_label, pat in _ROLE_PATTERNS:
        for m in pat.finditer(text):
            start, end = m.start(), m.end()
            win_start = max(0, start - 150)
            window = text[win_start:end + 150]
            # A "Cessation" / resignation notice mentions the role and a
            # date too - but that date is when someone LEFT, not when they
            # joined. Confirmed real bug from live testing (HINDUNILVR: "Mr.
            # Rohit Jawa stepped down as ... Managing Director & CEO ... with
            # effect from close of business hours on 31st July, 2025" was
            # being read as his APPOINTMENT date, computing a near-zero
            # "tenure" for a departure, not a start). Skip the whole match -
            # a departing/departed executive isn't a current key executive.
            if _CESSATION_CTX.search(window):
                continue
            year = _find_appointment_year(window, fiscal_year)
            if year is None:
                continue
            name = _closest_name(window, start - win_start) or f"Unnamed {role_label}"
            # Dedup by NAME, not (name, role): a combined title like "Chief
            # Executive Officer and Managing Director" matches BOTH the CEO
            # and Managing Director role patterns for the SAME person - only
            # counting them once avoids double-weighting one executive's
            # tenure in the average (the spec's denominator is "Number of
            # Key Executives", not number of role mentions).
            tenure_years = round(max(0.0, fiscal_year - year), 1)
            if tenure_years > _MAX_PLAUSIBLE_TENURE_YEARS:
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            out.append({
                "name": name, "role": role_label, "tenure_years": tenure_years,
                "bucket": _tenure_bucket_for(tenure_years),
                "detail": window[:220].strip(),
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


# ---------------------------------------------------------------------------
# B.1.2 STRUCTURAL variant - reads a real detected table (pdfplumber) by
# COLUMN HEADER KEYWORD instead of matching exact wording in flowing text.
# This is the fix for the core limitation of the regex-window approach
# above: a company that titles its column "Appointed On" instead of "Date
# of Appointment" simply won't match _APPOINTED_YEAR/_BARE_DATE_* patterns
# wherever that phrase sits relative to a role mention, but WILL be found
# here via find_column's substring match on the actual header cell -
# generalizes across differently-worded filings far better, since it keys
# off table STRUCTURE (a real column exists) rather than exact phrasing.
# ---------------------------------------------------------------------------

_DATE_CELL_NUMERIC = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.](\d{4})\b")
_DATE_CELL_YEAR_ONLY = re.compile(r"\b(19|20)\d{2}\b")


def _year_from_date_cell(cell, fiscal_year):
    if not cell:
        return None
    for pat in (_DATE_CELL_NUMERIC, _BARE_DATE_DAY_MONTH, _BARE_DATE_MONTH_DAY):
        m = pat.search(cell)
        if m:
            y = int(m.group(1))
            if 1950 <= y <= fiscal_year:
                return y
    m = _DATE_CELL_YEAR_ONLY.search(cell)
    if m:
        y = int(m.group(0))
        if 1950 <= y <= fiscal_year:
            return y
    return None


_ROLE_CELL_PATTERNS = [
    ("CEO", re.compile(r"chief executive officer|\bceo\b", re.I)),
    ("CFO", re.compile(r"chief financial officer|\bcfo\b", re.I)),
    # "Non Managing Director" / "Non-Managing Director" is a real board
    # classification (opposite meaning) - confirmed real false-positive
    # (WIPRO: a Non-Managing Director was counted as a Managing Director).
    ("Managing Director", re.compile(r"(?<!non-)(?<!non )managing director", re.I)),
    ("Executive Director", re.compile(r"(?<!non-)(?<!non )executive director", re.I)),
]


_NAME_STRIP = re.compile(r"\([^)]*\)")
_HONORIFIC_STRIP = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Shri|Smt|Prof)\.?\b", re.I)
_NAME_JUNK = re.compile(r"[^A-Za-z\s]")


def _normalize_name_words(name):
    """A person's name reduced to its significant lowercase words - strips
    parenthetical annotations ("(NED)", "(i)"), honorifics, and punctuation,
    so the SAME person can be matched across two differently-formatted
    tables (e.g. "N Chandrasekaran, Chairman(i)" in one table vs "N.
    Chandrasekaran" in another)."""
    name = _NAME_STRIP.sub(" ", name or "")
    name = _HONORIFIC_STRIP.sub(" ", name)
    name = _NAME_JUNK.sub(" ", name)
    return {w.lower() for w in name.split() if len(w) > 1}


# A job-TITLE cell ("Executive Vice President & Head - Integrated Supply
# Chain") is often more alphabetic than the actual name cell in the same
# row, so a naive "most alphabetic cell = name" heuristic picks the title
# instead - confirmed real bug (JUBLFOOD: SVP-level titles were shown as
# if they were CEO/CFO people's names). A real person's name is short (1-5
# words) and never contains these role/function words.
_JOB_TITLE_WORDS = re.compile(
    r"\b(?:vice president|president|officer|head|manager|chief|business|strategy|"
    r"supply chain|human resources|operations|finance|legal|marketing|sales|"
    r"technology|information|corporate|director|division|department)\b", re.I
)


def _looks_like_person_name(cell):
    """Cheap shape check: a real name is a handful of short, mostly-
    alphabetic words with no job-title/function vocabulary in it."""
    if not cell or len(cell) > 40:
        return False
    if _JOB_TITLE_WORDS.search(cell):
        return False
    words = cell.split()
    if not (1 <= len(words) <= 5):
        return False
    return sum(ch.isalpha() or ch.isspace() for ch in cell) / max(len(cell), 1) > 0.7


# No realistic CEO/CFO/Managing/Executive Director tenure exceeds this -
# a value above it means the "date" cell almost certainly wasn't an
# appointment date at all (e.g. a date of birth or company-founding year
# grabbed by mistake) - confirmed real bug (a 58-year "tenure" was clearly
# a misread, not a real appointment-to-date span).
_MAX_PLAUSIBLE_TENURE_YEARS = 40


def _names_match(a, b):
    wa, wb = _normalize_name_words(a), _normalize_name_words(b)
    if not wa or not wb:
        return False
    overlap = wa & wb
    return len(overlap) >= 1 and len(overlap) / min(len(wa), len(wb)) >= 0.5


# A board-attendance/sitting-fee table routinely tags each director's row
# with a short category code in parentheses - NED (Non-Executive Director),
# ED (Executive Director), ID (Independent Director), MD (Managing
# Director) - a reliable, compact ROLE signal even when the table has no
# proper header row at all (confirmed real format live on TCS).
_ROLE_CODE = re.compile(r"\((NED|ED|ID|MD|CEO|CFO)\)")
_ROLE_CODE_LABEL = {"ED": "Executive Director", "MD": "Managing Director", "CEO": "CEO", "CFO": "CFO"}
_NON_EXEC_CODES = {"NED", "ID"}


def _extract_role_map_from_tables(tables):
    """Scans every row of every table for a name-like cell paired with
    either an explicit CEO/CFO/Managing/Executive Director phrase (see
    _ROLE_CELL_PATTERNS) or a parenthetical role code (see _ROLE_CODE) IN
    THE SAME ROW. Returns [{'name','role'}] for every row that resolves to
    an executive (non-NED/ID) role - used to cross-reference against a
    separate, cleaner appointment-date table that itself carries no role
    column (a very common real-world split across two different AR
    tables)."""
    out = []
    for table in tables or []:
        for row in table or []:
            cells = [(c or "").strip() for c in row]
            row_text = " ".join(cells)
            if not row_text.strip():
                continue
            role = None
            for role_label, pat in _ROLE_CELL_PATTERNS:
                if pat.search(row_text):
                    role = role_label
                    break
            if role is None:
                m = _ROLE_CODE.search(row_text)
                if m and m.group(1) not in _NON_EXEC_CODES:
                    role = _ROLE_CODE_LABEL.get(m.group(1))
            if role is None:
                continue
            name_candidates = [c for c in cells if _looks_like_person_name(c)]
            if not name_candidates:
                continue
            name_cell = max(name_candidates, key=lambda c: sum(ch.isalpha() for ch in c))
            if len(_normalize_name_words(name_cell)) >= 1:
                out.append({"name": name_cell, "role": role})
    return out


def extract_key_executive_tenure_from_tables(tables, fiscal_year, role_tables=None):
    """Structural counterpart to extract_key_executive_tenure: finds a
    Name+Date-of-Appointment table by VALUE PATTERN (not header wording -
    works even when pdfplumber fails to detect a proper header row, a
    confirmed real gap: TCS's own appointment table starts directly at
    data row 1). If that table carries no role/designation column itself
    (also common - role info is routinely on a SEPARATE page/table), cross-
    references names against `role_tables` (any tables scanned for role
    signals, e.g. a board-attendance table with (NED)/(ED)/(ID) tags) via
    fuzzy name matching. Returns a list of {'name','role','tenure_years',
    'bucket','detail'} - empty if no table yields a name+date pair that
    also resolves to a confirmed executive role."""
    from tools.ar_table_extractor import find_column
    role_map = _extract_role_map_from_tables(role_tables) if role_tables else []

    out = []
    seen_names = set()
    for table in tables or []:
        if not table or len(table) < 2:
            continue
        header = table[0]
        name_col = find_column(header, ["name"])
        date_col = find_column(header, ["date of appointment", "appointment", "date"])
        role_col = find_column(header, ["designation", "position", "role", "category"])
        header_has_names = name_col is not None and date_col is not None
        rows = table[1:] if header_has_names else table

        for row in rows:
            cells = [(c or "").strip() for c in row]
            if header_has_names:
                if max(name_col, date_col) >= len(cells):
                    continue
                name = cells[name_col]
                date_cell = cells[date_col]
                role_cell = cells[role_col] if role_col is not None and role_col < len(cells) else ""
            else:
                # No usable header - value-pattern fallback: the date cell
                # is whichever cell parses as a date, the name cell is
                # whichever OTHER cell is mostly alphabetic.
                date_cell = next((c for c in cells if _year_from_date_cell(c, fiscal_year) is not None), "")
                if not date_cell:
                    continue
                name_candidates = [c for c in cells if c != date_cell and _looks_like_person_name(c)]
                name = max(name_candidates, key=lambda c: sum(ch.isalpha() for ch in c)) if name_candidates else ""
                role_cell = ""

            if not name or len(name) < 3 or not date_cell:
                continue
            year = _year_from_date_cell(date_cell, fiscal_year)
            if year is None:
                continue
            tenure_years = round(max(0.0, fiscal_year - year), 1)
            if tenure_years > _MAX_PLAUSIBLE_TENURE_YEARS:
                continue

            role = None
            for role_label, pat in _ROLE_CELL_PATTERNS:
                if role_cell and pat.search(role_cell):
                    role = role_label
                    break
            if role is None and role_map:
                match = next((rm for rm in role_map if _names_match(name, rm["name"])), None)
                if match:
                    role = match["role"]
            if role is None:
                continue

            if name in seen_names:
                continue
            seen_names.add(name)
            out.append({
                "name": name, "role": role, "tenure_years": tenure_years,
                "bucket": _tenure_bucket_for(tenure_years),
                "detail": f"Table row: {name} | {role_cell or '(role via cross-reference)'} | {date_cell}",
            })
    return out[:10]
