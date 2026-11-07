"""Key Metrics ratios from the stored Screener statements, each on two bases where both exist:

  ttm     last four reported quarters (Screener's TTM column); balance-sheet items from the latest balance sheet
  annual  the last full financial year

A basis that cannot be computed is None (never 0). Point-in-time items (book value, dividend yield, promoter holding)
carry a single value. Financial companies (banks, lenders) get no interest coverage: interest is their raw material.
"""
from __future__ import annotations

import math


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _pct(n, d):
    n, d = _num(n), _num(d)
    return round(n / d * 100.0, 2) if n is not None and d not in (None, 0) else None


def _roe(n, equity):
    """Return on equity in %; positive equity only, and not beyond +-500%: a result like that means the equity figure on
    the page is not the real net worth (a new listing, a unit mix-up), so it is left blank rather than shown."""
    v = _pct(n, equity if (equity or 0) > 0 else None)
    return v if v is not None and abs(v) <= 500 else None


def _first(row, *keys):
    for k in keys:
        v = _num((row or {}).get(k))
        if v is not None:
            return v
    return None


def _ni(row):
    return _first(row, "Net Income Common Stockholders", "Net Income")


def _is_period(col: str) -> bool:
    return isinstance(col, str) and len(col) >= 4 and col[:4].isdigit()


def _periods(grid: dict) -> list:
    return sorted(c for c in (grid or {}) if _is_period(c))


def _coverage(ebit, interest):
    ebit, interest = _num(ebit), _num(interest)
    if ebit is None or interest is None or interest <= 0:
        return None            # no interest cost: coverage is not a meaningful number
    return round(ebit / interest, 2)


def _growth(new, old):
    new, old = _num(new), _num(old)
    if new is None or old is None or old <= 0:
        return None
    return round((new / old - 1.0) * 100.0, 2)


def compute(payload: dict | None, financial: bool = False) -> dict | None:
    """payload = the dict returned by tools.screener_scraper.fetch_screener_financials."""
    if not payload:
        return None
    fa = payload.get("financial_arrays") or {}
    inc, bs, q = fa.get("income_stmt") or {}, fa.get("balance_sheet") or {}, fa.get("quarterly_income_stmt") or {}
    info = payload.get("info") or {}

    years = _periods(inc)
    fy = inc.get(years[-1]) if years else None
    fy_prev = inc.get(years[-2]) if len(years) > 1 else None
    ttm = inc.get("TTM")
    bs_cols = _periods(bs)
    eq_latest = _first(bs.get(bs_cols[-1]), "Stockholders Equity", "Common Stock Equity") if bs_cols else None
    fy_col = years[-1] if years else None
    eq_fy = _first(bs.get(fy_col), "Stockholders Equity", "Common Stock Equity") if fy_col in bs else None

    # Revenue growth, TTM basis: the last four quarters against the four before them.
    qcols = _periods(q)
    growth_ttm = None
    if len(qcols) >= 8:
        last4 = [_first(q[c], "Total Revenue", "Revenue") for c in qcols[-4:]]
        prev4 = [_first(q[c], "Total Revenue", "Revenue") for c in qcols[-8:-4]]
        if all(v is not None for v in last4 + prev4):
            growth_ttm = _growth(sum(last4), sum(prev4))

    rev = lambda row: _first(row, "Total Revenue", "Revenue")
    book = _num(info.get("bookValue"))
    dy = _num(info.get("dividendYield"))
    promoter = _num(((payload.get("shareholding") or {}).get("latest") or {}).get("promoter"))
    return {
        "annual_label": f"FY{fy_col[2:4]}" if fy_col else None,
        # a return on equity needs positive equity: with negative book value the ratio flips sign and means nothing
        "roe": {"ttm": _roe(_ni(ttm), eq_latest), "annual": _roe(_ni(fy), eq_fy)},
        "net_margin": {"ttm": _pct(_ni(ttm), rev(ttm)), "annual": _pct(_ni(fy), rev(fy))},
        "revenue_growth": {"ttm": growth_ttm, "annual": _growth(rev(fy), rev(fy_prev))},
        "interest_coverage": (None if financial else
                              {"ttm": _coverage(_first(ttm, "EBIT", "Operating Income"), _first(ttm, "Interest Expense")),
                               "annual": _coverage(_first(fy, "EBIT", "Operating Income"), _first(fy, "Interest Expense"))}),
        "book_value": book if book and book > 0 else None,
        "dividend_yield": round(dy * 100.0, 2) if dy is not None else None,
        "promoter": promoter,
    }
