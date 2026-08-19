"""
E.5.3 - Inventory build vs demand: obsolete / slow-moving inventory.
Deterministic (no-LLM) scorer over real Annual Report Notes to
Accounts text. Generic keyword/regex logic, not ticker-specific.

E.5.1 (inventory trend) and E.5.2 (inventory vs demand divergence) are
NOT here - they're computed directly in tools/qualitative_engine.py
from the same real Inventory (current, prior) figures already
extracted for the Inventory Turnover ratio
(tools.annual_report_financials._get_extracted_financials) plus the
same Revenue figures used across A-D, no separate scoring module
needed for arithmetic formulas.
"""
import re

_NUM = r"[\d,]+\.?\d*"

# Two real phrasings confirmed across filers for the mandated Ind AS 2
# inventory write-down-to-NRV disclosure: HINDUNILVR's "an amount of
# X crores (prior: Y crores) was charged to the...statement of profit
# and loss on account of damaged and slow moving inventory" and
# MARUTI's "...includes X million (prior: Y million) in respect of
# write-downs of inventory to net realisable value". Both have the
# current figure, a parenthetical prior-year figure, and a nearby
# write-down/slow-moving keyword - captured together so the (current,
# prior) pair is never misattributed to an unrelated nearby number.
_WRITEDOWN_WITH_PRIOR = re.compile(
    rf"({_NUM})\s*(?:crores?|million|lakhs?)?\s*\([^)]*?({_NUM})\s*(?:crores?|million|lakhs?)?\)"
    r"[^.]{0,90}(?:slow moving inventory|write-?downs? of inventory|inventory to net realisable value)",
    re.I,
)
_OBSOLETE_MARKER = re.compile(r"\bobsolete\b|\bslow[- ]moving\b|\bslow moving\b", re.I)


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def score_inventory_obsolescence(text):
    """E.5.3 - Obsolescence Risk Score (1-5) based on write-downs,
    ageing and management commentary. Reads the real current + prior-
    year inventory write-down/slow-moving-inventory charge disclosed
    under Ind AS 2's mandated "lower of cost and NRV" note. A write-
    down that DECREASED year-over-year scores higher (improving
    inventory quality); one that INCREASED scores lower (worsening);
    a flat or newly-disclosed write-down with no prior comparison
    falls back to a mid score anchored only on its own disclosure
    (transparency itself, without a trend to judge). Returns
    {'writedown_cr','writedown_prior_cr','writedown_trend',
    'obsolescence_score'} or all-None if no write-down/slow-moving-
    inventory disclosure was located at all (a real, common gap - not
    every filer discloses a distinct write-down charge, especially
    when immaterial)."""
    if not text:
        return {"writedown_cr": None, "writedown_prior_cr": None, "writedown_trend": None, "obsolescence_score": None}
    m = _WRITEDOWN_WITH_PRIOR.search(text)
    if m:
        current, prior = _to_float(m.group(1)), _to_float(m.group(2))
        if current is not None and prior is not None:
            if prior == 0:
                trend = "New disclosure" if current > 0 else "Flat"
                score = 3
            else:
                change_pct = round(100 * (current - prior) / prior, 1)
                if change_pct <= -10:
                    trend, score = "Decreasing", 5
                elif change_pct <= 10:
                    trend, score = "Flat", 3
                else:
                    trend, score = "Increasing", 2
            return {"writedown_cr": current, "writedown_prior_cr": prior, "writedown_trend": trend, "obsolescence_score": score}
    if _OBSOLETE_MARKER.search(text):
        return {"writedown_cr": None, "writedown_prior_cr": None, "writedown_trend": None, "obsolescence_score": 3}
    return {"writedown_cr": None, "writedown_prior_cr": None, "writedown_trend": None, "obsolescence_score": None}
