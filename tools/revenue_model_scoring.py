"""
A.3 — Revenue model quality: deterministic (no-LLM) contract-type
classifier, mirroring the A.2.x moat scorers' regex/anchor pattern (see
tools/moat_switching_costs_scoring.py) but classifying a CONTRACT TYPE
(3A/3B/3C of the spec) instead of a 0-5 rubric.

Classification (per the spec's exact wording):
  3A Transactional — revenue recognised AT A POINT IN TIME with no ongoing
     service obligation ("revenue ... recognised at the point in time when
     control ... is transferred").
  3B Recurring — repeat/subscription billing recognised OVER TIME, WITHOUT
     a stated fixed contractual term. If a specific duration IS stated,
     it's Annuity, not Recurring — the defined-term anchor is the
     deciding factor between the two.
  3C Annuity — contractual periodic payments over a DEFINED term (AMC/O&M/
     service contracts with a stated tenure, e.g. "5-year O&M agreement").

Deliberately does NOT call any LLM — same rationale as the A.2.x factors
(reproducible, auditable, avoids the shared Groq/OpenRouter quota).

3D Contract renewal rate is scored SEPARATELY here (see
`extract_renewal_rate_pct`) — only populated when an actual disclosed
PERCENTAGE for this specific ratio is found, never for a qualitative claim
like "high renewal rates" (per the mandatory no-fabrication rule in the
spec and CLAUDE.md's "never convert unknown to zero/false" rule — this
stays None/NOT_DISCLOSED rather than an assumed number).
"""

import re

# Point-in-time recognition = Transactional. Real Ind AS 115 notes phrase
# this many different ways ("recognised at a point in time", "recognises
# the revenue at a point in time when products are dispatched" — confirmed
# on MARUTI, whose actual "Sale of products" policy note used the latter
# wording; the earlier version of this list only matched "recognised at a
# point in time" as one rigid substring and silently missed a textbook,
# unambiguous point-in-time disclosure entirely). Anchored on "point in
# time" plus a same-sentence "revenue"/"control"/"dispatch" co-occurrence
# rather than one fixed word order, so it survives real paraphrasing.
_POINT_IN_TIME_PATTERNS = [
    r"\bpoint in time\b.{0,80}\b(?:revenue|control|dispatch)\b",
    r"\b(?:revenue|control|dispatch)\b.{0,80}\bpoint in time\b",
    r"\bsatisfied at a point in time\b",
    r"\bone[- ]time sale\b",
    # "revenue ... is recognised WHEN control ... is transferred to the
    # customer" — the textbook Ind AS 115/IFRS 15 default wording for
    # point-in-time recognition, used almost verbatim by RELIANCE and
    # SUNPHARMA's actual Notes to Accounts, and paraphrased by ITC's
    # auditor's Key Audit Matter section ("the control over the same is
    # transferred to the customer, which is mainly upon delivery") —
    # neither ever says "point in time" or "over time" literally, since
    # this IS the standard's own definition of point-in-time recognition
    # (over-time recognition is always separately, explicitly labelled).
    # Confirmed all three were previously scanned as SEARCH_INCONCLUSIVE
    # even though their real, unambiguous policy text was already being
    # fetched — this was a classifier pattern gap, not a missing source.
    r"\brecognised when control\b", r"\brecognized when control\b",
    # No "control" requirement here — a page-window boundary can clip the
    # word "control" off the front of an excerpt while leaving the rest of
    # the clause intact (confirmed on ITC's auditor KAM text: "...the
    # control over the same is transferred to the customer, which is
    # mainly upon delivery" — "control" fell just outside the fetched
    # window, but "transferred to the customer...upon delivery" alone is
    # already unambiguous point-in-time revenue-recognition language on its
    # own, essentially never used outside that context).
    r"\btransferred to the customers?\b.{0,80}\b(?:upon|on)\s+(?:delivery|dispatch|shipment)\b",
    r"\b(?:upon|on)\s+(?:delivery|dispatch|shipment)\b.{0,80}\btransferred to the customers?\b",
    # Verb-form variant — confirmed on VIP Industries: "...transferred to
    # the customer WHEN the products ARE DELIVERED to the customer..." —
    # "when...delivered/dispatched/shipped" rather than the noun-form
    # "upon delivery" the two patterns above expect.
    r"\btransferred to the customers?\b.{0,80}\bwhen\b.{0,40}\b(?:delivered|dispatched|shipped)\b",
    r"\bwhen\b.{0,40}\b(?:delivered|dispatched|shipped)\b.{0,80}\btransferred to the customers?\b",
]

# Over-time recognition WITHOUT a defined term = Recurring. These anchors
# alone (no term-length anchor nearby) signal Recurring; if a term-length
# anchor co-occurs in the SAME sentence, the Annuity classification wins
# instead (see _DEFINED_TERM_ANCHOR below) — that's the spec's explicit
# Recurring-vs-Annuity tiebreaker. Same paraphrase-robustness fix as
# point-in-time above — confirmed on MARUTI, whose services note read
# "performance obligations that are satisfied over A PERIOD OF time", which
# the old rigid "satisfied over time" substring did not match.
_OVER_TIME_PATTERNS = [
    r"\brevenue\b.{0,80}\bover (?:a period of )?time\b",
    r"\bover (?:a period of )?time\b.{0,80}\brevenue\b",
    r"\bperformance obligations?\b.{0,80}\bsatisfied over (?:a period of )?time\b",
    r"\bsatisfied over (?:a period of )?time\b",
    r"\bsubscription(?:-based)? revenue\b", r"\brecurring revenue\b",
]

# Annuity = a defined-term periodic-service contract (AMC/O&M with a stated
# tenure). AMC/O&M anchors are treated as Annuity signals directly (they
# describe the CONTRACT TYPE, not just recognition timing) since the spec's
# own example is "5-year O&M agreement" — a named contract type with an
# inherent defined term, distinct from bare over-time recognition language.
#
# Each pattern requires a "revenue" co-occurrence within the same sentence —
# confirmed false positive on L&T without this: an AR page's ESG/case-study
# narrative ("...implementation of electricity consumption initiatives...
# in its O&M contract for the Bhagirathi Water Treatment Plant...") matched
# "O&M contract" even though it's describing a specific project example, not
# the company's revenue-recognition policy. A genuine policy disclosure
# always states what happens to REVENUE for that contract type; a narrative
# mention of a named O&M contract elsewhere in the report typically doesn't.
_ANNUITY_CONTRACT_PATTERNS = [
    r"\brevenue\b.{0,100}\bannual maintenance contracts?\b",
    r"\bannual maintenance contracts?\b.{0,100}\brevenue\b",
    # NOTE: deliberately NOT matching bare "amc" — confirmed false positive
    # on HDFCBANK, where "amc" matched "HDFC AMC" (Asset Management
    # Company, a subsidiary name), not Annual Maintenance Contract.
    r"\brevenue\b.{0,100}\boperation and maintenance (?:contract|agreement)s?\b",
    r"\boperation and maintenance (?:contract|agreement)s?\b.{0,100}\brevenue\b",
    r"\brevenue\b.{0,100}\bo&m (?:contract|agreement)s?\b",
    r"\bo&m (?:contract|agreement)s?\b.{0,100}\brevenue\b",
]
# A stated tenure attached to a contract/agreement noun (e.g. "5-year O&M
# agreement", "10 year service contract") — the defined-term signal that
# distinguishes Annuity from Recurring per the spec.
_DEFINED_TERM_ANCHOR = re.compile(
    r"\b\d+(?:\.\d+)?\s*[-–]?\s*years?\b[^.]{0,40}\b(?:contract|agreement|tenure|term)\b"
    r"|\b(?:contract|agreement|tenure|term)\b[^.]{0,40}\b\d+(?:\.\d+)?\s*[-–]?\s*years?\b",
    re.I,
)

# A sentence stating BOTH "point in time" and "over (a period of) time"
# joined by "or" is the generic Ind AS 115 FRAMEWORK/judgement description
# every company includes ("...determining whether the performance
# obligation is satisfied at a point in time or over a period of time") —
# it explains that the company assesses each obligation against BOTH
# possible methods, not which one actually applies to ITS revenue. Matching
# on this sentence as if it were a definitive classification is a
# confirmed false positive (TCS): it says nothing about which method TCS's
# revenue actually uses, so it must be skipped entirely rather than
# counted as either Transactional or Recurring evidence.
_GENERIC_FRAMEWORK_RE = re.compile(
    r"\bpoint in time\b.{0,40}\bor\b.{0,40}\bover (?:a period of )?time\b"
    r"|\bover (?:a period of )?time\b.{0,40}\bor\b.{0,40}\bpoint in time\b",
    re.I,
)

_PERCENT_ANCHOR = re.compile(r"\d+(?:\.\d+)?\s*%")

# Renewal-rate anchors — only a sentence carrying BOTH one of these AND an
# actual percentage counts as a disclosed renewal rate (3D). A qualitative
# claim ("high renewal rates", "strong customer retention") with no number
# is explicitly NOT_DISCLOSED per the spec, not estimated.
_RENEWAL_RATE_PATTERNS = [
    r"\brenewal rate\b", r"\bcontracts? renewed\b", r"\bpersistency\s+ratio\b",
    r"\brenewed at\b",
]


def _sentences(text):
    """Same PDF-line-wrap-safe sentence splitter as
    moat_switching_costs_scoring._sentences — newlines normalized to spaces
    before splitting so a phrase mid-wrapped across a PDF line break (e.g.
    "Persistency"/"ratio" on separate lines) isn't broken apart."""
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _quote_snippet(sent, patterns, window=140):
    """Table text extracted from a PDF often has no sentence-ending
    punctuation, so `_sentences` can merge an unrelated table block with the
    real anchor match into one giant run-on "sentence" (confirmed on TCS —
    a fixed-asset schedule table got glued to a genuine "recognised over
    time" match). Returning the whole merged blob as the evidence quote
    would show a false-positive-looking citation even though the underlying
    match is real, so this centers the quote on the actual matched anchor
    instead of returning the full sentence.

    Centering alone wasn't enough — confirmed on the same TCS excerpt, the
    140-char PREFIX window still swallowed a run of unrelated table cell
    values ("31 Vehicles 1 2 Furniture and fixtures - 2 2,778 7,601") sitting
    right before the real sentence. Real prose essentially never has 2+
    separate digit tokens in a short run; a PDF table row does. So if the
    prefix contains 2+ digit runs, trim it back to just after the LAST one —
    that's almost always where the genuine prose clause actually starts.
    Left untouched when the prefix has 0-1 digit runs (e.g. a normal "In
    FY24, ..." lead-in) since that's very unlikely to be table noise.
    """
    low = sent.lower()
    for pat in patterns:
        m = re.search(pat, low, re.I)
        if m:
            start = max(0, m.start() - window)
            end = min(len(sent), m.end() + window)
            prefix = sent[start:m.start()]
            digit_runs = list(re.finditer(r"\d[\d,\.]*", prefix))
            if len(digit_runs) >= 2:
                prefix = prefix[digit_runs[-1].end():]
            # A page footer/header stitched onto the next excerpt by the
            # newline-collapse in _sentences (no sentence-ending punctuation
            # between them) very often contains "<Company Name> Limited"/
            # "Ltd" right before the real clause resumes — confirmed on ITC
            # ("...294 REPORT AND ACCOUNTS 2026 ITC Limited same is
            # transferred to the customer..."). Nearly every Indian company
            # is named "X Limited"/"X Ltd", so this is generic cleanup, not
            # company-specific: drop everything up to and including the
            # LAST such occurrence in the prefix.
            footer_hits = list(re.finditer(r"\b(?:limited|ltd\.?)\b", prefix, re.I))
            if footer_hits:
                prefix = prefix[footer_hits[-1].end():]
            snippet = (prefix + sent[m.start():end]).strip()
            return snippet[:300]
    return sent[:300]


# Ind AS 115 requires a "disaggregation of revenue" note splitting revenue
# by TIMING of recognition — some companies disclose this as an explicit
# rupee-value table: "Revenue recognised at a point in time X ... Revenue
# recognised over a period of time Y". Confirmed on CAMS: the AR literally
# discloses ~140,258 (point in time) vs ~968 (over time) — i.e. ~99.3% of
# revenue is point-in-time — but the generic per-sentence anchor scan below
# would have picked "Recurring" purely because the over-time phrase
# happened to appear in the same merged table-sentence, WITHOUT ever
# looking at the actual figures. A disclosed numeric split is strictly
# better evidence than a plain anchor mention, so it's checked FIRST and
# wins outright when found, rather than falling through to the qualitative
# per-sentence scan.
_DISAGGREGATION_TABLE_RE = re.compile(
    r"revenue recogni[sz]ed at a point in time\D{0,20}?([\d,]+\.?\d*)"
    r".{0,200}?revenue recogni[sz]ed over (?:a period of )?time\D{0,20}?([\d,]+\.?\d*)"
    r"|revenue recogni[sz]ed over (?:a period of )?time\D{0,20}?([\d,]+\.?\d*)"
    r".{0,200}?revenue recogni[sz]ed at a point in time\D{0,20}?([\d,]+\.?\d*)",
    re.I | re.S,
)


def _extract_disaggregation_split(text):
    """Returns (point_in_time_amount, over_time_amount, matched_span_text)
    from a disclosed Ind AS 115 revenue-timing disaggregation table, or
    None if no such table is found. Amounts are whatever unit the AR uses
    (Rs Crore/Million/Lakh) — only their RATIO is used, so the unit doesn't
    need to be known."""
    m = _DISAGGREGATION_TABLE_RE.search(text)
    if not m:
        return None
    if m.group(1) is not None:
        pit_raw, ot_raw = m.group(1), m.group(2)
    else:
        ot_raw, pit_raw = m.group(3), m.group(4)
    try:
        pit = float(pit_raw.replace(",", ""))
        ot = float(ot_raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None
    if pit + ot <= 0:
        return None
    return pit, ot, m.group(0)


def classify_contract_type(text):
    """Deterministic 3A/3B/3C classification from AR/Ind-AS-115-note text.

    Returns:
      {"contract_type": "transactional"|"recurring"|"annuity"|None,
       "evidence_quote": str, "source": "Annual Report"|"none",
       "reasoning": str}
    Never raises, never fabricates — returns contract_type=None (not a
    default guess) if no recognition-timing/contract-type language is found.

    Classifies off the FIRST sentence (in document order) that matches any
    category, rather than pooling every match in the whole evidence pool
    under a fixed Annuity > Recurring > Transactional priority. Real Notes
    to Accounts consistently disclose the company's PRIMARY/largest revenue
    stream first (e.g. "2.4.1 Sale of products") and ancillary streams after
    (e.g. "2.4.2.1 Income from services") — confirmed on MARUTI, where a
    fixed category-priority order would have let a minor extended-warranty/
    services over-time clause outrank the company's actual primary,
    dominant point-in-time vehicle-sale policy simply because "Recurring"
    was checked before "Transactional". Reading sentences in order and
    taking the first hit respects that primary-disclosure-comes-first
    convention instead.
    """
    sentences = _sentences(text)
    if not sentences:
        return {"contract_type": None, "evidence_quote": "", "source": "none",
                "reasoning": "No Annual Report text available to scan for revenue-recognition language."}

    split = _extract_disaggregation_split(re.sub(r"\s+", " ", text or ""))
    if split is not None:
        pit, ot, matched_text = split
        total = pit + ot
        pit_pct = round(100 * pit / total, 1)
        # A disclosed split still needs a real majority to call outright —
        # if it's genuinely close to even, fall through to the qualitative
        # scan below rather than forcing a razor-thin numeric edge into a
        # single label.
        if pit_pct >= 60 or pit_pct <= 40:
            winner = "transactional" if pit_pct >= 60 else "recurring"
            return {
                "contract_type": winner,
                "evidence_quote": matched_text[:300],
                "source": "Annual Report",
                "reasoning": (
                    f"Annual Report discloses an EXPLICIT revenue-timing split (Ind AS 115 disaggregation note): "
                    f"{pit_pct}% of revenue recognised at a point in time vs {round(100 - pit_pct, 1)}% over time — "
                    f"{'Transactional' if winner == 'transactional' else 'Recurring'} per the spec, based on the "
                    f"disclosed majority, not a plain anchor mention."
                ),
            }

    for sent in sentences:
        low = sent.lower()

        if _GENERIC_FRAMEWORK_RE.search(low):
            continue

        # Annuity check 1: an AMC/O&M contract-type anchor names the
        # contract type directly, decisive on its own.
        if any(re.search(p, low, re.I) for p in _ANNUITY_CONTRACT_PATTERNS):
            return {
                "contract_type": "annuity", "evidence_quote": _quote_snippet(sent, _ANNUITY_CONTRACT_PATTERNS),
                "source": "Annual Report",
                "reasoning": "Annual Report names a defined-tenure service contract (AMC/O&M-type language), the Annuity signal per the spec.",
            }

        has_over_time = any(re.search(p, low, re.I) for p in _OVER_TIME_PATTERNS)
        # Annuity check 2: over-time recognition co-occurring with a stated
        # contract term length IN THE SAME SENTENCE promotes it from
        # Recurring to Annuity — the spec's explicit tiebreaker ("if a
        # specific duration is stated, it's Annuity not Recurring"). Scoped
        # to the same sentence (not "anywhere in the evidence pool") so an
        # unrelated defined-term clause elsewhere in the document (e.g. a
        # lease-term note) can't wrongly promote a genuinely term-less
        # recurring-revenue sentence.
        if has_over_time and _DEFINED_TERM_ANCHOR.search(sent):
            return {
                "contract_type": "annuity",
                "evidence_quote": _quote_snippet(sent, [_DEFINED_TERM_ANCHOR.pattern]), "source": "Annual Report",
                "reasoning": "Over-time revenue recognition co-occurs with a stated contract term length in the same disclosure — Annuity, not Recurring, per the spec's defined-term tiebreaker.",
            }

        if has_over_time:
            return {
                "contract_type": "recurring", "evidence_quote": _quote_snippet(sent, _OVER_TIME_PATTERNS), "source": "Annual Report",
                "reasoning": "Annual Report describes revenue recognised over time / subscription-style billing with no stated fixed contractual term — Recurring per the spec.",
            }

        if any(re.search(p, low, re.I) for p in _POINT_IN_TIME_PATTERNS):
            return {
                "contract_type": "transactional", "evidence_quote": _quote_snippet(sent, _POINT_IN_TIME_PATTERNS), "source": "Annual Report",
                "reasoning": "Annual Report describes revenue recognised at a point in time when control is transferred, with no ongoing service obligation — Transactional per the spec.",
            }

    return {
        "contract_type": None, "evidence_quote": "", "source": "none",
        "reasoning": "No Ind AS 115 recognition-timing (point-in-time / over-time) or AMC/O&M contract-tenure language located in the Annual Report text scanned.",
    }


def extract_renewal_rate_pct(text):
    """3D — Contract renewal rate = Contracts renewed / Contracts up for
    renewal. Only returns a value when an actual disclosed PERCENTAGE
    sentence is found (renewal-rate anchor AND a number in the SAME
    sentence) — a qualitative claim like "high renewal rates" with no
    number returns None (NOT_DISCLOSED), never an estimate, per the
    spec's explicit no-estimation rule and CLAUDE.md's "never convert
    unknown to zero/false" rule.

    Returns {"renewal_rate_pct": float|None, "evidence_quote": str|None}.
    """
    sentences = _sentences(text)
    for sent in sentences:
        low = sent.lower()
        if any(re.search(pat, low, re.I) for pat in _RENEWAL_RATE_PATTERNS):
            m = _PERCENT_ANCHOR.search(sent)
            if m:
                try:
                    pct = float(re.match(r"[\d.]+", m.group()).group())
                except Exception:
                    continue
                if 0 <= pct <= 100:
                    return {"renewal_rate_pct": pct, "evidence_quote": _quote_snippet(sent, _RENEWAL_RATE_PATTERNS)}
    return {"renewal_rate_pct": None, "evidence_quote": None}
