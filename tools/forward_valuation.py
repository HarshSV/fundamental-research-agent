"""
Forward valuation engine (#10). Applies the model's projected growth (from the
ML forecast, which fits the company's own multi-year revenue/earnings) to the
latest actuals to derive FORWARD metrics — Forward EPS, Forward P/E, PEG,
EV/Sales, EV/EBITDA, Market-Cap/Sales, Forward Revenue/PAT/Margins — for +1y and
+3y. Deterministic, computed from data already in the payload. Never raises.

Rendered as a Current vs 1Y-Fwd vs 3Y-Fwd comparison table (visual, not prose).
"""

from tools.financial_analysis import _annual, _pick, _REV, _NI


def compute_forward_valuation(metrics: dict, ml_forecast: dict, info: dict) -> dict:
    try:
        val = metrics.get('F-03_Valuation_Metrics', {}) or {}
        sol = metrics.get('F-08_Solvency_Metrics', {}) or {}
        ml = ml_forecast or {}
        info = info or {}

        inc = _annual(metrics, 'income_stmt')
        if not inc:
            return {}
        y = sorted(inc.keys())[-1]
        row = inc[y] or {}
        latest_rev = _pick(row, _REV)
        latest_pat = _pick(row, _NI)
        latest_ebitda = _pick(row, ['ebitda', 'normalizedebitda']) or _pick(row, ['ebit', 'operatingincome'])

        price = val.get('last_price') or info.get('currentPrice')
        mcap = info.get('marketCap') or val.get('MarketCap')
        shares = info.get('sharesOutstanding') or val.get('SharesOutstanding')
        debt = sol.get('total_debt') or 0
        cash = sol.get('cash_equivalents') or 0
        cur_pe = val.get('PE')
        rev_cagr = ml.get('revenue_cagr')       # %
        eps_cagr = ml.get('earnings_cagr')      # %

        if not (latest_rev and latest_pat and price):
            return {}

        ev = (mcap + debt - cash) if mcap else None
        ebitda_margin = (latest_ebitda / latest_rev) if (latest_ebitda and latest_rev) else None

        def grow(base, cagr, yrs):
            if base is None or cagr is None:
                return None
            return base * ((1 + cagr / 100.0) ** yrs)

        def eps_of(pat):
            return (pat / shares) if (pat and shares) else None

        def block(yrs):
            rev = grow(latest_rev, rev_cagr, yrs)
            pat = grow(latest_pat, eps_cagr, yrs)
            e = eps_of(pat)
            ebitda = (rev * ebitda_margin) if (rev and ebitda_margin) else None
            return {
                'revenue': rev, 'pat': pat, 'eps': e,
                'pe': (price / e) if (e and e > 0) else None,
                'net_margin': (pat / rev) if (pat and rev) else None,
                'ev_sales': (ev / rev) if (ev and rev) else None,
                'ev_ebitda': (ev / ebitda) if (ev and ebitda and ebitda > 0) else None,
                'mcap_sales': (mcap / rev) if (mcap and rev) else None,
            }

        cur = {
            'revenue': latest_rev, 'pat': latest_pat, 'eps': eps_of(latest_pat),
            'pe': cur_pe if cur_pe else (price / eps_of(latest_pat) if eps_of(latest_pat) else None),
            'net_margin': (latest_pat / latest_rev) if latest_rev else None,
            'ev_sales': (ev / latest_rev) if (ev and latest_rev) else None,
            'ev_ebitda': (ev / latest_ebitda) if (ev and latest_ebitda) else None,
            'mcap_sales': (mcap / latest_rev) if (mcap and latest_rev) else None,
        }
        f1, f3 = block(1), block(3)

        peg = None
        if f1.get('pe') and eps_cagr and eps_cagr > 0:
            peg = round(f1['pe'] / eps_cagr, 2)

        peg_tag = None
        if peg is not None:
            peg_tag = 'cheap vs growth' if peg < 1 else 'fair' if peg < 1.5 else 'rich vs growth'

        return {
            'current': cur, 'fwd_1y': f1, 'fwd_3y': f3,
            'revenue_cagr': rev_cagr, 'earnings_cagr': eps_cagr,
            'peg': peg, 'peg_tag': peg_tag,
            'available': True,
            'note': "Forward metrics apply the model's projected growth to the latest reported "
                    "actuals; PEG = forward P/E ÷ earnings CAGR. Projection, not guidance.",
        }
    except Exception as e:
        print(f"[forward_valuation] skipped: {e}")
        return {}
