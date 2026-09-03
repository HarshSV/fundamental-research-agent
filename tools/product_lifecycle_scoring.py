"""
A.4 - Product lifecycle stage: deterministic (no-LLM) segment classifier.

Per the sheet's row 4: classify each of a company's reported segments as
Growth / Maturity / Commoditisation / Decline by comparing that segment's OWN
3-5yr revenue CAGR against a sector-median CAGR benchmark (see
tools/sector_cagr_universe.py), then A.4's orchestration in
tools/qualitative_engine.py blends the classified segments into a company-
level, revenue-weighted result.

Deliberately does NOT call any LLM - same rationale as the A.2.x moat scorers
and A.3's revenue_model_scoring.py (reproducible, auditable, avoids the
shared Groq/OpenRouter quota, and a classification that can be wrong
because of a bad LLM guess is a much bigger problem for a lifecycle-stage
label than for a qualitative moat score). Unlike those text-matching
scorers, this one classifies NUMBERS (CAGR percentages), but keeps the same
"deterministic, pure function, well-documented rubric, never fabricates"
spirit.

Two scoping decisions were locked in with the user (do not relitigate):
  - Sector benchmark = the company's own single NSE sector's peer-median
    CAGR, applied to every segment (not a per-segment sector
    reclassification).
  - Commoditisation's margin-compression leg uses the COMPANY-LEVEL EBITDA
    margin trend (not true segment-level margin, which this codebase cannot
    extract).

Rubric (relative_growth = segment_cagr - sector_median_cagr):
  Decline:         segment_cagr < 0 (negative CAGR) - ALWAYS wins, checked
                    first, regardless of the sector comparison. A company
                    losing revenue outright is in decline/obsolescence risk
                    even if the whole sector is also shrinking (relative
                    growth alone would misleadingly call that "Maturity").
  Growth:           relative_growth >= +3 percentage points.
  Commoditisation:  relative_growth <= -3pp AND company-level EBITDA margin
                     is compressing over the same lookback window (latest
                     margins_annual entry < margin N years back). BOTH
                     conditions required - if only the below-sector-growth
                     leg holds without confirmed margin compression, this
                     returns "Maturity" with a `margin_inconclusive` flag
                     rather than forcing a Commoditisation label the margin
                     data doesn't actually support.
  Maturity:         everything else (|relative_growth| < 3pp, or below-sector
                     growth without confirmed margin compression).

The +/-3pp threshold is a documented placeholder, same convention as A.5's
pricing-power bands (the spec itself doesn't pre-define exact bands) - kept
as a single named constant so it's easy to find and reconsider later.
"""

RELATIVE_GROWTH_THRESHOLD_PP = 3.0  # percentage points; documented placeholder, see module docstring


def classify_segment_lifecycle_stage(segment_cagr, sector_median_cagr, company_margin_trend=None):
    """
    Classify one segment's lifecycle stage.

    Args:
      segment_cagr: float (e.g. 0.08 for 8%) or None.
      sector_median_cagr: float or None (from
        tools.sector_cagr_universe.get_sector_median_cagr's "median_cagr").
      company_margin_trend: optional dict {"compressing": bool} - pass the
        result of `company_margin_trend_compressing()` below. None means the
        margin leg could not be evaluated (margin data unavailable).

    Returns:
      {"stage": "growth"|"maturity"|"commoditisation"|"decline", or None,
       "relative_growth_pct": float|None,   # percentage points
       "margin_inconclusive": bool,
       "reasoning": str}
      Returns stage=None (never a guess) if segment_cagr or
      sector_median_cagr is unavailable - a segment that cannot be
      classified is surfaced as such by the caller (`unclassified_pct`),
      never silently defaulted to "Maturity" or any other label.
    """
    if segment_cagr is None:
        return {
            "stage": None, "relative_growth_pct": None, "margin_inconclusive": True,
            "reasoning": "Segment CAGR unavailable - cannot classify without guessing.",
        }
    # Decline is genuinely determinable from segment_cagr ALONE (see the
    # branch below - it never reads sector_median_cagr), so a company with
    # no sector benchmark at all (routinely the case for BSE-SME/small-cap
    # filers outside the fixed NSE Total Market universe - confirmed real
    # on Prime Fresh Limited) can still be correctly classified Decline
    # rather than left permanently Unclassified just because the OTHER
    # three stages (which do need the sector comparison) can't be reached.
    if sector_median_cagr is None and segment_cagr >= 0:
        return {
            "stage": None, "relative_growth_pct": None, "margin_inconclusive": True,
            "reasoning": "Sector-median CAGR unavailable - Growth/Maturity/Commoditisation need a sector comparison, but Decline is ruled out (segment revenue is not shrinking).",
        }

    relative_growth_pct = round((segment_cagr - sector_median_cagr) * 100, 2) if sector_median_cagr is not None else None

    # Decline takes priority over everything else, regardless of the sector
    # comparison - a segment that is genuinely shrinking is in decline even
    # if it happens to be shrinking slightly LESS than a collapsing sector.
    if segment_cagr < 0:
        return {
            "stage": "decline", "relative_growth_pct": relative_growth_pct, "margin_inconclusive": False,
            "reasoning": f"Segment revenue CAGR is negative ({segment_cagr * 100:.1f}%) - declining regardless of sector comparison.",
        }

    if relative_growth_pct >= RELATIVE_GROWTH_THRESHOLD_PP:
        return {
            "stage": "growth", "relative_growth_pct": relative_growth_pct, "margin_inconclusive": False,
            "reasoning": f"Segment CAGR beats the sector median by {relative_growth_pct:+.1f}pp - outgrowing the sector.",
        }

    if relative_growth_pct <= -RELATIVE_GROWTH_THRESHOLD_PP:
        margin_compressing = (company_margin_trend or {}).get("compressing")
        if margin_compressing is True:
            return {
                "stage": "commoditisation", "relative_growth_pct": relative_growth_pct, "margin_inconclusive": False,
                "reasoning": (f"Segment CAGR trails the sector median by {relative_growth_pct:.1f}pp AND the "
                              f"company's overall EBITDA margin is compressing over the same window - consistent "
                              f"with commoditisation pressure (company-level margin proxy, not true segment margin)."),
            }
        return {
            "stage": "maturity", "relative_growth_pct": relative_growth_pct, "margin_inconclusive": True,
            "reasoning": (f"Segment CAGR trails the sector median by {relative_growth_pct:.1f}pp, but company-level "
                          f"EBITDA margin is NOT confirmed compressing - below-sector growth alone is not enough to "
                          f"call this Commoditisation without the margin-compression evidence; treated as Maturity."),
        }

    return {
        "stage": "maturity", "relative_growth_pct": relative_growth_pct, "margin_inconclusive": False,
        "reasoning": f"Segment CAGR is roughly in line with the sector median ({relative_growth_pct:+.1f}pp).",
    }


def company_margin_trend_compressing(margins_annual, lookback_years=3):
    """
    Company-level EBITDA-margin-compression check (the documented proxy for
    Commoditisation's margin leg - see module docstring). `margins_annual` is
    the SAME chronological (oldest-first) list tools/metrics_engine.py
    already returns (`F-06_Margin_Analysis.margins_annual`, entries with an
    'ebitda_margin' key) - that list appends a trailing "TTM" (trailing
    twelve months) entry after the fiscal-year ones. TTM is excluded here:
    treating it as "latest" would shift the N-year lookback off a clean
    fiscal-year-to-fiscal-year comparison (confirmed on RELIANCE - with TTM
    included, "3 years back" from a 13-entry list landed on FY2024, not
    FY2023, since TTM occupies the final slot). Excluding it keeps "latest"
    and "N years back" both anchored to real, whole fiscal years.

    Returns {"compressing": bool} or None if there isn't enough margin
    history to compare (< 2 fiscal-year points, or the two endpoints being
    compared both have a None ebitda_margin) - None, not a guessed False, so
    the caller can tell "margin data didn't confirm compression" apart from
    "no margin data at all".
    """
    fy_margins = [m for m in (margins_annual or []) if str(m.get("date", "")).upper() != "TTM"]
    if len(fy_margins) < 2:
        return None
    latest = fy_margins[-1].get("ebitda_margin")
    idx = max(0, len(fy_margins) - 1 - lookback_years)
    baseline = fy_margins[idx].get("ebitda_margin")
    if latest is None or baseline is None:
        return None
    return {"compressing": latest < baseline}


def normalize_segment_label(label):
    """Lowercase, whitespace-collapsed normalization for exact-match segment
    label comparison across fiscal years. No fuzzy/approximate matching per
    the approved plan - a company that renamed or restructured a segment
    mid-window must show that segment as unclassified (honest None), not a
    guessed match."""
    if not label:
        return ""
    return " ".join(str(label).strip().lower().split())


def compute_segment_cagr_from_multi_year(multi_year_segments):
    """
    Compute each segment's own revenue CAGR from
    tools.annual_report_financials.fetch_multi_year_segment_revenue's output
    (`{year: [{"label", "value_cr"}, ...]}`).

    Matching rule (per the approved plan): a segment only gets a computed
    CAGR if its normalized label appears in BOTH the oldest and newest
    available year - exact normalized-string match only, no fuzzy matching.
    CAGR is annualized over the actual number of years spanned (oldest to
    newest), not hardcoded to 3yr, since AR history availability varies by
    company.

    Returns {"label": {"cagr": float|None, "oldest_year": int, "newest_year": int,
                        "oldest_value_cr": float, "newest_value_cr": float}, ...}
    for every label present in the newest year - matched entries get a real
    `cagr`; unmatched/unresolvable ones get `cagr: None` (never guessed) so
    the caller can report them as unclassified rather than silently dropping
    them.
    """
    if not multi_year_segments:
        return {}
    years = sorted(multi_year_segments.keys())
    if len(years) < 2:
        return {}
    oldest_year, newest_year = years[0], years[-1]
    span_years = newest_year - oldest_year
    oldest_by_label = {normalize_segment_label(s["label"]): s for s in (multi_year_segments.get(oldest_year) or [])}
    newest_by_label = {normalize_segment_label(s["label"]): s for s in (multi_year_segments.get(newest_year) or [])}

    out = {}
    for norm_label, newest_seg in newest_by_label.items():
        display_label = newest_seg["label"]
        oldest_seg = oldest_by_label.get(norm_label)
        cagr = None
        oldest_value = oldest_seg["value_cr"] if oldest_seg else None
        newest_value = newest_seg["value_cr"]
        if oldest_seg is not None and span_years > 0:
            ov, nv = oldest_seg["value_cr"], newest_seg["value_cr"]
            if ov and nv and ov > 0 and nv > 0:
                cagr = (nv / ov) ** (1 / span_years) - 1
        out[display_label] = {
            "cagr": cagr,
            "oldest_year": oldest_year, "newest_year": newest_year,
            "oldest_value_cr": oldest_value, "newest_value_cr": newest_value,
            "matched_across_years": oldest_seg is not None,
        }
    return out
