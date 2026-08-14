"""
Generic, STRUCTURAL Annual Report table extraction — reads a table by its
actual row/column layout (via pdfplumber) instead of matching exact
wording in flowing text. This is the fix for the core limitation of the
keyword-window regex approach used elsewhere in this codebase (founder_
track_record_scoring.py, management_incentives_scoring.py): a regex tuned
against one company's phrasing ("Fixed Commission") won't fire for another
company that discloses the identical concept as "Basic Pay" or "Fixed
Component" in a table column header. Matching by COLUMN HEADER KEYWORD
inside a real detected table generalizes far better across the whole
~2409-company registry, since SEBI/Companies Act disclosure formats are
tables far more consistently than they're identically-worded prose.

Not a silver bullet: a scanned-image PDF with no extractable text, or a
company whose table genuinely omits the needed column, still won't
resolve. But it removes the single biggest source of registry-wide
false-negatives (exact-phrase mismatch on a real, present disclosure).
"""

import os
import re
import time

from tools.bse_scraper import _sess, CACHE_DIR as _BSE_CACHE_DIR

_PDF_BYTES_CACHE_DIR = os.path.join(os.path.dirname(_BSE_CACHE_DIR), "ar_pdfs")
_PDF_BYTES_TTL = 30 * 24 * 3600  # ARs don't change once filed - cache long


def _pdf_cache_path(symbol, fiscal_year):
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    return os.path.join(_PDF_BYTES_CACHE_DIR, f"{sym}_{fiscal_year}.pdf")


def download_ar_pdf_bytes(symbol, name, fiscal_year):
    """Downloads (or reads from a long-TTL disk cache) the raw Annual
    Report PDF bytes for one fiscal year. Shared cache so a company already
    visited by the fitz-based text-window extractors pays no extra
    download cost here. Returns bytes or None."""
    try:
        sym = symbol.strip().upper().replace(".NS", "")
        p = _pdf_cache_path(sym, fiscal_year)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) <= _PDF_BYTES_TTL:
            with open(p, "rb") as fh:
                return fh.read()

        from tools.annual_report_financials import _find_annual_report_pdf
        pdf_url = _find_annual_report_pdf(sym, name, fiscal_year)
        if not pdf_url:
            return None

        is_nse_url = "nseindia.com" in pdf_url
        content = None
        for _attempt in range(2):
            try:
                if is_nse_url:
                    from tools.nse_annual_reports import download_nse_pdf_bytes
                    content = download_nse_pdf_bytes(pdf_url)
                else:
                    content = _sess().get(pdf_url, timeout=90).content
                if content:
                    break
            except Exception as e:
                print(f"[ar_table_extractor] PDF download failed for {sym}: {e}")
        if not content or len(content) < 50000:
            return None

        try:
            os.makedirs(_PDF_BYTES_CACHE_DIR, exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(content)
        except Exception:
            pass
        return content
    except Exception as e:
        print(f"[ar_table_extractor] download_ar_pdf_bytes failed for {symbol}: {e}")
        return None


def _find_anchor_pages_fast(content, anchor_phrases_by_key, max_pages_per_key=3, score_by="phrase_count"):
    """Phase 1 (fast): scans every page's text with PyMuPDF (fitz) - the
    same library the rest of this codebase's text-window extractors
    already use, and dramatically faster than pdfplumber's own text
    extraction for a full-document scan (confirmed live: pdfplumber took
    ~0.2s/page, timing out well before finishing a 300+ page filing;
    fitz's page.get_text() is the established fast path here). Returns
    {key: [page_index, ...]}, capped per key by a score so phase 2 only
    opens a small, targeted set of pages with pdfplumber.

    `score_by`: "phrase_count" (default) ranks by how many times the
    anchor phrase itself repeats on the page - the right signal for a
    table where each ROW repeats a role/label phrase (e.g. "Non-Executive
    Director" once per director), where digit-density would instead favor
    an unrelated but numbers-heavy financial-statement page that merely
    mentions the phrase once in passing (confirmed real bug from live
    testing). "digit_density" (the previous behavior) is still available
    for anchors that genuinely ARE about a numbers-heavy disclosure table
    (e.g. a remuneration or appointment-date table)."""
    import fitz
    doc = fitz.open(stream=content, filetype="pdf")
    scored = {k: [] for k in anchor_phrases_by_key}
    for i, page in enumerate(doc):
        try:
            t = page.get_text()
        except Exception:
            continue
        if not t:
            continue
        tl = t.lower()
        for key, phrases in anchor_phrases_by_key.items():
            hit_count = sum(tl.count(p) for p in phrases)
            if hit_count == 0:
                continue
            score = hit_count if score_by == "phrase_count" else sum(c.isdigit() for c in t)
            scored[key].append((score, i))
    doc.close()
    out = {}
    for key, pages in scored.items():
        pages.sort(key=lambda sp: -sp[0])
        out[key] = [i for _, i in pages[:max_pages_per_key]]
    return out


def extract_tables_near_anchors(symbol, name, anchor_phrases_by_key, fiscal_year=None, max_tables_per_key=3, score_by="phrase_count"):
    """Downloads the AR PDF and, for each `key: [phrase, ...]` in
    `anchor_phrases_by_key`, finds the highest-scoring pages whose text
    contains one of the phrases (fast fitz scan) and extracts every REAL
    table on those pages (pdfplumber's layout-based table detection - not
    a regex on flowing text). Returns {key: [table, ...], 'fiscal_year':
    int} where each table is a list of rows, each row a list of cell
    strings (None cells normalized to ""). Keeps at most
    `max_tables_per_key` tables per key (highest row-count first, since a
    real disclosure table is rarely a 2-row scrap). Never raises; returns
    {} on any failure."""
    try:
        sym = symbol.strip().upper().replace(".NS", "")
        if fiscal_year is None:
            from tools.annual_report_financials import list_annual_report_years
            years = list_annual_report_years(sym, name)
            if not years:
                return {}
            fiscal_year = years[0]

        content = download_ar_pdf_bytes(sym, name, fiscal_year)
        if not content:
            return {}

        anchor_pages = _find_anchor_pages_fast(content, anchor_phrases_by_key, score_by=score_by)
        all_page_indices = sorted({i for pages in anchor_pages.values() for i in pages})
        if not all_page_indices:
            out = {k: [] for k in anchor_phrases_by_key}
            out["fiscal_year"] = fiscal_year
            return out

        import pdfplumber
        import io
        out = {k: [] for k in anchor_phrases_by_key}
        with pdfplumber.open(io.BytesIO(content), pages=[i + 1 for i in all_page_indices]) as pdf:
            # pdfplumber's `pages=` selector re-indexes pdf.pages to just
            # the requested ones, in the same order - zip back to the
            # original page index so we know which key(s) it satisfies.
            for orig_idx, page in zip(all_page_indices, pdf.pages):
                try:
                    tables = page.extract_tables()
                except Exception:
                    tables = []
                if not tables:
                    continue
                matched_keys = [key for key, pages in anchor_pages.items() if orig_idx in pages]
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    clean = [[(c or "").strip() for c in row] for row in table]
                    for key in matched_keys:
                        out[key].append(clean)

        for key in anchor_phrases_by_key:
            out[key].sort(key=lambda t: -len(t))
            out[key] = out[key][:max_tables_per_key]
        out["fiscal_year"] = fiscal_year
        return out
    except Exception as e:
        print(f"[ar_table_extractor] extract_tables_near_anchors failed for {symbol}: {e}")
        return {}


def find_column(header_row, keywords):
    """Index of the first header cell whose lowercased text contains any of
    `keywords`, or None. `header_row` is a list of cell strings."""
    for i, cell in enumerate(header_row):
        low = (cell or "").lower()
        if any(kw in low for kw in keywords):
            return i
    return None


_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_cell_number(cell):
    """Parses a table cell as a number (handles Indian-comma-grouping and
    a leading currency symbol/sign), or None if the cell has no number."""
    if not cell:
        return None
    m = _NUM_RE.search(cell.replace("₹", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None
