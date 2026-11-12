"""Quarterly results, growth measures and the industry classification for every scanned stock, read from Screener.in.

One company page per stock (consolidated view first; Screener shows the standalone figures when a company has no consolidated
accounts). For each stock we keep the last 12 quarters of sales, operating profit, OPM, net profit and EPS, the latest 12 quarters of
FII / DII holding, annual EPS, ROE / ROCE, 5-year sales growth and Screener's four-level classification (sector > industry group >
industry > basic industry). From these `derive()` computes the measures the screener filters use.

Nothing is guessed: a figure the page does not show, or a growth whose base is zero or negative, is None - never 0 - and a stock with
None simply does not match a filter on it. The data lives in data/screens/quarterly.json (one record per symbol)."""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.environ.get("SCREENS_DATA_DIR", os.path.join(ROOT, "data", "screens"))
PATH = os.path.join(DIR, "quarterly.json")
STALE_SECONDS = 20 * 3600
MISSING_RETRY_SECONDS = 10 * 60
WORKERS = 2          # Screener timed out when we used four; two is polite enough
PAUSE = 0.35
QUARTERS = 12

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "started": 0.0, "failed": 0}
_mem: dict = {"mt": None, "data": {}}


# ------------------------------------------------------------------ storage
def load() -> dict:
    try:
        mt = os.path.getmtime(PATH)
    except OSError:
        return {}
    if _mem["mt"] == mt:
        return _mem["data"]
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return _mem["data"]
    _mem.update({"mt": mt, "data": data})
    return data


def _save(data: dict) -> None:
    os.makedirs(DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, PATH)


def status() -> dict:
    data = load()
    ok = sum(1 for r in data.values() if r.get("periods"))
    return {**_state, "stocks": len(data), "with_quarters": ok,
            "as_of": max((r.get("fetched", 0) for r in data.values()), default=None)}


# ------------------------------------------------------------------ parsing
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _classification(html: str) -> list[str | None]:
    """[sector, industry group, industry, basic industry] from the /market/INxx links of the peers header."""
    out: dict[int, str] = {}
    for href, text in re.findall(r'<a[^>]+href="/market/(IN[0-9]+(?:/[A-Z0-9]+)*)/?"[^>]*>([^<]+)</a>', html):
        code = href.split("/")[-1]
        level = {4: 1, 6: 2, 8: 3, 11: 4}.get(len(code) - 0)
        if level is None:
            level = {"IN08": 1}.get(code)
        if level:
            out.setdefault(level, _clean(text))
    return [out.get(i) for i in (1, 2, 3, 4)]


def _series(html: str, section: str) -> dict:
    from tools.screener_scraper import _parse_data_table
    return _parse_data_table(html, section)


def _growth_table(html: str, title: str) -> dict:
    m = re.search(rf"{title}.*?</table>", html, re.S)
    out = {}
    if m:
        for k, v in re.findall(r"<td[^>]*>\s*([0-9A-Za-z ]+):\s*</td>\s*<td[^>]*>\s*(-?[0-9.,]+)\s*%", m.group(0)):
            try:
                out[k.strip().lower()] = float(v.replace(",", ""))
            except ValueError:
                pass
    return out


def _holding(sh: dict, name: str) -> list:
    """A shareholding row (the label carries a '+' / '&nbsp;' suffix, so match by prefix)."""
    for label, vals in sh["rows"].items():
        if label.startswith(name):
            return vals[-QUARTERS:]
    return []


def parse(html: str) -> dict | None:
    """The compact record for one company page, or None when the page is not a company page."""
    from tools.screener_scraper import _parse_top_ratios
    q = _series(html, "quarters")
    if not q["periods"]:
        return None
    n = QUARTERS
    rows = q["rows"]

    def pick(*names):
        for name in names:
            for label, vals in rows.items():
                if label == name or label.startswith(name):
                    return vals[-n:]
        return None

    sh = _series(html, "shareholding")
    pl = _series(html, "profit-loss")
    annual_periods = [p for p in pl["periods"] if p and p.upper() != "TTM"]
    eps_a = None
    for label, vals in pl["rows"].items():
        if label.startswith("eps in rs"):
            eps_a = vals[: len(annual_periods)]
            break
    top = _parse_top_ratios(html)
    sales_g = _growth_table(html, "Compounded Sales Growth")
    return {
        "fetched": time.time(),
        "periods": q["periods"][-n:],
        "sales": pick("sales", "revenue"), "op": pick("operating profit"), "opm": pick("opm"), "np": pick("net profit"), "eps": pick("eps in rs"),
        "fii": _holding(sh, "fiis"), "dii": _holding(sh, "diis"), "sh_periods": sh["periods"][-n:],
        "annual_periods": annual_periods[-6:], "annual_eps": (eps_a or [])[-6:],
        "roe": top.get("roe"), "roce": top.get("roce"), "sales_cagr_5y": sales_g.get("5 years"),
        "cls": _classification(html),
    }


def _fetch(url: str) -> str | None:
    """The page text, retrying a few times (Screener sometimes answers slowly); None on 404 or after the retries."""
    import tools.screener_scraper as sc
    for attempt in range(4):
        try:
            s = sc._http.Session(impersonate="chrome") if sc._HAVE_CFFI else sc._http.Session()
            r = s.get(url, timeout=30)
            if r.status_code == 200 and len(r.text) > 2000:
                return r.text
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def fetch_one(sym: str) -> dict:
    from tools import bse_universe
    key = (bse_universe.info().get(sym) or {}).get("code") or sym        # Screener knows a BSE-only company by its BSE code
    # the consolidated page first; when it has no readable quarterly table (some companies' pages lack the period headings) the standalone page
    for url in (f"https://www.screener.in/company/{key}/consolidated/", f"https://www.screener.in/company/{key}/"):
        html = _fetch(url)
        rec = parse(html) if html else None
        if rec:
            rec["basis"] = "consolidated" if "consolidated" in url else "standalone"
            return rec
    return {"fetched": time.time(), "periods": None, "missing": True}


# ------------------------------------------------------------------ derived measures
def _pct(a, b):
    return (a / b - 1.0) * 100.0 if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b and b > 0 else None


def _at(v, i):
    try:
        return v[i] if v and len(v) >= -i else None
    except IndexError:
        return None


def _streak(v, rising=False, positive=False):
    """How many of the latest quarters in a row are positive / each above the quarter before (None values stop the count)."""
    if not v:
        return None
    k = 0
    for i in range(len(v) - 1, -1, -1):
        cur = v[i]
        if cur is None:
            break
        if positive:
            if cur > 0:
                k += 1
                continue
            break
        prev = v[i - 1] if i > 0 else None
        if prev is None:
            break
        if cur > prev:
            k += 1
            continue
        break
    return k


def derive(rec: dict | None, latest_period: str | None = None, pe=None, eps_growth=None) -> dict:
    """The filter measures for one stock (all None when there is no quarterly record)."""
    keys = ("eps_qoq", "eps_yoy", "np_qoq", "np_yoy", "sales_qoq", "sales_yoy", "opm_qoq_pp", "opm_yoy_pp", "opm_ttm", "roe", "roce",
            "sales_cagr_5y", "peg", "np_pos_streak", "eps_incr_streak", "np_incr_streak", "sales_incr_streak", "opm_incr_streak",
            "fii_qoq_pp", "last_quarter", "basic_industry", "industry", "industry_group", "sector_cls",
            "f_eps_last_gt_prev", "f_np_turnaround", "f_latest_quarter", "f_fii_up", "f_code33")
    out = {k: None for k in keys}
    if not rec or not rec.get("periods"):
        return out
    s, np_, eps, opm, op = rec.get("sales"), rec.get("np"), rec.get("eps"), rec.get("opm"), rec.get("op")
    out["eps_qoq"], out["eps_yoy"] = _pct(_at(eps, -1), _at(eps, -2)), _pct(_at(eps, -1), _at(eps, -5))
    out["np_qoq"], out["np_yoy"] = _pct(_at(np_, -1), _at(np_, -2)), _pct(_at(np_, -1), _at(np_, -5))
    out["sales_qoq"], out["sales_yoy"] = _pct(_at(s, -1), _at(s, -2)), _pct(_at(s, -1), _at(s, -5))
    for key, back in (("opm_qoq_pp", -2), ("opm_yoy_pp", -5)):
        a, b = _at(opm, -1), _at(opm, back)
        out[key] = a - b if a is not None and b is not None else None
    if op and s and len(op) >= 4 and len(s) >= 4 and all(x is not None for x in op[-4:] + s[-4:]) and sum(s[-4:]) > 0:
        out["opm_ttm"] = sum(op[-4:]) / sum(s[-4:]) * 100.0
    out["roe"], out["roce"], out["sales_cagr_5y"] = rec.get("roe"), rec.get("roce"), rec.get("sales_cagr_5y")
    if isinstance(pe, (int, float)) and pe > 0 and isinstance(eps_growth, (int, float)) and eps_growth > 0:
        out["peg"] = pe / eps_growth
    out["np_pos_streak"] = _streak(np_, positive=True)
    out["eps_incr_streak"], out["np_incr_streak"] = _streak(eps, rising=True), _streak(np_, rising=True)
    out["sales_incr_streak"], out["opm_incr_streak"] = _streak(s, rising=True), _streak(opm, rising=True)
    fii = rec.get("fii") or []
    if len(fii) >= 2 and fii[-1] is not None and fii[-2] is not None:
        out["fii_qoq_pp"] = fii[-1] - fii[-2]
        out["f_fii_up"] = out["fii_qoq_pp"] > 0
    out["last_quarter"] = rec["periods"][-1]
    out["f_latest_quarter"] = bool(latest_period) and rec["periods"][-1] == latest_period
    cls = rec.get("cls") or [None] * 4
    # "industry" is Screener's finest level (basic industry, about 140 groups) so it is comparable to other platforms' industry lists;
    # the coarser levels are kept as industry_group (3rd level) and sector_cls (1st level)
    out["sector_cls"], out["industry_group"], out["basic_industry"] = cls[0], cls[2], cls[3]
    out["industry"] = cls[3] or cls[2]
    a = rec.get("annual_eps") or []
    out["f_eps_last_gt_prev"] = (a[-1] > a[-2]) if len(a) >= 2 and a[-1] is not None and a[-2] is not None else None
    if len(np_ or []) >= 2 and np_[-1] is not None and np_[-2] is not None:
        out["f_np_turnaround"] = np_[-2] < 0 < np_[-1]
    # "Code 33": year-on-year EPS growth, year-on-year sales growth and the margin each better in each of the last three quarters
    try:
        g_eps = [_pct(eps[i], eps[i - 4]) for i in (-3, -2, -1)]
        g_sal = [_pct(s[i], s[i - 4]) for i in (-3, -2, -1)]
        m3 = [opm[i] for i in (-3, -2, -1)]
        if None not in g_eps and None not in g_sal and None not in m3:
            out["f_code33"] = g_eps[0] < g_eps[1] < g_eps[2] and g_sal[0] < g_sal[1] < g_sal[2] and m3[0] < m3[1] < m3[2]
    except (TypeError, IndexError):
        pass
    return out


def latest_quarter(data: dict) -> str | None:
    """The newest quarter that at least 3% of the stocks have reported (so one early filer does not define it)."""
    from collections import Counter
    c = Counter(r["periods"][-1] for r in data.values() if r.get("periods"))
    if not c:
        return None

    def key(p):
        try:
            return time.strptime(p, "%b %Y")
        except ValueError:
            return time.gmtime(0)

    need = max(5, int(0.03 * sum(c.values())))
    ok = [p for p, n in c.items() if sum(v for q, v in c.items() if key(q) >= key(p)) >= need]
    return max(ok, key=key) if ok else None


# ------------------------------------------------------------------ build
def _symbols() -> list[str]:
    from tools import bse_universe
    from tools.nse_sector_map import all_symbols_by_sector
    return sorted({s for syms in all_symbols_by_sector().values() for s in syms} | set(bse_universe.info()))


def due(rec: dict | None, now: float) -> bool:
    if not rec:
        return True
    age = now - rec.get("fetched", 0)
    return age > (MISSING_RETRY_SECONDS if rec.get("missing") else STALE_SECONDS)


def build(force: bool = False, symbols: list[str] | None = None) -> bool:
    """Read every due stock's page (about 10 minutes for 750 stocks). Returns False when a build is already running."""
    with _lock:
        if _state["running"]:
            return False
        _state.update({"running": True, "done": 0, "failed": 0, "started": time.time()})
    try:
        data = dict(load())
        now = time.time()
        todo = [s for s in (symbols or _symbols()) if force or due(data.get(s), now)]
        _state["total"] = len(todo)
        lock = threading.Lock()

        def one(sym):
            rec = fetch_one(sym)
            time.sleep(PAUSE)
            with lock:
                data[sym] = rec
                _state["done"] += 1
                _state["failed"] += 1 if rec.get("missing") else 0
                if _state["done"] % 25 == 0:
                    _save(data)

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(one, todo))
        _save(data)
    finally:
        with _lock:
            _state["running"] = False
    return True


def ensure_fresh() -> None:
    """Start a background read when the data is missing or old (never blocks the caller)."""
    data = load()
    if _state["running"]:
        return
    now = time.time()
    if data and max((r.get("fetched", 0) for r in data.values()), default=0) > now - STALE_SECONDS:
        return
    threading.Thread(target=build, daemon=True).start()


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    t = time.time()
    build(force="--force" in sys.argv)
    print(f"done in {time.time() - t:.0f}s", status())
