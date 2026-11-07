"""Free cash flow by financial year, read from the 'Free Cash Flow' row of Screener.in's cash-flow table (Screener defines it as
cash from operating activity less the fixed assets purchased). A company whose table has no such row (banks and other lenders, for
example) returns None: it is reported as unavailable, never as zero or computed from guesses."""
from __future__ import annotations

import re
import time

from . import screener_scraper as sc

TTL = 12 * 3600


def _page(url: str) -> str | None:
    """Screener answers 429 / an empty page when it is throttling, so retry a few times before giving up."""
    for attempt in range(4):
        html = sc._get(url)
        if html:
            return html
        time.sleep(1.5 * (attempt + 1))
    return None


def _table(sym: str) -> tuple[dict, str] | None:
    """The cash-flow table, consolidated first. A company that has consolidated accounts is never read from its standalone page (a
    throttled consolidated page would otherwise quietly give standalone figures): standalone is used only when the standalone page
    itself shows there are no consolidated accounts."""
    slug = sc._SYMBOL_MAP.get(sym, sym)
    html = _page(f"https://www.screener.in/company/{slug}/consolidated/")
    if html:
        t = sc._parse_data_table(html, "cash-flow")
        if t["periods"] and t["rows"]:
            return t, "consolidated"
    st = _page(f"https://www.screener.in/company/{slug}/")
    if st and f"/company/{slug}/consolidated/" not in st:
        t = sc._parse_data_table(st, "cash-flow")
        if t["periods"] and t["rows"]:
            return t, "standalone"
    return None


def free_cash_flow(symbol: str, years: int = 5) -> dict | None:
    """{'basis', 'rows': [{'period': 'Mar 2026', 'fcf_cr': .., 'cfo_cr': ..}]} newest last, or None when Screener gives no FCF row."""
    sym = symbol.strip().upper().replace(".NS", "")
    ck = f"fcf1_{sym}"
    hit = sc._read_cache(ck, TTL)
    if hit is not None:
        return hit.get("result")
    got = _table(sym)
    if not got:
        return None                      # could not be read right now: not cached, so the next view tries again
    t, basis = got
    fcf = next((v for k, v in t["rows"].items() if k.startswith("free cash flow")), None)
    if not fcf:
        sc._write_cache(ck, {"result": None})   # the page was read and has no FCF row: remember that
        return None
    cfo = sc._row_pick(t["rows"], ["cash from operating activity", "cash from operating activities"]) or []
    out = []
    for i, p in enumerate(t["periods"]):
        if not re.match(r"^[A-Za-z]{3} \d{4}$", p) or i >= len(fcf) or fcf[i] is None:
            continue
        out.append({"period": p, "fcf_cr": fcf[i], "cfo_cr": cfo[i] if i < len(cfo) else None})
    res = {"basis": basis, "rows": out[-years:]} if out else None
    sc._write_cache(ck, {"result": res})
    return res
