"""
SOIC-style deterministic fundamental analysis, computed from the 12-year financial
statements the metrics engine already produces. No LLM, no network — pure math, so
it is fast, reliable and identical every run. Powers three VISUAL modules:

  1. Piotroski F-Score (0-9)      — classic quality/quant scorecard
  2. DuPont ROE decomposition     — what actually drives ROE
  3. Financial-health checklist   — green/yellow/red on the "Financial statements
                                    in 2 minutes" questions (balance-sheet strength,
                                    leverage trend, cash-flow strength, internal
                                    accruals, growth, CFO/PAT conversion, ROE/ROCE,
                                    margin durability).

Every row carries the measured value + a one-line plain-English verdict so the UI
can render tables/scorecards instead of paragraphs. Never raises.
"""


def _annual(metrics, stmt):
    return ((metrics.get('F-01_Financial_Statements', {}) or {}).get('annual', {}) or {}).get(stmt, {}) or {}


def _pick(row, names):
    """Value for the first matching row label (normalised, exact then substring)."""
    if not isinstance(row, dict):
        return None
    norm = {str(k).lower().replace(' ', ''): v for k, v in row.items()}
    for n in names:
        if norm.get(n) is not None:
            return norm[n]
    for n in names:
        for k, v in norm.items():
            if n in k and v is not None:
                return v
    return None


_REV = ['totalrevenue', 'revenue', 'operatingrevenue']
_NI = ['netincome', 'netincomecommonstockholders']
_EBIT = ['ebit', 'operatingincome']
_ASSETS = ['totalassets']
_EQUITY = ['stockholdersequity', 'commonstockequity', 'totalequitygrossminorinterest']
_DEBT = ['totaldebt', 'longtermdebt']
_CURL = ['currentliabilities', 'totalcurrentliabilities']
_CFO = ['operatingcashflow', 'cashflowfromcontinuingoperatingactivities',
        'netcashprovidedbyoperatingactivities']
_EPS = ['dilutedeps', 'basiceps']


def _series(metrics):
    """Per-year dict of the raw lines we need, sorted oldest->newest."""
    inc = _annual(metrics, 'income_stmt')
    bs = _annual(metrics, 'balance_sheet')
    cf = _annual(metrics, 'cash_flow')
    years = sorted(inc.keys())
    out = []
    for y in years:
        irow, brow, crow = inc.get(y) or {}, bs.get(y) or {}, cf.get(y) or {}
        ni = _pick(irow, _NI)
        rev = _pick(irow, _REV)
        eps = _pick(irow, _EPS)
        out.append({
            'year': y,
            'net_income': ni,
            'revenue': rev,
            'ebit': _pick(irow, _EBIT),
            'assets': _pick(brow, _ASSETS),
            'equity': _pick(brow, _EQUITY),
            'debt': _pick(brow, _DEBT),
            'curr_liab': _pick(brow, _CURL),
            'cfo': _pick(crow, _CFO),
            'eps': eps,
            # implied share count (net income / EPS) — lets us detect dilution
            'shares': (ni / eps) if (ni and eps and eps != 0) else None,
        })
    return out


def _fy(year_key):
    """'2024-03-31' -> 'FY24'."""
    try:
        return f"FY{str(year_key)[2:4]}"
    except Exception:
        return str(year_key)


def _is_financial(name):
    nm = (name or "").lower()
    return any(w in nm for w in ["bank", "financ", "finance", "nbfc", "insurance",
                                 "insurer", "life ", "lombard", "housing finance",
                                 "capital", "fintech", "gic ", "amc", "asset management"])


def compute_piotroski(series, is_financial=False):
    """Classic 9-point Piotroski F-Score (this year vs last). Components whose
    inputs are unavailable are marked None and excluded from the max, so the score
    is honest (shown as X / available). For lenders, the leverage/liquidity/cash-flow
    components are excluded (the F-Score is designed for non-financials — banks are
    structurally leveraged and their cash flows aren't comparable)."""
    if len(series) < 2:
        return None
    cur, prev = series[-1], series[-2]
    checks = []

    def add(name, passed, detail, na=False):
        checks.append({'name': name, 'pass': (None if na else passed),
                       'detail': ("Not applicable to lenders" if na else detail),
                       'na': na})

    # --- Profitability ---
    roa_c = (cur['net_income'] / cur['assets']) if (cur['net_income'] is not None and cur['assets']) else None
    roa_p = (prev['net_income'] / prev['assets']) if (prev['net_income'] is not None and prev['assets']) else None
    add('Positive net income', (cur['net_income'] > 0) if cur['net_income'] is not None else None,
        f"Net profit {_cr(cur['net_income'])}")
    add('Positive operating cash flow', (cur['cfo'] > 0) if cur['cfo'] is not None else None,
        f"CFO {_cr(cur['cfo'])}", na=is_financial)
    add('Rising return on assets', (roa_c > roa_p) if (roa_c is not None and roa_p is not None) else None,
        f"ROA {_pct(roa_c)} vs {_pct(roa_p)}")
    add('Cash flow exceeds profit (quality)',
        (cur['cfo'] > cur['net_income']) if (cur['cfo'] is not None and cur['net_income'] is not None) else None,
        f"CFO {_cr(cur['cfo'])} vs PAT {_cr(cur['net_income'])}", na=is_financial)
    # --- Leverage / liquidity (not applicable to lenders) ---
    lev_c = (cur['debt'] / cur['assets']) if (cur['debt'] is not None and cur['assets']) else None
    lev_p = (prev['debt'] / prev['assets']) if (prev['debt'] is not None and prev['assets']) else None
    add('Falling leverage', (lev_c < lev_p) if (lev_c is not None and lev_p is not None) else None,
        f"Debt/assets {_pct(lev_c)} vs {_pct(lev_p)}", na=is_financial)
    cr_c = (cur['assets'] / cur['curr_liab']) if (cur['assets'] and cur['curr_liab']) else None
    cr_p = (prev['assets'] / prev['curr_liab']) if (prev['assets'] and prev['curr_liab']) else None
    add('Improving liquidity', (cr_c > cr_p) if (cr_c is not None and cr_p is not None) else None,
        "Current-ratio proxy improved" if (cr_c and cr_p and cr_c > cr_p) else "Flat/weaker", na=is_financial)
    add('No share dilution',
        (cur['shares'] <= prev['shares'] * 1.02) if (cur['shares'] and prev['shares']) else None,
        "Share count stable" if (cur['shares'] and prev['shares'] and cur['shares'] <= prev['shares'] * 1.02)
        else "Shares increased")
    # --- Efficiency (operating margin / asset turnover not meaningful for lenders) ---
    gm_c = (cur['ebit'] / cur['revenue']) if (cur['ebit'] is not None and cur['revenue']) else None
    gm_p = (prev['ebit'] / prev['revenue']) if (prev['ebit'] is not None and prev['revenue']) else None
    add('Rising operating margin', (gm_c > gm_p) if (gm_c is not None and gm_p is not None) else None,
        f"Op margin {_pct(gm_c)} vs {_pct(gm_p)}", na=is_financial)
    at_c = (cur['revenue'] / cur['assets']) if (cur['revenue'] and cur['assets']) else None
    at_p = (prev['revenue'] / prev['assets']) if (prev['revenue'] and prev['assets']) else None
    add('Rising asset turnover', (at_c > at_p) if (at_c is not None and at_p is not None) else None,
        f"Asset turnover {_num(at_c)} vs {_num(at_p)}", na=is_financial)

    scored = [c for c in checks if c['pass'] is not None]
    score = sum(1 for c in scored if c['pass'])
    # Band on the RATIO of passed checks, so lenders (fewer applicable checks) are
    # judged fairly: >=0.7 strong, >=0.44 average (mirrors classic 7/9, 4/9 cutoffs).
    ratio = (score / len(scored)) if scored else 0
    band = ('Strong' if ratio >= 0.7 else 'Average' if ratio >= 0.44 else 'Weak') if scored else 'Unavailable'
    return {
        'score': score,
        'max': len(scored),
        'classic_max': 9,
        'band': band,
        'checks': checks,
        'as_of': _fy(cur['year']),
        'note': "Piotroski F-Score: 9 pass/fail tests of profitability, leverage and "
                "efficiency (this year vs last). 7-9 strong, 4-6 average, 0-3 weak.",
    }


def compute_dupont(series):
    """ROE = Net margin x Asset turnover x Equity multiplier (latest year), plus a
    short history so the UI can show which lever drives ROE."""
    rows = []
    for s in series:
        if s['net_income'] is None or not s['revenue'] or not s['assets'] or not s['equity']:
            continue
        nm = s['net_income'] / s['revenue']
        at = s['revenue'] / s['assets']
        em = s['assets'] / s['equity']
        rows.append({'year': _fy(s['year']), 'net_margin': round(nm * 100, 1),
                     'asset_turnover': round(at, 2), 'equity_multiplier': round(em, 2),
                     'roe': round(nm * at * em * 100, 1)})
    if not rows:
        return None
    latest = rows[-1]
    driver = max([('profitability (net margin)', latest['net_margin'] / 100),
                  ('efficiency (asset turnover)', latest['asset_turnover']),
                  ('leverage (equity multiplier)', latest['equity_multiplier'] - 1)],
                 key=lambda x: x[1])[0]
    return {
        'latest': latest, 'series': rows[-6:],
        'primary_driver': driver,
        'note': f"DuPont splits ROE of {latest['roe']}% into margin x turnover x leverage. "
                f"Here ROE is driven mainly by {driver}.",
    }


def _status(value, green, amber, higher_better=True):
    if value is None:
        return 'grey'
    if higher_better:
        return 'green' if value >= green else 'amber' if value >= amber else 'red'
    return 'green' if value <= green else 'amber' if value <= amber else 'red'


def compute_health(metrics, series, is_financial=False):
    """Green/amber/red checklist mirroring the SOIC 'financial statements in 2 mins'
    questions. Each row: {question, value, status, verdict}. For lenders, the
    leverage/cash-flow questions (which don't apply to banks) are reframed rather
    than red-flagged."""
    sol = metrics.get('F-08_Solvency_Metrics', {}) or {}
    cq = metrics.get('F-09_Cash_Flow_Conversion', {}) or {}
    gs = metrics.get('F-05_Growth_Summary', {}) or {}
    ma = metrics.get('F-06_Margin_Analysis', {}) or {}
    ratios = metrics.get('F-02_Ratio_Analysis', []) or []
    latest_r = ratios[-1] if ratios else {}
    rows = []

    def row(q, value_str, status, verdict):
        rows.append({'question': q, 'value': value_str, 'status': status, 'verdict': verdict})

    if is_financial:
        # For lenders/insurers, leverage & operating cash flow are structural, not
        # a weakness — assess the franchise on growth, returns and stability instead.
        row("Balance sheet / leverage", "Inherent to lending", 'grey',
            "Leverage is core to a lender's model — judged via ROE & growth, not D/E")
    else:
        # 1. Balance-sheet strength (D/E level)
        de = sol.get('debt_to_equity')
        row("Strong balance sheet?", f"D/E {_num(de)}" if de is not None else "N/A",
            _status(de, 0.5, 1.0, higher_better=False),
            "Comfortably low leverage" if (de is not None and de < 0.5) else
            "Manageable leverage" if (de is not None and de < 1.0) else
            "Elevated leverage" if de is not None else "Debt data unavailable")

        # 2. Leverage trend (D/E now vs ~3y ago via debt/assets)
        lev = [(s['debt'] / s['assets']) for s in series if s['debt'] is not None and s['assets']]
        trend = None
        if len(lev) >= 2:
            trend = lev[-1] - lev[0]
        row("Leverage improving over time?",
            (f"{_pct(lev[0])} -> {_pct(lev[-1])}" if lev else "N/A"),
            ('green' if (trend is not None and trend < -0.01) else 'amber' if (trend is not None and trend <= 0.01) else 'red' if trend is not None else 'grey'),
            "Deleveraging" if (trend is not None and trend < -0.01) else
            "Broadly stable" if (trend is not None and trend <= 0.01) else
            "Leverage rising" if trend is not None else "Insufficient history")

        # 3. Cash flows strong?
        cfos = [s['cfo'] for s in series if s['cfo'] is not None]
        pos = sum(1 for c in cfos if c > 0)
        row("Are operating cash flows strong?",
            (f"{pos}/{len(cfos)} yrs positive" if cfos else "N/A"),
            ('green' if (cfos and pos == len(cfos)) else 'amber' if (cfos and pos >= len(cfos) * 0.7) else 'red' if cfos else 'grey'),
            "Consistently cash-generative" if (cfos and pos == len(cfos)) else
            "Mostly positive" if (cfos and pos >= len(cfos) * 0.7) else
            "Erratic cash generation" if cfos else "Cash-flow data unavailable")

        # 4. Can it fund growth from internal accruals (FCF positive)?
        fcf = cq.get('FCF')
        row("Can it fund growth internally?",
            (f"FCF {_cr(fcf)}" if fcf is not None else "N/A"),
            _status(fcf, 0, -1, higher_better=True) if fcf is not None else 'grey',
            "Self-funding (positive FCF)" if (fcf is not None and fcf > 0) else
            "Relies on external funding" if fcf is not None else "FCF unavailable")

    # 5. Sales & profit growth
    sg = gs.get('cagr_3y_revenue')
    pg = gs.get('cagr_3y_pat')
    row("Healthy sales & profit growth?",
        (f"Rev {_pct(sg)} / PAT {_pct(pg)} 3y CAGR" if (sg is not None or pg is not None) else "N/A"),
        _status(max([x for x in [sg, pg] if x is not None], default=None), 0.12, 0.0),
        "Compounding well" if ((sg or 0) >= 0.12 or (pg or 0) >= 0.12) else
        "Modest growth" if (sg is not None or pg is not None) else "Growth data unavailable")

    # 6. CFO/PAT conversion (not meaningful for lenders)
    if not is_financial:
        conv = cq.get('CFO_to_PAT')
        row("Converting profit into cash?",
            (f"CFO/PAT {_num(conv)}" if conv is not None else "N/A"),
            _status(conv, 0.8, 0.5),
            "Profits are cash-backed" if (conv is not None and conv >= 0.8) else
            "Partial conversion" if (conv is not None and conv >= 0.5) else
            "Weak conversion" if conv is not None else "Unavailable")

    # 7. Profitability — ROE only for lenders (ROCE is not meaningful for banks)
    roce = latest_r.get('ROCE')
    roe = latest_r.get('ROE')
    if is_financial:
        row("Strong profitability (ROE)?",
            (f"ROE {_pct(roe)}" if roe is not None else "N/A"),
            _status(roe, 0.15, 0.10),
            "Efficient lending franchise" if (roe or 0) >= 0.15 else
            "Average returns" if roe is not None else "Unavailable")
    else:
        row("Strong profitability (ROE/ROCE)?",
            (f"ROCE {_pct(roce)} / ROE {_pct(roe)}" if (roce is not None or roe is not None) else "N/A"),
            _status(max([x for x in [roce, roe] if x is not None], default=None), 0.15, 0.10),
            "High returns on capital" if ((roce or 0) >= 0.15 or (roe or 0) >= 0.15) else
            "Average returns" if (roce is not None or roe is not None) else "Unavailable")

    # 8. Margin durability (EBIT margin not meaningful for lenders)
    if not is_financial:
        tag = ma.get('margin_status_tag')
        row("Are margins holding up?",
            (tag.title() if tag else "N/A"),
            ('green' if tag in ('IMPROVING', 'STABLE') else 'red' if tag == 'DETERIORATING' else 'grey'),
            "Stable/improving margins" if tag in ('IMPROVING', 'STABLE') else
            "Margins compressing" if tag == 'DETERIORATING' else "Unavailable")

    counts = {'green': sum(1 for r in rows if r['status'] == 'green'),
              'amber': sum(1 for r in rows if r['status'] == 'amber'),
              'red': sum(1 for r in rows if r['status'] == 'red'),
              'grey': sum(1 for r in rows if r['status'] == 'grey')}
    scored = counts['green'] + counts['amber'] + counts['red']
    grade = ('Good' if scored and counts['green'] >= scored * 0.6 and counts['red'] == 0
             else 'Average' if scored and counts['red'] <= 1 else 'Weak' if scored else 'Unavailable')
    return {'rows': rows, 'counts': counts, 'grade': grade}


# --- tiny formatters (kept local so this module is self-contained) ---
def _cr(x):
    try:
        v = float(x) / 1e7
        return f"Rs {v:,.0f} Cr"
    except Exception:
        return "N/A"


def _pct(x, d=1):
    try:
        return f"{float(x) * 100:.{d}f}%"
    except Exception:
        return "N/A"


def _num(x, d=2):
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return "N/A"


def compute_financial_analysis(metrics: dict) -> dict:
    """Top-level entry: returns {piotroski, dupont, health, is_financial} or {}."""
    try:
        series = _series(metrics or {})
        if not series:
            return {}
        is_fin = _is_financial(metrics.get('company_name') or metrics.get('symbol'))
        return {
            'is_financial': is_fin,
            'piotroski': compute_piotroski(series, is_fin),
            'dupont': compute_dupont(series),
            'health': compute_health(metrics, series, is_fin),
        }
    except Exception as e:
        print(f"[financial_analysis] skipped: {e}")
        return {}
