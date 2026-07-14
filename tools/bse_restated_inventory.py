"""
Restated prior-year Inventory — fixes a real accuracy gap in NSE-XBRL-only
Inventory Turnover: NSE's annual XBRL only tags the CURRENT year-end balance
sheet, never the prior-year comparative. So Average Inventory was built from
two DIFFERENT filings (this year's XBRL + last year's OWN separately-filed
XBRL) — which is wrong whenever the company restates prior-year comparatives
(e.g. after a merger/amalgamation). The company's OWN annual result PDF shows
the correct RESTATED comparative next to this year's figure; this module reads
that specific number.

Method: DETERMINISTIC position-based extraction (no LLM) — pdfplumber gives
each word's real (x, y) pixel position on the page; we cluster words into rows
by y-coordinate, so a jumbled linear-text-extraction problem becomes a real
table read. Two proven LLM attempts on this same filing (read-the-number,
then just-find-the-line-number) both returned wrong values — this coordinate
method is the one that reproduced the correct figure, verified against the
filing manually.

SAFETY: the extracted CURRENT-year figure must match the already-trusted XBRL
value (within a tiny tolerance) before the paired PRIOR-year figure is trusted
and used. If it doesn't match, return None — never a fabricated number.
"""

import re
import io
import time
import json

try:
    from tools import ssl_bootstrap  # noqa: F401
except Exception:
    pass

from tools.bse_scraper import _sess, _resolve_scrip_code, _read_cache, _write_cache


_MONTH_FULL = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
               "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
               "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December"}
_MONTH_NUM = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
              "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}


def _find_annual_result_pdf(symbol, name, to_date):
    """Find the BSE FULL-YEAR 'Financial Results For ... Year Ended <to_date>'
    announcement and return its PDF attachment URL, or None. `to_date` like
    '31-Mar-2024'. Excludes half-year/quarter filings — "Half Year Ended" and
    "Quarter Ended" both contain the substring "Year Ended", so a plain
    substring match on 'year ended' wrongly grabs half-year filings; this
    requires the FULL month name + day + year (e.g. 'March 31, 2024') and
    rejects any subject containing 'half'."""
    try:
        m = re.match(r"(\d{2})-(\w{3})-(\d{4})", to_date or "")
        if not m:
            return None
        day, mon, yr = m.groups()
        month_full = _MONTH_FULL.get(mon)
        if not month_full:
            return None
        code = _resolve_scrip_code(symbol, name)
        if not code:
            return None
        s = _sess()
        to = time.strftime("%Y%m%d")
        frm = f"{yr}{_MONTH_NUM[mon]}01"
        to_win = str(int(yr) + 1) + "0301"
        url = (f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
               f"pageno=1&strCat=Result&strPrevDate={frm}&strToDate={min(to_win, to)}"
               f"&strSearch=P&strscrip={code}&strType=C")
        rows = json.loads(s.get(url, timeout=25).text).get("Table", []) or []
        target = f"{month_full} {int(day)}, {yr}"  # e.g. "March 31, 2024"
        for r in rows:
            subj = r.get("NEWSSUB", "")
            if "half" in subj.lower():
                continue
            if target.lower() in subj.lower() and "year ended" in subj.lower():
                att = r.get("ATTACHMENTNAME")
                if att:
                    return f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{att}"
        return None
    except Exception as e:
        print(f"[bse_restated_inventory] filing lookup failed for {symbol}: {e}")
        return None


def _row_tokens_by_position(page):
    """Cluster a PDF page's words into visual rows by y-position (not linear text
    order), so a two-column table reads correctly regardless of how the text
    stream jumbles labels vs numbers."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    rows = {}
    for w in words:
        key = round(w["top"] / 2)
        rows.setdefault(key, []).append(w)
    keys = sorted(rows.keys())
    return keys, {k: [w["text"] for w in sorted(rows[k], key=lambda w: w["x0"])] for k in keys}


def _merge_numbers(tokens):
    """Merge tokens into real numbers. Handles both a properly-formed decimal
    ('2,45,634.06') and this filing's split form (['24.547', '20'] -> 24547.20,
    where pdfplumber tokenized the thousands-group and the 2-digit paise part
    as separate words)."""
    nums, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r"^-?[\d,]+\.\d{2}$", t):
            nums.append(float(t.replace(",", "")))
            i += 1
            continue
        if re.match(r"^-?[\d.,]+$", t) and i + 1 < len(tokens) and re.match(r"^\d{2}$", tokens[i + 1]):
            intpart = re.sub(r"[.,]", "", t)
            try:
                nums.append(float(intpart + "." + tokens[i + 1]))
            except Exception:
                pass
            i += 2
            continue
        i += 1
    return nums


def _extract_prior_inventory(pdf_bytes, current_value_cr):
    """Find the Consolidated Balance Sheet's Inventories row and return the prior
    year's ₹ crore value, ONLY if the same row's current-year value matches
    `current_value_cr` (the already-trusted XBRL figure) within tolerance.
    Returns (value_or_None, reason_or_None)."""
    try:
        import pdfplumber
    except Exception as e:
        return None, f"pdfplumber unavailable: {e}"
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Consolidated Balance Sheet" not in text or "Inventories" not in text:
                continue
            keys, rows = _row_tokens_by_position(page)
            inv_idx = None
            for i, k in enumerate(keys):
                if "Inventories" in " ".join(rows[k]):
                    inv_idx = i
                    break
            if inv_idx is None:
                continue
            combined = []
            for j in (inv_idx - 1, inv_idx, inv_idx + 1):
                if 0 <= j < len(keys):
                    combined += rows[keys[j]]
            vals = [v for v in _merge_numbers(combined) if v > 0]
            if len(vals) < 2:
                return None, "Could not locate two Inventory values near the label."
            for a, b in zip(vals, vals[1:]):
                if abs(a - current_value_cr) < 1.0:
                    return b, None
                if abs(b - current_value_cr) < 1.0:
                    return a, None
            return None, f"Extracted values {vals} didn't match the trusted current-year figure {current_value_cr} — rejected."
        return None, "Consolidated Balance Sheet page not found in the filing."
    except Exception as e:
        return None, f"PDF parse error: {e}"


def fetch_restated_prior_inventory(symbol, name, to_date, current_value_cr):
    """
    Public entry point. Returns {'value_cr': float, 'source_url': str} on a
    verified match, or {'value_cr': None, 'reason': str} otherwise. Cached 30
    days (annual filings don't change). Never raises.
    """
    sym = symbol.strip().upper().replace(".NS", "")
    ckey = f"restated_inv_{sym}_{to_date}"
    cached = _read_cache(ckey)
    if cached is not None:
        return cached

    out = {"value_cr": None, "reason": "Matching BSE annual filing not found."}
    try:
        pdf_url = _find_annual_result_pdf(sym, name, to_date)
        if not pdf_url:
            _write_cache(ckey, out)
            return out
        content = _sess().get(pdf_url, timeout=60).content
        if len(content) < 5000:
            out["reason"] = "Filing download failed or too small."
            _write_cache(ckey, out)
            return out
        value, reason = _extract_prior_inventory(content, current_value_cr)
        if value is None:
            out = {"value_cr": None, "reason": reason, "source_url": pdf_url}
        else:
            out = {"value_cr": round(value, 2), "source_url": pdf_url}
        _write_cache(ckey, out)
        return out
    except Exception as e:
        out = {"value_cr": None, "reason": f"error: {e}"}
        _write_cache(ckey, out)
        return out
