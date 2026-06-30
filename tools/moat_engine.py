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
not meaningful for banks) — there ROE track record and profit-growth durability lead.

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
    sales_g = data.get("sales_growth_5y") or data.get("sales_growth_3y")
    profit_g = data.get("profit_growth_5y") or data.get("profit_growth_3y")

    debt_free = any("debt free" in p.lower() or "reduced debt" in p.lower() for p in (data.get("pros") or []))
    if not debt_free and fallback.get("debt_to_equity") is not None:
        debt_free = fallback["debt_to_equity"] < 0.3

    pillars, signals, warnings = [], [], []

    def add_pillar(label, score, max_pts, note):
        pillars.append({"label": label, "score": round(score, 1), "max": max_pts, "note": note})

    total = 0.0
    n_inputs = 0

    if not financial:
        # ---- Non-financial: ROCE-led moat ----------------------------------
        # 1) Return on capital (35) — level + consistency.
        roce_level = _scale(roce, 10, 30)
        roce_consist = _stability(roce_hist)
        if roce is not None:
            n_inputs += 1
            p = 25 * roce_level + 10 * (roce_consist if roce_consist is not None else roce_level)
            add_pillar("Return on Capital (ROCE)", p, 35,
                       f"ROCE {roce:.0f}%" + (f", {len(roce_hist)}-yr history" if roce_hist else ""))
            total += p
            if roce >= 25 and (roce_consist is None or roce_consist >= 0.6):
                signals.append(f"Sustained ROCE of {roce:.0f}% — exceptional, hard-to-replicate capital efficiency (hallmark of a wide moat).")
            elif roce >= 16:
                signals.append(f"Healthy ROCE of {roce:.0f}% — earns well above its cost of capital.")
            elif roce < 12:
                warnings.append(f"Low ROCE of {roce:.0f}% — little evidence of a durable competitive advantage.")

        # 2) Pricing power via operating margin (25) — level + stability.
        if opm_mean is not None:
            n_inputs += 1
            opm_level = _scale(opm_mean, 8, 25)
            opm_stab = _stability(opm_hist)
            p = 15 * opm_level + 10 * (opm_stab if opm_stab is not None else opm_level)
            add_pillar("Pricing Power (Op. Margin)", p, 25,
                       f"OPM ~{opm_mean:.0f}%" + (", stable" if (opm_stab or 0) >= 0.7 else ", variable" if opm_stab is not None else ""))
            total += p
            if opm_mean >= 20 and (opm_stab is None or opm_stab >= 0.7):
                signals.append(f"Operating margins steady around {opm_mean:.0f}% — strong, defensible pricing power.")
            elif opm_stab is not None and opm_stab < 0.5:
                warnings.append("Operating margins are volatile — limited pricing power / cyclicality.")

        # 3) ROE track record (15)
        if roe_track is not None:
            n_inputs += 1
            p = 15 * _scale(roe_track, 10, 25)
            add_pillar("ROE Track Record", p, 15, f"{roe_track:.0f}% (multi-year)")
            total += p
            if roe_track < 12 and (sales_g or 0) >= 25:
                warnings.append(f"ROE only {roe_track:.0f}% despite ~{sales_g:.0f}% sales growth — growth is capital-intensive with weak returns.")

        # 4) Balance-sheet strength (10)
        p = 10 if debt_free else 4
        add_pillar("Balance-Sheet Strength", p, 10, "Debt-free / net cash" if debt_free else "Carries debt")
        total += p
        if debt_free:
            signals.append("Debt-free / net-cash balance sheet — resilience through cycles and reinvestment optionality.")

        # 5) Working-capital efficiency (10)
        if ccc is not None:
            n_inputs += 1
            if ccc <= 0:
                p = 10
            elif ccc <= 60:
                p = 7
            elif ccc <= 120:
                p = 4
            elif ccc <= 200:
                p = 2
            else:
                p = 0
            add_pillar("Working-Capital Efficiency", p, 10, f"Cash conversion cycle {ccc:.0f} days")
            total += p
            if ccc < 0:
                signals.append("Negative cash conversion cycle — suppliers/customers fund growth (a structural advantage).")
            elif ccc > 180:
                warnings.append(f"High cash conversion cycle ({ccc:.0f} days) — heavy working-capital lockup.")

        # 6) Growth durability (5)
        if profit_g is not None or sales_g is not None:
            g = max([x for x in [profit_g, sales_g] if x is not None])
            p = 5 * _scale(g, 8, 25)
            add_pillar("Growth Durability", p, 5, f"~{g:.0f}% compounded")
            total += p

        pricing_power = round(_clamp((opm_mean or 0) / 3.0, 0, 10)) if opm_mean is not None else None
        barriers = round(_clamp((roce or 0) / 3.5, 0, 10)) if roce is not None else None

    else:
        # ---- Financials / lenders: ROE-led moat ----------------------------
        # 1) ROE track record (50)
        if roe_track is not None:
            n_inputs += 1
            p = 50 * _scale(roe_track, 8, 20)
            add_pillar("ROE Track Record", p, 50, f"{roe_track:.0f}% (multi-year)")
            total += p
            if roe_track >= 16:
                signals.append(f"Strong, consistent ROE of {roe_track:.0f}% — efficient deposit/loan franchise.")
            elif roe_track < 10:
                warnings.append(f"Subdued ROE of {roe_track:.0f}% — weaker franchise economics.")

        # 2) Profit-growth durability (25)
        if profit_g is not None:
            n_inputs += 1
            p = 25 * _scale(profit_g, 8, 22)
            add_pillar("Profit-Growth Durability", p, 25, f"~{profit_g:.0f}% CAGR")
            total += p
            if profit_g >= 15:
                signals.append(f"Compounded profit growth ~{profit_g:.0f}% — durable franchise expansion.")

        # 3) Loan/sales-growth durability (15)
        if sales_g is not None:
            n_inputs += 1
            p = 15 * _scale(sales_g, 8, 22)
            add_pillar("Book / Income Growth", p, 15, f"~{sales_g:.0f}% CAGR")
            total += p

        # 4) Payout / prudence (10)
        payout = any("dividend payout" in p.lower() for p in (data.get("pros") or []))
        p = 10 if payout else 5
        add_pillar("Capital Prudence", p, 10, "Healthy dividend payout" if payout else "Standard")
        total += p

        pricing_power = round(_clamp((roe_track or 0) / 2.0, 0, 10)) if roe_track is not None else None
        barriers = round(_clamp((roe_track or 0) / 2.0, 0, 10)) if roe_track is not None else None

    moat_score = round(_clamp(total, 0, 100))
    strength = _label(moat_score) if n_inputs >= 2 else "Unrated"

    # Confidence reflects how much real data backed the score.
    confidence = round(_clamp(40 + n_inputs * 12, 0, 95))

    if not signals:
        signals.append("No standout moat signals in the data — competitive position looks average.")

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
