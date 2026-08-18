"""
D.6.2 - Forced-sale / invocation signals. Deterministic (no-LLM) scoring
over real NSE Corporate Announcements (SEBI SAST Regulation 31/8A pledge/
encumbrance disclosures + any standalone default/forced-sale filing),
cross-checked against the real pledge-% trend (tools.shareholding_scraper)
and Regulation 7(2) insider-trading disclosures (tools.insider_trading_scraper).
Generic keyword/regex logic, not ticker-specific.

Key real ambiguity this module has to handle: NSE's own SEBI SAST
Regulation 31(1)/31(2)/8A disclosure-TYPE description is a template that
always lists all three possible reasons together - "encumbrance of
shares/invocation of encumbrance/release of encumbrance" - regardless of
which one actually happened this filing. A naive "invocation" keyword
match against that boilerplate title would false-positive on almost
every company that has ever filed ANY pledge disclosure, since the word
"invocation" appears in the routine template itself. This module
therefore distinguishes a SINGULAR, unambiguous invocation statement
(real confirming evidence) from the routine enumerated-list boilerplate
(real but ambiguous - a pledge-related filing exists, but not
necessarily an invocation), consistent with the spec's own instruction
to classify only on disclosed evidence, not an assumed reason.
"""
import re


# A SAST Reg 31/8A pledge/encumbrance disclosure filing exists. Real,
# but ambiguous on its own - see module docstring.
_PLEDGE_DISCLOSURE = re.compile(
    r"encumbrance of shares|pledge(?:d)? shares|regulation 31\(1\)|regulation 31\(2\)|"
    r"regulation 8a|sast regulations|disclosure of pledge",
    re.I,
)
# The routine enumerated-list template - matches when the filing's own
# description lists invocation alongside creation/release as one of
# several possible reasons, rather than singularly confirming it.
_ENUMERATED_BOILERPLATE = re.compile(
    r"(?:creation|encumbrance)(?:\s+of\s+(?:shares|encumbrance))?\s*/\s*invocation of encumbrance\s*/\s*release",
    re.I,
)
# A SINGULAR, unambiguous statement that invocation/forced sale actually
# occurred - not part of the enumerated "X/Y/Z" template.
_SINGULAR_INVOCATION = re.compile(
    r"invocation of pledge(?!\s*/)|pledge(?:d shares)?\s+(?:were|was|have been|has been)\s+invoked|"
    r"invok(?:ed|ing) the pledge|lender(?:s)?\s+(?:has|have)?\s*invok|"
    r"shares?\s+sold\s+(?:pursuant to|on|upon)\s+invocation|forced sale of pledged shares|"
    r"sale of pledged shares by (?:the )?lender",
    re.I,
)
# Standalone distress language that isn't pledge-specific at all but is
# real, strong forced-sale-adjacent evidence wherever it appears (no
# enumerated-boilerplate ambiguity problem, since these phrasings aren't
# part of any routine multi-option disclosure-type template).
_DEFAULT_DISTRESS = re.compile(
    r"default in (?:repayment|payment)|declared (?:a )?default|invocation of (?:corporate )?guarantee|"
    r"margin call|classified as npa|debt default",
    re.I,
)


def classify_pledge_announcements(announcements):
    """Scans real NSE Corporate Announcements (as returned by
    tools.nse_announcements.fetch_announcements) for pledge/encumbrance
    and default/distress language. Returns
    {'confirmed': [...], 'possible': [...]} - each a list of
    {'desc','an_dt','evidence'} for real matched rows, never a guess at
    ones that don't literally match."""
    confirmed, possible = [], []
    for row in announcements or []:
        text = f"{row.get('desc') or ''} {row.get('attchmntText') or ''}"
        if not text.strip():
            continue
        if _SINGULAR_INVOCATION.search(text) or _DEFAULT_DISTRESS.search(text):
            confirmed.append({
                "desc": row.get("desc"), "an_dt": row.get("an_dt"),
                "evidence": text.strip()[:300],
            })
        elif _PLEDGE_DISCLOSURE.search(text) and (_ENUMERATED_BOILERPLATE.search(text) or "invocation" in text.lower()):
            possible.append({
                "desc": row.get("desc"), "an_dt": row.get("an_dt"),
                "evidence": text.strip()[:300],
            })
    return {"confirmed": confirmed, "possible": possible}


# Only "invoc" (invocation/invoked) - deliberately NOT a bare "pledge"
# match. Real acqMode values surveyed across multiple companies include
# "Pledge Creation" (a new pledge - not distress) and "Revokation of
# Pledge" (a pledge RELEASE - the opposite of forced-sale distress, and
# in fact real evidence for D.6.1). A bare "pledge" match would
# false-positive on both (confirmed real: RELIANCE's own Reg 7(2) filing
# "Revokation of Pledge" was being scored as Confirmed forced-sale
# evidence, when it's actually a benign pledge release). "Revokation"/
# "Revocation" doesn't contain the "invoc" substring, so this narrower
# match is safe against that specific false positive.
_INSIDER_INVOCATION = re.compile(r"invoc", re.I)


def classify_insider_invocation(trades):
    """Scans real Regulation 7(2) insider-trading rows (as returned by
    tools.insider_trading_scraper.fetch_insider_trades) for an acqMode
    or remarks field naming an INVOCATION-specific transaction (not a
    routine pledge creation or release) - a Reg 7(2) filing that itself
    tags the transaction this way is direct, singular confirming
    evidence (not the enumerated-boilerplate ambiguity the SAST filings
    carry). Returns a list of matched real rows, never a guess."""
    out = []
    for t in trades or []:
        mode = t.get("acqMode") or ""
        remarks = t.get("remarks") or ""
        if _INSIDER_INVOCATION.search(mode) or _INSIDER_INVOCATION.search(remarks):
            out.append(t)
    return out


def score_forced_sale_signals(announcement_matches, insider_matches, pledge_trend):
    """D.6.2 - Risk classification: No evidence / Possible / Confirmed,
    based only on disclosed evidence (never assumes a reason for a
    pledge% decline alone - that's D.6.1's job, and even there the spec
    says not to assume a reason).

    Confirmed: a singular, unambiguous invocation/default statement was
    found in a real NSE announcement, OR a real Reg 7(2) insider-trading
    filing itself tags the transaction as pledge/invocation-related.
    Possible: the routine, ambiguous SAST Reg 31/8A enumerated-list
    pledge-disclosure filing exists AND there is real corroborating
    evidence of an actual promoter pledge on record (a non-empty
    `pledge_trend`) - SEBI mandates this exact disclosure TYPE annually
    from every listed company's promoters regardless of whether any
    pledge actually exists (confirmed real false positive: TCS/Tata
    Sons has a routine 2012 Reg 31 filing using the standard "encumbrance
    of shares/invocation of encumbrance/release of encumbrance" template
    language, despite TCS having zero pledge history on NSE's own pledge
    endpoint - without this corroboration gate, that compliance
    formality alone would flag nearly every large-cap company as
    "Possible"). Without corroborating pledge data, the boilerplate
    filing alone is downgraded out of "Possible", not fabricated into
    false risk.
    No evidence: neither of the above was found.

    Returns {'classification','confirmed_count','possible_count',
    'evidence'}."""
    confirmed = list(announcement_matches.get("confirmed") or [])
    possible = list(announcement_matches.get("possible") or []) if pledge_trend else []
    if insider_matches:
        confirmed.extend([{
            "desc": f"Reg 7(2) insider filing - {t.get('acqName') or 'unnamed acquirer'} ({t.get('acqMode') or t.get('tdpTransactionType')})",
            "an_dt": t.get("date"), "evidence": t.get("remarks") or t.get("acqMode") or "",
        } for t in insider_matches])

    if confirmed:
        classification = "Confirmed"
    elif possible:
        classification = "Possible"
    else:
        classification = "No evidence"

    evidence = (confirmed[:3] if confirmed else possible[:3])
    return {
        "classification": classification,
        "confirmed_count": len(confirmed),
        "possible_count": len(possible),
        "evidence": evidence,
    }
