"""
Data-driven, company-specific economic-moat score (F-20).

Replaces the old LLM-guessed / hardcoded-fallback moat with an objective score
computed from the parameters Screener.in publishes per company:
  - ROCE (level + multi-year consistency)  -> the single strongest moat signal
  - Operating margin (level + stability)    -> pricing power
  - ROE track record (3/5-year)             -> efficient compounding
  - Balance-sheet strength (debt-free)      -> resilience
  - Working-capital efficiency (cash conversion cycle)
  - Growth durability (compounded sales/profit growth)

Lenders/financials are scored on a separate branch (ROCE/OPM/working-capital are
not meaningful for banks) - there ROE track record and profit-growth durability lead.

Output is deterministic and differentiates companies (e.g. Nestlé = Wide, a fast-
but-capital-hungry small-cap = Narrow). An LLM may *explain* the result, but never
invents the numbers.
"""

import statistics


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _scale(x, lo, hi):
    """Linear 0..1 score for a value rising from `lo` (=0) to `hi` (=1)."""
    if x is None:
        return None
    if hi == lo:
        return 0.0
    return _clamp((x - lo) / (hi - lo))


def _mean(series):
    vals = [v for v in (series or []) if v is not None]
    return statistics.mean(vals) if vals else None


def _stability(series):
    """0..1: how stable a series is (low coefficient of variation = stable = moaty)."""
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    if m == 0:
        return None
    cov = statistics.pstdev(vals) / abs(m)
    # CoV of 0 -> 1.0 (rock-steady); CoV >= 0.5 -> 0.0 (very volatile)
    return _clamp(1 - cov / 0.5)


def _is_financial(name, data):
    nm = (name or "").lower()
    if any(w in nm for w in ["bank", "financ", "finance", "nbfc", "insurance", "housing finance", "capital"]):
        return True
    # Banks/lenders publish neither a meaningful OPM history nor a cash conversion cycle.
    if not data.get("opm_history") and not data.get("roce_history") and data.get("roe_3y") is not None:
        return True
    return False


def _label(score):
    if score is None:
        return "Unrated"
    if score >= 70:
        return "Wide"
    if score >= 50:
        return "Narrow to Wide"
    if score >= 30:
        return "Narrow"
    return "No moat"


def compute_moat(data: dict, company_name: str = None, fallback: dict = None) -> dict:
    """
    data     : dict from screener_scraper.fetch_screener_moat_data()
    fallback : optional {debt_to_equity, roce, roe, operating_margin} from our own
               metrics engine, used when Screener fields are missing.
    Returns the F-20 payload (moat_strength, scores, pillars, signals, memo, ...).
    """
    data = data or {}
    fallback = fallback or {}
    financial = _is_financial(company_name, data)

    roce = data.get("roce_latest")
    if roce is None:
        roce = fallback.get("roce")
    roce_hist = data.get("roce_history") or []
    opm_hist = data.get("opm_history") or []
    opm_mean = _mean(opm_hist)
    if opm_mean is None and fallback.get("operating_margin") is not None:
        opm_mean = fallback["operating_margin"] * 100  # fraction -> %
    roe_track = data.get("roe_3y") or data.get("roe_5y") or data.get("roe_latest") or fallback.get("roe")
    ccc = data.get("cash_conversion_cycle")
    # Fall back to our own metrics-engine CAGRs when Screener's ranges-tables don't
    # parse (common for insurers/NBFCs) - this keeps lenders from scoring "Unrated".
    sales_g = data.get("sales_growth_5y") or data.get("sales_growth_3y") or fallback.get("sales_growth")
    profit_g = data.get("profit_growth_5y") or data.get("profit_growth_3y") or fallback.get("profit_growth")

    debt_free = any("debt free" in p.lower() or "reduced debt" in p.lower() for p in (data.get("pros") or []))
    if not debt_free and fallback.get("debt_to_equity") is not None:
        debt_free = fallback["debt_to_equity"] < 0.3

    pillars, signals, warnings = [], [], []
    total = 0.0
    n_inputs = 0

    def add_check(label, points, max_pts, basis):
        """One transparent, threshold-based check (the exact aspect + measured value)."""
        ratio = (points / max_pts) if max_pts else 0
        result = "strong" if ratio >= 0.8 else "ok" if ratio >= 0.4 else "weak"
        pillars.append({"label": label, "score": round(points, 1), "max": max_pts,
                        "basis": basis, "result": result, "note": basis})
        return points

    def _band(x, thresholds):
        """thresholds: list of (min_value, points) high->low; returns points for x."""
        for mn, pts in thresholds:
            if x >= mn:
                return pts
        return 0

    if not financial:
        # ============ Non-financial: capital-efficiency-led moat ============
        # 1) ROCE level (20) - the single strongest moat signal.
        if roce is not None:
            n_inputs += 1
            p = _band(roce, [(20, 20), (15, 14), (12, 8), (10, 4)])
            total += add_check("ROCE - level", p, 20,
                               f"ROCE {roce:.0f}%  (≥20%→full · ≥15% · ≥12% · <10%→0)")
            if roce >= 20:
                signals.append(f"High ROCE of {roce:.0f}% - earns far above its cost of capital, the hallmark of a real moat.")
            elif roce < 12:
                warnings.append(f"Low ROCE of {roce:.0f}% - little evidence of a durable competitive edge.")

        # 2) ROCE consistency (10) - is the high return SUSTAINED?
        if roce_hist and len(roce_hist) >= 2:
            n_inputs += 1
            lo = min(roce_hist)
            p = _band(lo, [(18, 10), (14, 7), (10, 4)])
            total += add_check("ROCE - consistency", p, 10,
                               f"{len(roce_hist)}-yr ROCE low {lo:.0f}%, range {lo:.0f}–{max(roce_hist):.0f}%  (floor ≥18%→full)")
            if lo >= 18:
                signals.append(f"ROCE stayed above {lo:.0f}% every year - a consistently high return, not a one-off.")

        # 3) Operating-margin level (15) - pricing power.
        if opm_mean is not None:
            n_inputs += 1
            p = _band(opm_mean, [(20, 15), (15, 10), (10, 5)])
            total += add_check("Operating margin - level", p, 15,
                               f"OPM ~{opm_mean:.0f}%  (≥20%→full · ≥15% · ≥10% · <10%→0)")

        # 4) Operating-margin stability (10) - pricing power = steady margins.
        if opm_hist and len(opm_hist) >= 3:
            n_inputs += 1
            stab = _stability(opm_hist) or 0
            p = round(10 * stab, 1)
            total += add_check("Operating margin - stability", p, 10,
                               f"OPM {min(opm_hist):.0f}–{max(opm_hist):.0f}% over {len(opm_hist)} yrs  ({'steady' if stab >= 0.7 else 'variable'})")
            if opm_mean and opm_mean >= 18 and stab >= 0.7:
                signals.append(f"Operating margins held steady around {opm_mean:.0f}% for years - defensible pricing power.")
            elif stab < 0.5:
                warnings.append("Operating margins are volatile year to year - limited pricing power / cyclical.")

        # 5) ROE track record (15).
        if roe_track is not None:
            n_inputs += 1
            p = _band(roe_track, [(18, 15), (15, 11), (12, 6)])
            total += add_check("ROE - 3-yr track record", p, 15,
                               f"{roe_track:.0f}%  (≥18%→full · ≥15% · ≥12% · <12%→0)")
            if roe_track < 12 and (sales_g or 0) >= 25:
                warnings.append(f"ROE only {roe_track:.0f}% despite ~{sales_g:.0f}% sales growth - growth is capital-hungry with weak returns.")

        # 6) Balance-sheet strength (10).
        n_inputs += 1
        p = 10 if debt_free else (6 if (fallback.get("debt_to_equity") or 9) < 0.5 else 3)
        total += add_check("Balance sheet - leverage", p, 10,
                           "Debt-free / net cash" if debt_free else "Carries debt")
        if debt_free:
            signals.append("Debt-free / net-cash balance sheet - resilience through downturns and reinvestment optionality.")

        # 7) Working-capital efficiency (10) - cash conversion cycle.
        if ccc is not None:
            n_inputs += 1
            p = _band(-ccc if ccc < 0 else -0.001, [(0, 10)]) or _band(ccc, [(9999, 0)])
            p = 10 if ccc <= 0 else (7 if ccc <= 45 else 4 if ccc <= 90 else 2 if ccc <= 180 else 0)
            total += add_check("Working-capital efficiency", p, 10,
                               f"Cash conversion cycle {ccc:.0f} days  (negative→full · <45 · <90 · >180→0)")
            if ccc < 0:
                signals.append("Negative cash-conversion cycle - suppliers/customers fund its growth, a structural advantage.")
            elif ccc > 180:
                warnings.append(f"High cash-conversion cycle ({ccc:.0f} days) - heavy working-capital lock-up.")

        # 8) Growth durability (10).
        if profit_g is not None or sales_g is not None:
            n_inputs += 1
            g = max([x for x in [profit_g, sales_g] if x is not None])
            p = _band(g, [(18, 10), (12, 7), (8, 4)])
            total += add_check("Growth durability", p, 10,
                               f"~{g:.0f}% compounded  (≥18%→full · ≥12% · ≥8% · <8%→0)")

        pricing_power = round(_clamp((opm_mean or 0) / 3.0, 0, 10)) if opm_mean is not None else None
        # Barriers scaled to ROCE but capped down when margins are unstable (not a real moat).
        _stab = _stability(opm_hist) if opm_hist else 1
        barriers = round(_clamp((roce or 0) / 3.5, 0, 10) * (0.6 + 0.4 * (_stab or 1))) if roce is not None else None
        if pricing_power is not None and (_stab or 1) < 0.5:
            pricing_power = min(pricing_power, 5)  # unstable margins ≠ pricing power

    else:
        # ==================== Financials / lenders ====================
        if roe_track is not None:
            n_inputs += 1
            p = _band(roe_track, [(18, 40), (15, 30), (12, 18), (10, 8)])
            total += add_check("ROE - 3-yr track record", p, 40,
                               f"{roe_track:.0f}%  (≥18%→full · ≥15% · ≥12% · <10%→0)")
            if roe_track >= 15:
                signals.append(f"Consistent ROE of {roe_track:.0f}% - an efficient deposit/loan franchise.")
            elif roe_track < 10:
                warnings.append(f"Subdued ROE of {roe_track:.0f}% - weaker franchise economics.")

        if profit_g is not None:
            n_inputs += 1
            p = _band(profit_g, [(18, 25), (12, 17), (8, 9)])
            total += add_check("Profit-growth durability", p, 25, f"~{profit_g:.0f}% 5-yr CAGR")
            if profit_g >= 15:
                signals.append(f"Compounded profit growth ~{profit_g:.0f}% - durable franchise expansion.")

        if sales_g is not None:
            n_inputs += 1
            p = _band(sales_g, [(18, 20), (12, 13), (8, 7)])
            total += add_check("Book / income growth", p, 20, f"~{sales_g:.0f}% 5-yr CAGR")

        payout = any("dividend payout" in p.lower() for p in (data.get("pros") or []))
        n_inputs += 1
        total += add_check("Capital prudence", 15 if payout else 7, 15,
                           "Healthy dividend payout" if payout else "Standard payout")

        pricing_power = round(_clamp((roe_track or 0) / 2.0, 0, 10)) if roe_track is not None else None
        barriers = round(_clamp((roe_track or 0) / 2.0, 0, 10)) if roe_track is not None else None

    # Normalise to 0-100 across the aspects we actually had data for (so a stock
    # missing one input isn't unfairly penalised vs the full 100-point scale).
    max_possible = sum(pl["max"] for pl in pillars) or 1
    moat_score = round(_clamp(total / max_possible * 100, 0, 100))
    strength = _label(moat_score) if n_inputs >= 3 else "Unrated"

    # Confidence reflects how much real data backed the score.
    confidence = round(_clamp(40 + n_inputs * 12, 0, 95))

    if not signals:
        signals.append("No standout moat signals in the data - competitive position looks average.")

    # Fold in Screener's own auto-generated flags as supporting context.
    screener_pros = [p for p in (data.get("pros") or []) if p][:4]
    screener_cons = [c for c in (data.get("cons") or []) if c][:3]

    nm = company_name or data.get("symbol") or "The company"
    memo = (
        f"{nm} scores {moat_score}/100 on the data-driven moat assessment "
        f"({strength}). " + " ".join(signals[:2]) +
        (" " + warnings[0] if warnings else "")
    )

    return {
        "moat_strength": strength,
        "moat_score": moat_score,
        "confidence_level": confidence,
        "pricing_power": pricing_power if pricing_power is not None else 5,
        "barriers_to_entry": barriers if barriers is not None else 5,
        "is_financial": financial,
        "pillars": pillars,
        "signals": signals,
        "warnings": warnings,
        "screener_pros": screener_pros,
        "screener_cons": screener_cons,
        "memo_text": memo,
        "method": "data-driven (Screener.in fundamentals)",
    }


if __name__ == "__main__":
    import sys, json
    from tools.screener_scraper import fetch_screener_moat_data
    sym = sys.argv[1] if len(sys.argv) > 1 else "NESTLEIND"
    d = fetch_screener_moat_data(sym)
    print(json.dumps(compute_moat(d, sym), indent=2, ensure_ascii=False))
