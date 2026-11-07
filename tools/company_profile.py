"""Company profile for the stock page's About section: the descriptive paragraphs, headquarters, year of incorporation,
MD / CEO, website, and a link to the latest Annual Report.

Sources, in order:
  * NSE Market Lens public API (the exchange's own company-profile record) - description, headquarters, founded year,
    MD / CEO, website. Cached on disk for a week.
  * Yahoo Finance profile (our price provider) - fallback for any field NSE does not return (or when NSE is unreachable).
  * BSE / NSE Annual Report filing list - the latest Annual Report PDF link.
A field no source provides is None - never a placeholder."""
from __future__ import annotations

import html
import json
import os
import re
import time

import requests

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "profile")
_PROFILE_TTL = 7 * 86400
_AR_TTL = 86400
_LEADERLESS_TTL = 6 * 3600     # a profile saved without an MD / CEO is looked up again after this long, not a week
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://marketlens.nseindia.com/", "Accept": "application/json"}


def _cache_get(key: str, ttl: float):
    try:
        p = os.path.join(_CACHE_DIR, key + ".json")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _cache_put(key: str, value) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(os.path.join(_CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
    except Exception:
        pass


def _paragraphs(raw: str | None) -> list[str]:
    """NSE's description is small HTML (<br/><br/> between paragraphs, an <a> for the e-mail): plain-text paragraphs."""
    if not raw:
        return []
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    out = []
    for block in re.split(r"\n\s*\n|\n{2,}", text.replace("\r", "")):
        block = re.sub(r"[ \t]+", " ", block.replace("\n", " ")).strip()
        if block:
            out.append(block)
    return out


def _from_nse(sym: str) -> dict | None:
    try:
        r = requests.get(f"https://marketlens.nseindia.com/api/stocks/{sym}", headers=_UA, timeout=20)
        d = (r.json() or {}).get("data") if r.status_code == 200 else None
    except Exception:
        return None
    if not d:
        return None
    founded = d.get("foundedYear")
    return {
        "paragraphs": _paragraphs(d.get("description")),
        "headquarters": (d.get("headquarters") or None),
        "incorporation_year": int(founded) if isinstance(founded, (int, float)) and founded else None,
        "leader": ({"name": d["ceoName"], "title": "MD / CEO"} if d.get("ceoName") else None),
        "website": (d.get("website") or None),
        "source": "nse",
    }


_YEAR_RE = re.compile(r"\b(?:incorporated|founded|established|formed)\b[^.]{0,80}?\b(1[89]\d{2}|20[0-2]\d)\b", re.I)


def _year_from_text(paragraphs) -> int | None:
    """The year a description says the company was incorporated / founded ("incorporated in the year 2013", "founded in
    1946"), for companies whose record has no founded-year field. The first such statement wins; None when there is none."""
    now = time.gmtime().tm_year
    for para in paragraphs or []:
        m = _YEAR_RE.search(para or "")
        if m and 1800 <= int(m.group(1)) <= now:
            return int(m.group(1))
    return None


def _clean_name(raw: str) -> str:
    nm = re.sub(r"^(?:(?:Mr|Ms|Mrs|Miss|Dr|Prof|Shri|Smt|Sri|CA|CS)\.?\s+)+", "", raw or "", flags=re.I)
    nm = re.split(r"\s+(?:B\.|M\.|Ph\.?D\b|CA\b|ACA\b|A\.C\.A\.?|MBA\b|BBA\b|BE\b|BTech\b|MTech\b|BCom\b|LLB\b|LLM\b|PGDM\b|FCA\b|CMA\b)", nm)[0]   # drop trailing degrees
    nm = nm.split(",")[0]                                                                               # "Name BBA, PGDM"
    return re.sub(r"\s+", " ", nm).strip()


def _leader_from_officers(officers) -> dict | None:
    """The company's chief executive from a list of {name, title}: an officer titled CEO / Chief Executive Officer /
    Managing Director / MD; a title carrying both ranks wins. A subsidiary or brand head ("Chief Executive Officer of
    Arrow") is not the company's own head and is skipped."""
    best, best_score = None, 0
    for o in officers or []:
        title = o.get("title") or ""
        name = _clean_name(o.get("name") or "")
        if not name or re.search(r"\b(?:deputy|assistant|associate|vice)\b", title, re.I):
            continue
        # a rank counts only when it is not "... of <a unit>": "CEO, CEO of Zinc Business & Executive Director" is the
        # company's CEO, "Chief Executive Officer of Arrow" is a brand head
        ceo = bool(re.search(r"\b(?:ceo|chief executive officer)\b(?!\s+of\b)", title, re.I))
        md = bool(re.search(r"\b(?:managing director|md)\b(?!\s+of\b)", title, re.I))
        score = 3 if ceo and md else 2 if ceo or md else 0
        if score > best_score:
            best, best_score = {"name": name, "title": "MD / CEO"}, score
    return best


def _yahoo_info(symbol: str) -> dict:
    """Yahoo's profile for the NSE listing (tried twice), then for the BSE listing."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    for suffix in (".NS", ".NS", ".BO"):
        try:
            info = yf.Ticker(f"{symbol}{suffix}").info or {}
        except Exception:
            info = {}
        if info.get("companyOfficers") or info.get("longBusinessSummary"):
            return info
        time.sleep(0.5)
    return {}


def _from_yahoo(sym: str) -> dict | None:
    info = _yahoo_info(sym)
    if not info:
        return None
    hq = ", ".join(x for x in (info.get("city"), info.get("state")) if x) or None
    leader = _leader_from_officers(info.get("companyOfficers"))
    site = info.get("website")
    return {
        "paragraphs": _paragraphs(info.get("longBusinessSummary")),
        "headquarters": hq,
        "incorporation_year": None,
        "leader": leader,
        "website": re.sub(r"^https?://", "", site).rstrip("/") if site else None,
        "source": "yahoo",
    }


def latest_annual_report(symbol: str, name: str | None) -> dict | None:
    """{year, url} of the newest Annual Report filing (BSE first, NSE as fallback), or None."""
    key = f"ar_{symbol}"
    hit = _cache_get(key, _AR_TTL)
    if hit is not None:
        return hit or None
    out = None
    try:
        from tools.annual_report_financials import _resolve_scrip_code, _sess
        code = _resolve_scrip_code(symbol, name)
        if code:
            r = _sess().get(f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}", timeout=25)
            rows = [x for x in (json.loads(r.text).get("Table") or []) if str(x.get("Year", "")).isdigit() and x.get("PDFDownload")]
            if rows:
                best = max(rows, key=lambda x: int(x["Year"]))
                out = {"year": int(best["Year"]), "url": best["PDFDownload"], "source": "bse"}
    except Exception as e:
        print(f"[company_profile] BSE annual report lookup failed for {symbol}: {e}")
    if out is None:
        try:
            from tools.nse_annual_reports import nse_annual_reports
            links = nse_annual_reports(symbol)
            if links:
                y = max(links)
                out = {"year": y, "url": links[y], "source": "nse"}
        except Exception as e:
            print(f"[company_profile] NSE annual report lookup failed for {symbol}: {e}")
    _cache_put(key, out or {})
    return out


def get_profile(symbol: str, name: str | None = None) -> dict:
    sym = symbol.strip().upper()
    base = _cache_get(f"p_{sym}", _PROFILE_TTL)
    if base is not None and not base.get("leader") and _cache_get(f"p_{sym}", _LEADERLESS_TTL) is None:
        base = None            # saved without an MD / CEO and old enough to try again
    if base is not None and not base.get("incorporation_year"):
        base = {**base, "incorporation_year": _year_from_text(base.get("paragraphs"))}     # no network needed
    if base is None:
        nse = _from_nse(sym)
        yh = None
        # Yahoo is read for every company: its officer list carries each person's title, so the MD / CEO it names is
        # backed by evidence, whereas NSE's bare "ceoName" is sometimes another director (a Deputy MD).
        yh = _from_yahoo(sym)
        base = {"paragraphs": [], "headquarters": None, "incorporation_year": None, "leader": None, "website": None, "source": None}
        for src in (nse, yh):  # NSE wins; Yahoo only fills what is still missing
            if not src:
                continue
            for k in ("paragraphs", "headquarters", "incorporation_year", "leader", "website"):
                if not base[k] and src.get(k):
                    base[k] = src[k]
        if yh and yh.get("leader"):
            base["leader"] = yh["leader"]
        if not base["incorporation_year"]:
            base["incorporation_year"] = _year_from_text(base["paragraphs"])
        if any(base[k] for k in ("paragraphs", "headquarters", "incorporation_year", "leader", "website")):
            base["source"] = (nse or {}).get("source") if nse else (yh or {}).get("source")
            _cache_put(f"p_{sym}", base)
    return {**base, "annual_report": latest_annual_report(sym, name)}
