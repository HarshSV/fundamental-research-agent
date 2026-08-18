"""
D.1.1-D.1.4 - Promoter/insider activity & market signalling. Deterministic
(no-LLM) scorers over real NSE Regulation 7(2) insider-trading disclosures
(tools/insider_trading_scraper.py) and NSE Corporate Announcements
(tools/nse_announcements.py, for D.1.2's sensitive-period cross-check).
Generic field/keyword logic, not ticker-specific.
"""

import re
import datetime


def _parse_date(s):
    """Parses NSE's own 'DD-Mon-YYYY' (or with a trailing time) date strings.
    Returns a datetime.date or None."""
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.datetime.strptime(s.strip().split(".")[0], fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _quarter_label(d):
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def _sell_rows(rows):
    """Filters raw NSE PIT rows to real SELL-direction rows only (the
    Regulation 7(2) feed reports both legs of a transfer, e.g. a promoter
    inter-se transfer shows as a Buy row for the recipient AND a Sell row
    for the transferor with the same did/pid group - only the Sell rows
    represent actual insider selling for this sub-point's purpose)."""
    return [r for r in (rows or []) if (r.get("tdpTransactionType") or "").strip().lower() == "sell"]


# ---------------------------------------------------------------------------
# D.1.1 - Frequency of insider selling.
# ---------------------------------------------------------------------------

def score_selling_frequency(rows):
    """Frequency = number of insider SELL disclosures per 8 quarters.
    Score: 5=none/rare(0-1), 4=low(2-3), 3=moderate(4-6), 2=high(7-10),
    1=frequent/repeated(11+). Returns {'sell_count','quarter_trend',
    'frequency_score'} or all-None if no PIT rows were located at all
    (distinct from a genuine zero sell-events result, which IS scoreable -
    a company with real PIT data and zero sells is a real 5/5, not N/A)."""
    if rows is None:
        return {"sell_count": None, "quarter_trend": None, "frequency_score": None}
    sells = _sell_rows(rows)
    by_quarter = {}
    for r in sells:
        d = _parse_date(r.get("acqfromDt") or r.get("date"))
        if not d:
            continue
        by_quarter.setdefault(_quarter_label(d), 0)
        by_quarter[_quarter_label(d)] += 1
    # Sort chronologically by parsing "Q# YYYY" back into a sortable key.
    def _qkey(label):
        q, yr = label.split()
        return (int(yr), int(q[1]))
    trend = sorted(by_quarter.items(), key=lambda kv: _qkey(kv[0]))
    count = len(sells)
    if count <= 1:
        score = 5
    elif count <= 3:
        score = 4
    elif count <= 6:
        score = 3
    elif count <= 10:
        score = 2
    else:
        score = 1
    return {
        "sell_count": count,
        "quarter_trend": [{"quarter": q, "count": c} for q, c in trend],
        "frequency_score": score,
    }


# ---------------------------------------------------------------------------
# D.1.2 - Timing of insider selling (sensitive-period cross-check).
# ---------------------------------------------------------------------------

_SENSITIVE_ANNOUNCEMENT = re.compile(
    r"financial results|board meeting|outcome of board|acquisition|merger|demerger|"
    r"scheme of arrangement|delisting|buyback|preferential issue", re.I
)


def score_selling_timing(sell_rows, announcements, window_days=7):
    """Timing Risk Score (1-5): flags a sell as "near a sensitive period"
    when its transaction date falls within `window_days` (either side) of
    a real NSE announcement matching a sensitive-event keyword (financial
    results, M&A, buyback, etc) - never infers intent, only measures
    date-proximity to a real, dated disclosure. Score: 5 = none near a
    sensitive period, 4 = 1 near, 3 = up to a third near, 2 = up to half
    near, 1 = more than half near. Returns {'near_sensitive_count',
    'total_sells','timing_events','timing_risk_score'} or all-None if there
    are no sell rows to assess."""
    if not sell_rows:
        return {"near_sensitive_count": None, "total_sells": None, "timing_events": None, "timing_risk_score": None}

    sensitive_dates = []
    for a in (announcements or []):
        desc = a.get("desc") or ""
        if not _SENSITIVE_ANNOUNCEMENT.search(desc):
            continue
        d = _parse_date((a.get("an_dt") or "").split()[0]) if a.get("an_dt") else None
        if d:
            sensitive_dates.append((d, desc))

    events = []
    near_count = 0
    for r in sell_rows:
        sd = _parse_date(r.get("acqfromDt") or r.get("date"))
        if not sd:
            continue
        nearest = min(sensitive_dates, key=lambda x: abs((x[0] - sd).days), default=None)
        is_near = nearest is not None and abs((nearest[0] - sd).days) <= window_days
        if is_near:
            near_count += 1
        events.append({
            "sell_date": sd.isoformat(),
            "near_sensitive_period": is_near,
            "nearest_event": nearest[1] if nearest else None,
            "gap_days": abs((nearest[0] - sd).days) if nearest else None,
        })

    total = len(events)
    if total == 0:
        return {"near_sensitive_count": None, "total_sells": None, "timing_events": None, "timing_risk_score": None}
    pct = near_count / total
    if near_count == 0:
        score = 5
    elif pct <= 1 / 3:
        score = 4 if near_count == 1 else 3
    elif pct <= 0.5:
        score = 2
    else:
        score = 1
    return {
        "near_sensitive_count": near_count, "total_sells": total,
        "timing_events": events, "timing_risk_score": score,
    }


# ---------------------------------------------------------------------------
# D.1.3 - Size of insider selling.
# ---------------------------------------------------------------------------

def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def score_selling_size(sell_rows):
    """Insider Sale Size % = Shares Sold / Insider Holding Before Sale x
    100, averaged across all real sell disclosures with a parseable
    before-holding figure ("Nil" or 0 before-holding rows are excluded -
    dividing by a zero/absent base holding is undefined, not a 100%
    sale). Classifies Low (<10%, score 5) / Moderate (10-30%, score 3) /
    High (>30%, score 1). Returns {'avg_sale_size_pct','classification',
    'size_score','events_used'} or all-None if no sell row has a usable
    before-holding figure."""
    if not sell_rows:
        return {"avg_sale_size_pct": None, "classification": None, "size_score": None, "events_used": 0}
    pcts = []
    for r in sell_rows:
        before = _to_int(r.get("befAcqSharesNo"))
        sold = _to_int(r.get("secAcq"))
        if not before or sold is None:
            continue
        pcts.append(round(100 * sold / before, 1))
    if not pcts:
        return {"avg_sale_size_pct": None, "classification": None, "size_score": None, "events_used": 0}
    avg_pct = round(sum(pcts) / len(pcts), 1)
    if avg_pct < 10:
        classification, score = "Low", 5
    elif avg_pct <= 30:
        classification, score = "Moderate", 3
    else:
        classification, score = "High", 1
    return {"avg_sale_size_pct": avg_pct, "classification": classification, "size_score": score, "events_used": len(pcts)}


# ---------------------------------------------------------------------------
# D.1.4 - Rationale for insider selling.
# ---------------------------------------------------------------------------

_RATIONALE_KEYWORD = re.compile(
    r"liquidity|tax|diversif|estate planning|personal financial|financial planning|"
    r"portfolio rebalanc|charitable|donation|family settlement|retirement", re.I
)
_BLANK_REMARK = re.compile(r"^\s*-?\s*$|^n\.?a\.?$|^nil$", re.I)


def score_selling_rationale(sell_rows):
    """Rationale Score (1-5): a sell disclosure's own `remarks` field
    (NSE's transaction-remarks field, not inferred) is "documented" when it
    names a liquidity/tax/diversification/estate-planning-type reason,
    "unexplained" when blank/"-"/"NA"/"Nil" (the overwhelmingly common
    real-world value - most Indian filers leave this optional field
    empty). Score: 5 = 100% documented, banded down to 1 = 0% documented
    (never guessed - a blank remark is scored as unexplained, not assumed
    benign). Returns {'documented_count','unexplained_count',
    'documented_pct','rationale_score'} or all-None if there are no sell
    rows to assess."""
    if not sell_rows:
        return {"documented_count": None, "unexplained_count": None, "documented_pct": None, "rationale_score": None}
    documented = unexplained = 0
    for r in sell_rows:
        remark = (r.get("remarks") or "").strip()
        if remark and not _BLANK_REMARK.match(remark) and _RATIONALE_KEYWORD.search(remark):
            documented += 1
        else:
            unexplained += 1
    total = documented + unexplained
    pct = round(100 * documented / total, 1)
    if pct >= 80:
        score = 5
    elif pct >= 50:
        score = 4
    elif pct >= 20:
        score = 3
    elif pct > 0:
        score = 2
    else:
        score = 1
    return {
        "documented_count": documented, "unexplained_count": unexplained,
        "documented_pct": pct, "rationale_score": score,
    }
