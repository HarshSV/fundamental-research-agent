"""
Section J - Regulatory, legal & compliance. Deterministic (no-LLM) scorers,
mirroring the established pattern used for F.2.1/G/H/I (tools.
entry_barrier_scoring, tools.channel_distribution_scoring, tools.
product_tech_scoring, tools.supply_chain_scoring) - generic keyword/regex
logic, not ticker-specific, per CLAUDE.md.

Most J sub-points are AR-based (Risk Factors / Notes to Accounts /
Contingent Liabilities), same as every prior section. J3.1 (Competition
investigations) is the one exception - its framework PRIMARY source is
NSE Corporate Announcements (not the Annual Report), so
classify_competition_investigation_status operates on the announcement-row
list already returned by the EXISTING tools.nse_announcements.
fetch_announcements() (already integrated into qualitative_engine.py for
C.8.2/D.1.2/etc.) rather than AR excerpt text - no new retrieval
infrastructure required.

J1.1, J2 (parent row itself) are blank/undefined in the framework.

J1.2 Renewal burden, J2.1 Litigation count/materiality, J2.2 Probability/
management assessment, J3.1 Competition investigations, J3.2 Potential
financial/operational impact, J4.1 Tax disputes, J4.2 Historic tax
exposures, J4.3 Ongoing tax audits/assessments, J5.1 Subsidy dependence,
J5.2 Environmental regulation exposure.
"""
import re

_RENEWAL_SPECIFIC_RE = re.compile(
    r"renewed?\s+every\s+(\d{1,3})\s*years?|renewal\s+period\s+of\s+(\d{1,3})\s*years?|"
    r"licen[sc]e\s+valid\s+for\s+(\d{1,3})\s*years?",
    re.I,
)
_RENEWAL_GENERIC_RE = re.compile(
    r"periodic\s+renewal|regulatory\s+compliance\s+requirements?|renewal\s+of\s+licen[sc]es?|"
    r"statutory\s+approvals?\s+(?:are\s+)?required",
    re.I,
)

_LITIGATION_QUANTIFIED_RE = re.compile(
    r"(\d{1,4})\s+(?:material\s+)?(?:cases?|litigations?|legal\s+proceedings?)|"
    r"contingent\s+liabilit(?:y|ies)\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+",
    re.I,
)
_LITIGATION_QUALITATIVE_RE = re.compile(
    r"contingent\s+liabilit(?:y|ies)|legal\s+proceedings?|material\s+litigation|pending\s+(?:cases?|litigation)",
    re.I,
)

_OUTCOME_ASSESSMENT_RE = re.compile(
    r"probable|possible\s+(?:but\s+not\s+probable)?|remote\b|"
    r"management\s+(?:is\s+)?(?:confident|believes?)\s+(?:of\s+)?(?:a\s+)?favou?rable\s+outcome|"
    r"no\s+material\s+(?:adverse\s+)?impact\s+(?:is\s+)?expected",
    re.I,
)

_COMPETITION_ORDER_RE = re.compile(
    r"cci\s+order|order\s+(?:was\s+)?passed\s+by\s+(?:the\s+)?(?:competition\s+commission|cci)|"
    r"penalty\s+imposed\s+by\s+(?:the\s+)?(?:cci|competition\s+commission)",
    re.I,
)
_COMPETITION_INVESTIGATION_RE = re.compile(
    r"investigation\s+(?:initiated|ordered)\s+by\s+(?:the\s+)?(?:cci|competition\s+commission)|"
    r"under\s+investigation\s+by\s+(?:the\s+)?(?:cci|competition\s+commission)|"
    r"dg\s+investigation|director\s+general.{0,30}investigation",
    re.I,
)
_COMPETITION_INQUIRY_RE = re.compile(
    r"show\s+cause\s+notice.{0,40}(?:cci|competition)|"
    r"(?:cci|competition\s+commission).{0,40}(?:inquiry|show\s+cause)",
    re.I,
)
_COMPETITION_CLOSED_RE = re.compile(
    r"(?:investigation|inquiry|matter|case)\s+(?:was\s+)?closed|"
    r"no\s+adverse\s+(?:order|finding)|cci\s+closed\s+the\s+(?:case|matter|investigation)",
    re.I,
)
_COMPETITION_MENTION_RE = re.compile(r"competition\s+commission|\bcci\b|antitrust", re.I)

_TAX_DISPUTE_QUANTIFIED_RE = re.compile(
    r"(?:income\s+tax|gst)\s+demand\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+|"
    r"outstanding\s+demand\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+",
    re.I,
)
_TAX_DISPUTE_QUALITATIVE_RE = re.compile(
    r"income\s+tax\s+(?:demand|contingenc|dispute)|gst\s+(?:demand|contingenc|dispute)|"
    r"outstanding\s+(?:tax\s+)?demand|tax\s+appeal",
    re.I,
)
# Ind AS 37's mandated Contingent Liabilities note is where a tax demand/
# dispute would ALWAYS surface if one existed ("Claims Against The
# Company/Group Not Acknowledged As Debt" is the standard row this sits
# under) - a genuine NIL/dash value on that row for both years shown is a
# real, explicit "no tax disputes" finding, not an absence of data.
# Confirmed real on Prime Fresh Limited: "Claims Against The Company Not
# Acknowledged As Debt - -" (both years NIL).
_TAX_DISPUTE_NONE_RE = re.compile(
    r"claims?\s+against\s+the\s+(?:company|group)\s+not\s+acknowledged\s+as\s+debt\s*"
    r"(?:-|nil)\s*(?:-|nil)?", re.I,
)

_TAX_AUDIT_ONGOING_RE = re.compile(
    r"(?:tax\s+)?(?:assessment|audit)\s+(?:is\s+)?(?:currently\s+)?ongoing|"
    r"under\s+(?:tax\s+)?assessment|assessment\s+proceedings?\s+(?:are\s+)?pending",
    re.I,
)
_TAX_AUDIT_RESOLVED_RE = re.compile(
    r"assessment\s+(?:has\s+been\s+)?(?:completed|resolved|concluded)|"
    r"(?:tax\s+)?(?:audit|assessment)\s+(?:was\s+)?resolved",
    re.I,
)

_SUBSIDY_QUANTIFIED_RE = re.compile(
    r"subsidy\s+(?:income|income\s+of)\s+(?:inr|rs\.?|₹)?\s*[\d,]+(?:\.\d+)?\s*(?:crore|lakh|million)?",
    re.I,
)
_SUBSIDY_QUALITATIVE_RE = re.compile(
    r"government\s+(?:subsid(?:y|ies)|incentives?|grants?)|export\s+incentives?|pli\s+scheme",
    re.I,
)

_ENV_REGULATION_SPECIFIC_RE = re.compile(
    r"environmental\s+clearance|forest\s+clearance|wildlife\s+clearance|\bcrz\b\s+clearance|"
    r"pollution\s+control\s+board|extended\s+producer\s+responsibility",
    re.I,
)
_ENV_REGULATION_GENERIC_RE = re.compile(
    r"environmental\s+regulations?|environmental\s+norms?|esg\s+(?:risk|compliance)",
    re.I,
)


def score_renewal_burden(text):
    """J.1.2 - Renewal burden. A specific renewal period (X years)
    scores highest; generic periodic-renewal/compliance language
    without a period scores mid; neither returns None."""
    if not text:
        return {"specific_period_disclosed": None, "renewal_burden_score": None}
    if _RENEWAL_SPECIFIC_RE.search(text):
        return {"specific_period_disclosed": True, "renewal_burden_score": 4}
    if _RENEWAL_GENERIC_RE.search(text):
        return {"specific_period_disclosed": False, "renewal_burden_score": 3}
    return {"specific_period_disclosed": None, "renewal_burden_score": None}


def score_litigation_materiality(text):
    """J.2.1 - Litigation count and materiality. A quantified case
    count or contingent-liability amount scores highest; qualitative
    litigation/contingent-liability language without a number scores
    mid; neither returns None."""
    if not text:
        return {"quantified": None, "litigation_materiality_score": None}
    if _LITIGATION_QUANTIFIED_RE.search(text):
        return {"quantified": True, "litigation_materiality_score": 4}
    if _LITIGATION_QUALITATIVE_RE.search(text):
        return {"quantified": False, "litigation_materiality_score": 3}
    return {"quantified": None, "litigation_materiality_score": None}


def score_outcome_assessment(text):
    """J.2.2 - Probability / management assessment. Per the framework's
    own explicit instruction: "do not assign probability if the company
    does not disclose one" - this returns None (not a fabricated
    middle score) unless real Ind-AS-37-style assessment language
    (probable/possible/remote, or an explicit management confidence
    statement) is found."""
    if not text:
        return {"assessment_disclosed": None, "outcome_risk_score": None}
    if _OUTCOME_ASSESSMENT_RE.search(text):
        return {"assessment_disclosed": True, "outcome_risk_score": 4}
    return {"assessment_disclosed": None, "outcome_risk_score": None}


def classify_competition_investigation_status(announcement_rows):
    """J.3.1 - Competition investigations. Spec: Investigation Status =
    None / Inquiry / Investigation / Order / Closed. Operates on the
    real NSE Corporate Announcements list (tools.nse_announcements.
    fetch_announcements), not AR text - matching the framework's own
    stated primary source. "None" is only returned when the
    announcement history was successfully searched and contained no
    CCI/antitrust/competition-investigation language at all (a real,
    evidenced absence over the available announcement window) -
    distinct from a failed/empty fetch, which the caller handles
    separately as SEARCH_INCONCLUSIVE."""
    if announcement_rows is None:
        return {"investigation_status": None, "matched_announcement": None}
    blob_rows = [
        (row, f"{row.get('desc') or ''} {row.get('attchmntText') or ''}")
        for row in announcement_rows
    ]
    for row, blob in blob_rows:
        if _COMPETITION_ORDER_RE.search(blob):
            return {"investigation_status": "Order", "matched_announcement": row.get("desc")}
    for row, blob in blob_rows:
        if _COMPETITION_CLOSED_RE.search(blob) and _COMPETITION_MENTION_RE.search(blob):
            return {"investigation_status": "Closed", "matched_announcement": row.get("desc")}
    for row, blob in blob_rows:
        if _COMPETITION_INVESTIGATION_RE.search(blob):
            return {"investigation_status": "Investigation", "matched_announcement": row.get("desc")}
    for row, blob in blob_rows:
        if _COMPETITION_INQUIRY_RE.search(blob):
            return {"investigation_status": "Inquiry", "matched_announcement": row.get("desc")}
    return {"investigation_status": "None", "matched_announcement": None}


def score_competition_impact(text):
    """J.3.2 - Potential financial / operational impact. Spec formula:
    Impact Score (1-5) based on disclosed penalty, remedy or
    operational restriction. Requires an actual competition-law context
    (CCI/antitrust) combined with a disclosed penalty/remedy - generic
    contingent-liability language alone is NOT sufficient (that's
    J.2.1's domain, not this sub-point's)."""
    if not text or not _COMPETITION_MENTION_RE.search(text):
        return {"impact_disclosed": None, "competition_impact_score": None}
    if re.search(r"penalty\s+(?:of|imposed)|remed(?:y|ial\s+measures?)|operational\s+restriction", text, re.I):
        return {"impact_disclosed": True, "competition_impact_score": 4}
    return {"impact_disclosed": False, "competition_impact_score": 2}


def score_tax_dispute_exposure(text):
    """J.4.1 - Tax disputes. A quantified demand amount scores highest;
    qualitative tax-dispute/contingency language without a number scores
    mid; an explicit NIL Contingent Liabilities claims row (a genuine "no
    tax disputes exist" finding, not an absence of data - see
    _TAX_DISPUTE_NONE_RE) scores as the cleanest real outcome; neither
    signal at all returns None."""
    if not text:
        return {"quantified": None, "tax_dispute_score": None}
    if _TAX_DISPUTE_QUANTIFIED_RE.search(text):
        return {"quantified": True, "tax_dispute_score": 4}
    if _TAX_DISPUTE_QUALITATIVE_RE.search(text):
        return {"quantified": False, "tax_dispute_score": 3}
    if _TAX_DISPUTE_NONE_RE.search(text):
        return {"quantified": False, "tax_dispute_score": 5}
    return {"quantified": None, "tax_dispute_score": None}


def score_historic_tax_risk(text):
    """J.4.2 - Historic tax exposures. The framework's own formula asks
    to "compare 3-5 years", which this single-year AR-excerpt scan
    cannot compute (same documented limitation as I.4.2/G.3.2's single-
    year evidence-presence convention). Scores current-year tax-dispute
    disclosure presence only - an explicit NIL Contingent Liabilities
    claims row (see _TAX_DISPUTE_NONE_RE) is real evidence of a clean
    history, not a missing one."""
    if not text:
        return {"disclosed": None, "historic_tax_risk_score": None}
    if _TAX_DISPUTE_QUALITATIVE_RE.search(text):
        return {"disclosed": True, "historic_tax_risk_score": 3}
    if _TAX_DISPUTE_NONE_RE.search(text):
        return {"disclosed": True, "historic_tax_risk_score": 5}
    return {"disclosed": None, "historic_tax_risk_score": None}


def classify_tax_audit_status(text):
    """J.4.3 - Ongoing tax audits / assessments. Spec: Audit Status =
    None / Ongoing / Resolved; score only where evidence exists.
    Returns None (never fabricated) when no assessment/audit language
    is found at all - "None" as a real status value is only used when
    the framework's own workbook semantics call for it; here, absence
    of ANY audit-status evidence returns None (caller treats this as
    genuinely not found, not as an evidenced "no audit" state, since
    unlike J.3.1 there is no comprehensive announcement-history search
    behind this one - only the current year's AR text)."""
    if not text:
        return {"audit_status": None}
    if _TAX_AUDIT_ONGOING_RE.search(text):
        return {"audit_status": "Ongoing"}
    if _TAX_AUDIT_RESOLVED_RE.search(text):
        return {"audit_status": "Resolved"}
    return {"audit_status": None}


def score_subsidy_dependence(text):
    """J.5.1 - Subsidy dependence. Spec formula: Subsidy Dependence % =
    Subsidy/Grant Income / Relevant Revenue or Profit where meaningful.
    A quantified subsidy-income figure scores highest (real % can be
    contextualized even if not independently recomputed here);
    qualitative subsidy/incentive language without a number scores mid;
    neither returns None - same documented limitation as every other
    MD&A-narrative %-formula sub-point (A.1.1/A.3/G.1.1) that cannot
    reliably parse a clean percentage from prose."""
    if not text:
        return {"quantified": None, "subsidy_dependence_score": None}
    if _SUBSIDY_QUANTIFIED_RE.search(text):
        return {"quantified": True, "subsidy_dependence_score": 4}
    if _SUBSIDY_QUALITATIVE_RE.search(text):
        return {"quantified": False, "subsidy_dependence_score": 3}
    return {"quantified": None, "subsidy_dependence_score": None}


def score_environmental_regulation_exposure(text):
    """J.5.2 - Environmental regulation exposure. Spec formula:
    Regulatory Shift Risk Score (1-5). A specific named clearance/
    regulation type (environmental/forest/wildlife/CRZ clearance,
    pollution control board, EPR) scores highest; generic ESG/
    environmental-regulation language scores mid; neither returns
    None. (The framework also lists PARIVESH as a secondary cross-
    check source; not invoked here, matching every other cross-check
    pathway already recorded as NOT_CHECKED throughout A-I.)
    """
    if not text:
        return {"specific_clearance_disclosed": None, "environmental_regulation_score": None}
    if _ENV_REGULATION_SPECIFIC_RE.search(text):
        return {"specific_clearance_disclosed": True, "environmental_regulation_score": 4}
    if _ENV_REGULATION_GENERIC_RE.search(text):
        return {"specific_clearance_disclosed": False, "environmental_regulation_score": 3}
    return {"specific_clearance_disclosed": None, "environmental_regulation_score": None}
