"""Free cash flow by financial year, read from the 'Free Cash Flow' row of Screener.in's cash-flow table (Screener defines it as
cash from operating activity less the fixed assets purchased). A company whose table has no such row (some lenders, for example)
returns None: it is reported as unavailable, never as zero or computed from guesses.

Why a read can fail, and what is done about it: Screener answers HTTP 429 when it is asked too often (shared with every other part of the
app, see tools/screener_scraper.note_429), and then every request is paused for minutes. So (1) the figures are yearly and are kept for a
week; (2) every full Screener read of a company (stock page, background builds) saves its FCF as a by-product, with no extra request;
(3) when a live read fails the last saved copy (up to 400 days old) is served; (4) only when there is nothing saved is the answer
"could not be read right now", which the page shows as such and retries, instead of "unavailable for this company"; (5) nothing waits for
a paused Screener: the old code retried for 15 seconds and the page's request timed out."""
from __future__ import annotations

import re
import time

from . import screener_scraper as sc

TTL = 7 * 86400              # figures change once a year
STALE = 400 * 86400          # a saved copy this old still beats "could not be read"


def _page(url: str) -> str | None:
    """One quick attempt, and a couple of short retries for a slow answer; none while Screener requests are paused after a 429."""
    for attempt in range(3):
        if time.time() < sc._DOWN_UNTIL:
            return None
        html = sc._get(url)
        if html:
            return html
        if time.time() < sc._DOWN_UNTIL:       # the failed request was a 429: it paused everything, do not ask again
            return None
        time.sleep(0.8 * (attempt + 1))
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


def _result(t: dict, basis: str, years: int = 5) -> dict | None:
    """{'basis', 'rows': [...]} from a parsed cash-flow table, None when it has no Free Cash Flow row (or no usable year)."""
    fcf = next((v for k, v in t["rows"].items() if k.startswith("free cash flow")), None)
    if not fcf:
        return None
    cfo = sc._row_pick(t["rows"], ["cash from operating activity", "cash from operating activities"]) or []
    out = []
    for i, p in enumerate(t["periods"]):
        if not re.match(r"^[A-Za-z]{3} \d{4}$", p) or i >= len(fcf) or fcf[i] is None:
            continue
        out.append({"period": p, "fcf_cr": fcf[i], "cfo_cr": cfo[i] if i < len(cfo) else None})
    return {"basis": basis, "rows": out[-years:]} if out else None


def store_from_html(sym: str, html: str, basis: str) -> None:
    """Save the FCF of a company page that was just read for other reasons (tools/screener_scraper financials read): no extra request."""
    try:
        t = sc._parse_data_table(html, "cash-flow")
        if t["periods"] and t["rows"]:
            sc._write_cache(f"fcf1_{sym}", {"result": _result(t, basis)})
    except Exception:
        pass


def _yahoo_fcf(sym: str, years: int = 5) -> dict | None:
    """Annual free cash flow from Yahoo Finance's cash-flow statement ('Free Cash Flow', crore), a second source for when Screener cannot be
    read. Used only when Yahoo reports the statement in rupees (Infosys, for one, is reported there in US dollars, and no conversion is
    guessed); None otherwise. Saved a week, separately from Screener's copy so a later Screener read still takes precedence."""
    ck = f"fcf1y_{sym}"
    hit = sc._read_cache(ck, TTL)
    if hit is not None:
        return hit.get("result")
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import yfinance as yf
        from . import bse_universe
        from .live_chart_yf import _to_symbol
        bse_universe.prime(sym)
        t = yf.Ticker(_to_symbol(sym))
        if (t.info or {}).get("financialCurrency") != "INR":
            sc._write_cache(ck, {"result": None})
            return None
        cf = t.cashflow
        if cf is None or cf.empty or "Free Cash Flow" not in cf.index:
            sc._write_cache(ck, {"result": None})
            return None
        isnum = lambda v: isinstance(v, (int, float)) and v == v
        rows = []
        for col in sorted(cf.columns):
            v = cf.at["Free Cash Flow", col]
            if not isnum(v):
                continue
            cfo = cf.at["Operating Cash Flow", col] if "Operating Cash Flow" in cf.index else None
            rows.append({"period": col.strftime("%b %Y"), "fcf_cr": round(float(v) / 1e7, 2),
                         "cfo_cr": round(float(cfo) / 1e7, 2) if isnum(cfo) else None})
        res = {"basis": "yahoo", "rows": rows[-years:]} if rows else None
        sc._write_cache(ck, {"result": res})
        return res
    except Exception:
        return None


def free_cash_flow_status(symbol: str, years: int = 5) -> tuple[dict | None, str]:
    """(result, status): status "ok" (result has rows), "no_row" (the page was read and has no FCF figures: remembered) or "unreadable"
    (Screener could not be read and nothing is saved: not remembered, so the next view tries again)."""
    sym = symbol.strip().upper().replace(".NS", "")
    ck = f"fcf1_{sym}"
    hit = sc._read_cache(ck, TTL)
    if hit is not None:
        res = hit.get("result")
        return res, ("ok" if res else "no_row")
    got = _table(sym)
    if got:
        t, basis = got
        res = _result(t, basis, years)
        sc._write_cache(ck, {"result": res})
        return res, ("ok" if res else "no_row")
    old = sc._read_cache(ck, STALE)               # the last saved copy, however old (within 400 days), rather than nothing
    if old is not None:
        res = old.get("result")
        return res, ("ok" if res else "no_row")
    alt = _yahoo_fcf(sym, years)                  # Screener cannot be read and nothing is saved: Yahoo's statement, when it is in rupees
    if alt:
        return alt, "ok"
    return None, "unreadable"


def free_cash_flow(symbol: str, years: int = 5) -> dict | None:
    """{'basis', 'rows': [{'period': 'Mar 2026', 'fcf_cr': .., 'cfo_cr': ..}]} newest last, or None (no FCF row, or not readable)."""
    return free_cash_flow_status(symbol, years)[0]


def warm(symbols: list[str], pace: float = 6.0) -> None:
    """Read and save the FCF of companies that have no fresh saved copy, one every `pace` seconds (Screener rate-limits this machine), waiting
    out any pause after a 429. Resumable: a company with a fresh copy is skipped."""
    done = 0
    for sym in symbols:
        if sc._read_cache(f"fcf1_{sym}", TTL) is not None:
            continue
        sc.wait_if_down()
        _res, status = free_cash_flow_status(sym)
        done += 1
        if done % 25 == 0:
            print(f"[fcf warm] {done} read, latest {sym}: {status}", flush=True)
        time.sleep(pace)
    print(f"[fcf warm] done, {done} read", flush=True)


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from patterns import scan
    rows = scan._load_all()
    nse = sorted((r for r in rows.values() if r.get("exchange") != "BSE"), key=lambda r: -(r.get("market_cap_cr") or 0))
    print(f"[fcf warm] {len(nse)} NSE companies, largest first", flush=True)
    warm([r["symbol"] for r in nse])
