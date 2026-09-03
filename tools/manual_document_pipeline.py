"""
Manual Document Upload pipeline.

Lets a user upload a company's Annual Report PDF directly, as an
alternative to the automatic BSE/NSE fetch. Generic across every company
in the registry - no ticker-specific logic (CLAUDE.md rule).

Flow: upload -> parse -> the user searches for whatever metric they want
(e.g. "EBIT", "PAT", "Revenue") -> the document is searched for that term
and the value + page + evidence is returned, never fabricated (a term that
isn't found is reported as not_found, not zero). Each search is recorded
so a running list of everything looked up for this company can be shown
and expanded.

Key architectural decision: the uploaded Annual Report is parsed into the
SAME on-disk caches (cache/ar_pdfs/{SYMBOL}_{YEAR}.pdf,
cache/ar_text/{SYMBOL}_{YEAR}.json) that tools/ar_document_cache.py already
serves to every one of the ~60 ratio endpoints and every qualitative
sub-point in tools/qualitative_engine.py. companies.latest_ar_year /
latest_ar_url are updated to point at it, so once processed the existing
ratio/qualitative engines pick this document up completely unchanged - no
per-ratio or per-subpoint rewiring needed.
"""

import os
import re
import time

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOAD_DIR = os.path.join(_BASE_DIR, "uploads")

# Every physical file format the ingestion pipeline can actually extract
# readable text/facts from - kept as the SINGLE source of truth for
# extension enforcement (both save_upload/save_upload_auto and the
# per-field dedicated-format checks in analyse_documents defer to this set
# rather than re-declaring their own). The category a file is uploaded
# under (Annual Report, Financial XBRL, Shareholding Pattern, Corporate
# Governance, ...) is independent of its physical format - any of these
# extensions is accepted for any category. ZIP is deliberately NOT
# included: there is no ingestion path that safely extracts/parses
# archive contents, and blindly unzipping arbitrary uploads is itself a
# path-traversal/zip-bomb risk, not just a missing feature.
_ALLOWED_FORMATS = {"pdf", "xml", "xbrl", "xlsx", "xls", "csv", "docx", "pptx", "txt", "html", "htm"}

_UNIT_MULTIPLIERS = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
    "million": 1e6, "millions": 1e6, "mn": 1e6,
    "billion": 1e9, "billions": 1e9, "bn": 1e9,
    "thousand": 1e3, "thousands": 1e3,
}


# ---------------------------------------------------------------------------
# Document parsing: PDF -> normalized page-text list
# ---------------------------------------------------------------------------

def _extract_pdf_pages(content):
    import fitz
    from tools.annual_report_financials import _page_text
    doc = fitz.open(stream=content, filetype="pdf")
    pages = []
    try:
        for page in doc:
            try:
                t = _page_text(page)
            except Exception:
                t = ""
            t = re.sub(r"\s+", " ", t)
            t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
            pages.append(t)
    finally:
        doc.close()
    return pages



# ---------------------------------------------------------------------------
# XBRL/XML supporting-document extraction (e.g. Shareholding Pattern filing,
# Change-in-Management/Corporate Actions filing uploaded as .xml). Generic
# across every XBRL taxonomy - reads whatever facts the file actually
# contains and turns each into one readable "Label: value" line, using only
# the element's own local tag name and text content plus, where present, its
# context's xbrldi:explicitMember dimension (e.g. shareholder category).
# Never fabricates a fact that isn't in the file, and is entirely separate
# from tools/nse_xbrl.py's dedicated in-bse-shp promoter/pledge-% parser
# (which still exclusively feeds Sr 67/68 / C.1.1/C.2.1/C.2.2/C.2.4 via its
# own save_manual_shareholding/_shareholding_from_manual_upload path) - this
# extractor only feeds the qualitative anchor-phrase search path
# (get_supporting_document_pages / _fetch_ar_evidence_excerpts), so the two
# never compete or duplicate each other.
# ---------------------------------------------------------------------------

_XML_TAG_RE = re.compile(r"<([A-Za-z][\w.\-]*:)?([A-Za-z][\w.\-]*)([^>]*)>([^<]*)</\1?\2>")
_CONTEXT_REF_RE = re.compile(r'contextRef="([^"]+)"')
_CONTEXT_BLOCK_RE = re.compile(r'<[\w.\-]*:?context id="([^"]+)"[^>]*>(.*?)</[\w.\-]*:?context>', re.S | re.I)
_EXPLICIT_MEMBER_RE = re.compile(r'explicitMember[^>]*>\s*[\w.\-]*:?([A-Za-z][\w.\-]*?)(?:Member)?\s*<', re.I)
# Structural/bookkeeping tags never worth surfacing as a "fact" line.
_XML_SKIP_TAGS = {
    "context", "unit", "schemaref", "measure", "identifier", "period",
    "startdate", "enddate", "instant", "entity", "scenario", "explicitmember",
    "segment", "xbrl",
}


def _humanize_xbrl_tag(tag):
    """'TypeOfChange' -> 'Type Of Change'; 'NameOfDesignatedPerson' ->
    'Name Of Designated Person'. Generic camel-case splitter, not tied to
    any specific taxonomy or company."""
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", tag)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_xbrl_pages(content):
    """Parses an XBRL/XML filing into readable 'Label: value' lines - one
    per tagged fact with non-empty text content. Where a fact's context
    carries an xbrldi:explicitMember (e.g. a shareholder category dimension
    on a Shareholding Pattern filing), the member name is prefixed onto the
    label so a category-specific percentage/count reads as e.g.
    'Shareholding Of Promoter And Promoter Group - Shareholding As A
    Percentage Of Total Number Of Shares: 59.07'. Never interpolates or
    fabricates a value not literally present in the file. Returns a single-
    element list (one 'page') so callers can treat it like PDF pages."""
    try:
        text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
    except Exception:
        text = ""
    if not text.strip():
        return []

    # Map context id -> dimension member label (if any), so each fact line
    # can carry its shareholder-category/event context when present.
    context_member = {}
    for cid, body in _CONTEXT_BLOCK_RE.findall(text):
        m = _EXPLICIT_MEMBER_RE.search(body)
        if m:
            context_member[cid] = _humanize_xbrl_tag(m.group(1))

    lines = []
    seen = set()
    for prefix, tag, attrs, value in _XML_TAG_RE.findall(text):
        local = tag.strip()
        if not local or local.lower() in _XML_SKIP_TAGS:
            continue
        # Taxonomy dimension-member declaration tags (e.g. "...Domain") name
        # a context/dimension member id, not an actual disclosed fact value
        # - skip them so real facts aren't buried under hundreds of these.
        if local.endswith("Domain"):
            continue
        val = re.sub(r"\s+", " ", (value or "")).strip()
        if not val:
            continue
        label = _humanize_xbrl_tag(local)
        ctx_m = _CONTEXT_REF_RE.search(attrs or "")
        member = context_member.get(ctx_m.group(1)) if ctx_m else None
        line = f"{member} - {label}: {val}" if member else f"{label}: {val}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)

    if not lines:
        return []
    return ["\n".join(lines)]


def _extract_xlsx_pages(content):
    """Reads every sheet of an .xlsx/.xls workbook into one readable
    'page' of tab-separated rows per sheet (one list element per sheet),
    so it can be treated like PDF pages by every downstream consumer
    (search_document's window scan, the qualitative anchor-phrase search).
    Never fabricates a cell value; blank cells render as empty strings."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    pages = []
    for sheet in wb.worksheets:
        lines = [f"Sheet: {sheet.title}"]
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                lines.append("\t".join(cells))
        text = "\n".join(lines)
        if text.strip():
            pages.append(text)
    return pages


def _extract_csv_pages(content):
    """Decodes a .csv file into one readable 'page' of comma-preserved
    text - no pandas dtype inference (which could silently coerce/mangle
    a genuinely textual value), just the raw rows joined back together."""
    try:
        text = content.decode("utf-8-sig", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
    except Exception:
        text = ""
    return [text] if text.strip() else []


def _extract_docx_pages(content):
    """Reads a .docx file's paragraphs and table cells into a single
    'page' of text, mirroring the PDF/XBRL extractors' contract (list of
    page-text strings)."""
    import io
    import docx
    doc = docx.Document(io.BytesIO(content))
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text for c in row.cells]
            if any(c.strip() for c in cells):
                lines.append("\t".join(cells))
    text = "\n".join(lines)
    return [text] if text.strip() else []


def _extract_pptx_pages(content):
    """Reads a .pptx deck's text frames/table cells into one 'page' per
    slide, so a slide number is preserved as a search-result page just
    like a PDF page."""
    import io
    from pptx import Presentation
    prs = Presentation(io.BytesIO(content))
    pages = []
    for slide in prs.slides:
        lines = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text for c in row.cells]
                    if any(c.strip() for c in cells):
                        lines.append("\t".join(cells))
        text = "\n".join(lines)
        pages.append(text)
    return pages


def _extract_txt_pages(content):
    try:
        text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
    except Exception:
        text = ""
    return [text] if text.strip() else []


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def _extract_html_pages(content):
    """Strips tags/scripts/styles from an .html file into one 'page' of
    readable text - same lightweight, no-fabrication contract as the other
    extractors (no HTML rendering, just the visible text content)."""
    try:
        text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
    except Exception:
        text = ""
    text = _HTML_SCRIPT_STYLE_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    import html as _html
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return [text.strip()] if text.strip() else []


def parse_document(content, file_format):
    """Returns list of normalized page-text strings, or raises."""
    if file_format == "pdf":
        return _extract_pdf_pages(content)
    if file_format in ("xml", "xbrl"):
        return _extract_xbrl_pages(content)
    if file_format in ("xlsx", "xls"):
        return _extract_xlsx_pages(content)
    if file_format == "csv":
        return _extract_csv_pages(content)
    if file_format == "docx":
        return _extract_docx_pages(content)
    if file_format == "pptx":
        return _extract_pptx_pages(content)
    if file_format == "txt":
        return _extract_txt_pages(content)
    if file_format in ("html", "htm"):
        return _extract_html_pages(content)
    raise ValueError(f"Unsupported format: {file_format}")


# ---------------------------------------------------------------------------
# Unit normalization
# ---------------------------------------------------------------------------

_NUM_WITH_UNIT_RE = re.compile(
    r"[₹Rs\.\s]{0,4}\(?(-?[\d,]+\.?\d*)\)?\s*(crore|crores|cr|lakh|lakhs|lac|million|millions|mn|billion|billions|bn|thousand|thousands|%)?",
    re.I,
)


def normalize_value(raw_text):
    """Parses a raw matched value string into (numeric_value, unit_label)
    honoring Indian numbering (crore/lakh) vs million/billion, bracketed
    negatives, and percentages. Returns (None, None) if no confident parse
 - callers must treat that as not_found, never coerce to 0."""
    if not raw_text:
        return None, None
    m = _NUM_WITH_UNIT_RE.search(raw_text)
    if not m:
        return None, None
    num_str, unit = m.group(1), (m.group(2) or "").lower()
    is_bracketed_negative = "(" in raw_text and ")" in raw_text and not num_str.startswith("-")
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return None, None
    if is_bracketed_negative:
        value = -abs(value)
    if unit == "%":
        return value, "%"
    if unit in _UNIT_MULTIPLIERS:
        return value, unit
    return value, None


# ---------------------------------------------------------------------------
# Free-text search over the document (interactive: user types a metric name)
# ---------------------------------------------------------------------------

# Small alias map for the metric names users are most likely to type - 
# generic across all companies (CLAUDE.md), not ticker-specific. A query
# with no alias entry still gets searched, just on the literal term alone.
_METRIC_ALIASES = {
    "revenue": ["revenue from operations", "total income", "net sales"],
    "ebitda": ["earnings before interest, tax, depreciation"],
    "ebit": ["operating profit", "profit before interest and tax"],
    "pat": ["profit after tax", "net profit"],
    "pbt": ["profit before tax"],
    "net profit margin": ["net profit ratio", "npm"],
    "roe": ["return on equity", "return on net worth"],
    "roce": ["return on capital employed"],
    "current ratio": ["current ratio"],
    "debt to equity": ["debt equity ratio", "debt-equity ratio"],
    "interest coverage ratio": ["interest coverage ratio", "interest service coverage"],
}


def _find_candidate(pages, label, aliases=None):
    """Searches page text for `label` (or any alias) followed by a number
    on the same line/window. Returns
    {value, unit, page, evidence, confidence} or None if no confident hit."""
    needles = [label.lower()] + [a.lower() for a in (aliases or [])]
    best = None
    for page_idx, text in enumerate(pages):
        low = text.lower()
        for needle in needles:
            pos = low.find(needle)
            if pos == -1:
                continue
            window = text[pos:pos + 160]
            value, unit = normalize_value(window[len(needle):])
            if value is None:
                continue
            confidence = 0.92 if needle == label.lower() else 0.8
            candidate = {
                "value": value, "unit": unit, "page": page_idx + 1,
                "evidence": window.strip(), "confidence": confidence,
            }
            if best is None or candidate["confidence"] > best["confidence"]:
                best = candidate
    return best


def search_document(symbol, query):
    """Searches the latest processed Annual Report for `query` (e.g.
    "EBIT", "PAT", "Revenue") and records the result. Returns the
    extracted_values-shaped row, or {"error": ...} if there's no
    processed document yet for this company. Never fabricates: no
    confident match -> status='not_found', value=None."""
    from tools.supabase_client import get_client
    sb = get_client()
    sym = symbol.strip().upper().replace(".NS", "")
    docs = (sb.table("uploaded_documents").select("*").eq("symbol", sym)
            .eq("status", "processed").order("uploaded_at", desc=True).limit(1).execute().data)
    if not docs:
        return {"error": "No processed Annual Report for this company yet. Upload and analyze one first."}
    doc = docs[0]

    from tools.ar_document_cache import get_ar_pages
    res = get_ar_pages(sym, sym, fiscal_year=doc.get("fiscal_year"))
    if "error" in res:
        return {"error": res["error"]}
    pages = res["pages"]

    q = query.strip()
    aliases = _METRIC_ALIASES.get(q.lower())
    hit = _find_candidate(pages, q, aliases)
    if hit is None:
        row = {
            "document_id": doc["id"], "symbol": sym, "requirement_type": "fundamental",
            "requirement_key": q.lower(), "requirement_label": q, "value": None, "unit": None,
            "page": None, "evidence_text": None, "confidence": None, "status": "not_found",
        }
    else:
        status = "verified" if hit["confidence"] >= 0.9 else "needs_validation"
        row = {
            "document_id": doc["id"], "symbol": sym, "requirement_type": "fundamental",
            "requirement_key": q.lower(), "requirement_label": q, "value": str(hit["value"]),
            "unit": hit["unit"], "page": hit["page"], "evidence_text": hit["evidence"],
            "confidence": hit["confidence"], "status": status,
        }
    inserted = sb.table("extracted_values").insert(row).execute()
    return inserted.data[0]


def get_search_history(symbol):
    """Every value the user has looked up for this company so far, most
    recent first - powers the sidebar list of searched metrics."""
    from tools.supabase_client import get_client
    sb = get_client()
    sym = symbol.strip().upper().replace(".NS", "")
    docs = (sb.table("uploaded_documents").select("id").eq("symbol", sym)
            .eq("status", "processed").order("uploaded_at", desc=True).limit(1).execute().data)
    if not docs:
        return []
    return (sb.table("extracted_values").select("*").eq("document_id", docs[0]["id"])
            .order("created_at", desc=True).execute().data)


# ---------------------------------------------------------------------------
# Company detection - the Annual Report already says who it's for, so the
# user never has to type a company name. Generic across every company
# (CLAUDE.md): no hardcoded names, just pattern matching + a fuzzy lookup
# against the existing companies registry.
# ---------------------------------------------------------------------------

# Up to 4 title-case-ish words immediately before "Limited"/"Ltd" - capped
# short so it can't swallow an unrelated sentence/heading that happens to
# precede the word "Limited" further down the page.
_COMPANY_NAME_RE = re.compile(r"\b((?:[A-Z][A-Za-z&.\-']*\s+){1,4}(?:Limited|Ltd\.?))\b")
_NOISE_WORDS = {"limited", "ltd", "india", "the", "of", "and", "company", "co", "pvt", "private"}
# Section-heading words that indicate the match spilled into a caption
# rather than an actual company name - discard any candidate containing one.
_HEADING_NOISE = {
    "board", "directors", "report", "office", "registered", "annual", "statutory",
    "management", "discussion", "analysis", "notice", "agm", "cin", "statement",
    "auditors", "committee", "corporate", "governance", "financial", "balance",
    "profit", "loss", "cash", "flow", "notes", "accounts", "meeting", "shareholders",
}
_NAME_WORD = r"[A-Z][A-Za-z&.\-']*"

# Structural anchors, most authoritative first - real places an Indian
# Annual Report states its OWN legal name as a matter of statutory form,
# not narrative prose a marketing cover page can dress up however it
# likes. Each entry is (pattern, description) - patterns capture group 1
# as the raw name (still cleaned/validated the same way as every other
# candidate below).
#
# 1) The running page header/footer ("PRIME FRESH LIMITED | ANNUAL
#    REPORT 2025-26") - printed on very nearly EVERY page of the report,
#    confirmed real: 219/251 pages on Prime Fresh Limited's own filing,
#    unanimous (zero competing values). This is the single most reliable
#    signal there is, because a filer's own PDF-generation template
#    stamps it identically on every page - a decorative cover headline
#    is inherently a one-off, it cannot compete with a per-page running
#    head once the WHOLE document (not just the first few pages) is
#    scanned for it.
_HEADER_FOOTER_RE = re.compile(r"([A-Z][A-Z0-9 &.,'\-]{3,60}?)\s*\|\s*ANNUAL REPORT\s*\d{4}")
# 2) The Board resolution/Notice sign-off immediately followed by the
#    Registered Office block - "For, Prime Fresh Limited\nRegistered
#    Office: ...". A standard Companies Act 2013 formality, not
#    marketing copy.
_SIGNOFF_OFFICE_RE = re.compile(
    rf"\bFor,?\s+((?:{_NAME_WORD}\s+){{1,6}}(?:Limited|Ltd\.?))\s*\n?\s*Registered Office", re.I,
)
# 3) "To the Members of <Name>" - the Auditor's Report/Directors' Report's
#    own standard opening address.
_TO_MEMBERS_RE = re.compile(rf"To the Members of\s+((?:{_NAME_WORD}\s+){{1,6}}(?:Limited|Ltd\.?))", re.I)
# 4) "Annual General Meeting of the Members of <Name>" - the Notice of
#    AGM's own standard convening language (only useful when the filer
#    names itself here rather than saying "of the company").
_AGM_OF_RE = re.compile(
    rf"Annual General Meeting of (?:the )?(?:Members|Shareholders) of\s+((?:{_NAME_WORD}\s+){{1,6}}(?:Limited|Ltd\.?))", re.I,
)
# 5) A bare "Name of the Company: <Name>" field, e.g. in a secretarial
#    audit report or MGT-7 extract.
_NAME_FIELD_RE = re.compile(rf"Name of (?:the )?Company\s*[:\-]?\s*((?:{_NAME_WORD}\s+){{1,6}}(?:Limited|Ltd\.?))", re.I)

_NAME_ANCHORS = [_SIGNOFF_OFFICE_RE, _TO_MEMBERS_RE, _AGM_OF_RE, _NAME_FIELD_RE]


def _clean_name_candidate(raw):
    name = re.sub(r"\s+", " ", raw).strip(" .,-")
    if len(name) < 6:
        return None
    if any(w in _HEADING_NOISE for w in name.lower().split()):
        return None
    return name


def _title_case_name(name):
    """The running-header anchor is printed in ALL CAPS - render it in
    the same title case every other source (search, registry) already
    uses, lower-casing small connector words except the first."""
    small = {"and", "of", "the", "for", "in", "on"}
    words = name.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        out.append(lw if (lw in small and i > 0) else (lw[:1].upper() + lw[1:].lower() if lw.isalpha() else w))
    return " ".join(out)


def detect_company_name(pages):
    """Finds the company's own real legal name by reading the SAME
    structural locations a human reader would trust - a running page
    header/footer, the Notice/Board sign-off, "To the Members of..." -
    rather than guessing from whichever "<Words> Limited" phrase happens
    to appear most often in the first few pages. A stylized cover-page
    marketing headline ("A Landmark Achievement - Prime Fresh Limited's
    BSE Main Board Migration") can and did win a raw frequency count
    (confirmed real: minted the wrong name/symbol - "Landmark Achievement
    Prime Fresh Limited" / LANDMARKACHIEVE - at first upload for Prime
    Fresh Limited), because the naive heuristic has no way to tell a
    one-off decorative phrase apart from the real name. None of these
    anchors are ticker-specific - they are standard Companies Act 2013 /
    SEBI LODR disclosure conventions every Indian filer's Annual Report
    follows in some form.

    Falls back to the old frequency heuristic (now scanning a wider
    front-matter window, and preferring a shorter name that's an exact
    trailing subset of a longer one) only when none of the structural
    anchors match anything - never fabricates a name from nothing."""
    full_text = " ".join(pages)

    # Priority 1: running header/footer, scanned across the WHOLE
    # document - the most repeated, most reliable signal available.
    header_counts = {}
    for m in _HEADER_FOOTER_RE.finditer(full_text):
        cleaned = _clean_name_candidate(m.group(1))
        if cleaned:
            header_counts[cleaned] = header_counts.get(cleaned, 0) + 1
    if header_counts:
        winner, wins = max(header_counts.items(), key=lambda kv: kv[1])
        total = sum(header_counts.values())
        # Require a real majority, not just a plurality - a report that
        # switches between standalone/consolidated running heads (rare)
        # should fall through to the other anchors rather than pick
        # arbitrarily.
        if wins / total >= 0.6:
            return _title_case_name(winner)

    # Priority 2-5: statutory structural anchors, front-matter + notice/
    # signature sections (bounded to the first 60 pages - these sections
    # are never buried deeper than that in practice, and bounding avoids
    # picking up an unrelated counterparty's "For, <Other> Limited" sign-
    # off inside a much later Related Party Transactions note).
    front_text = " ".join(pages[:60])
    for pattern in _NAME_ANCHORS:
        m = pattern.search(front_text)
        if m:
            cleaned = _clean_name_candidate(m.group(1))
            if cleaned:
                return cleaned

    # Fallback: frequency heuristic over a widened front-matter window,
    # preferring a shorter candidate that's an exact trailing subset of a
    # longer one (a decorated headline's own trailing words ARE the real
    # name, prefixed with marketing copy).
    counts = {}
    for m in _COMPANY_NAME_RE.finditer(front_text):
        cleaned = _clean_name_candidate(m.group(1))
        if cleaned:
            counts[cleaned] = counts.get(cleaned, 0) + 1
    if not counts:
        return None

    candidates = sorted(counts, key=lambda n: (-counts[n], len(n)))
    for shorter in sorted(counts, key=len):
        if shorter == candidates[0]:
            continue
        if candidates[0].lower().endswith(shorter.lower()) and counts[shorter] >= max(2, counts[candidates[0]] // 3):
            return shorter
    return candidates[0]


def _normalize_name(name):
    n = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    tokens = [t for t in n.split() if t not in _NOISE_WORDS]
    return " ".join(tokens)


def resolve_symbol_by_name(detected_name):
    """Fuzzy token-overlap match of `detected_name` against companies.name.
    Returns (symbol, canonical_name) on a confident match, else (None, None)
 - never guesses a symbol without evidence."""
    if not detected_name:
        return None, None
    from tools.supabase_client import get_client
    sb = get_client()
    target_tokens = set(_normalize_name(detected_name).split())
    if not target_tokens:
        return None, None
    seed = sorted(target_tokens, key=len, reverse=True)[0]
    candidates = sb.table("companies").select("symbol,name").ilike("name", f"%{seed}%").limit(50).execute().data or []
    best, best_score = None, 0.0
    for c in candidates:
        cand_tokens = set(_normalize_name(c["name"]).split())
        if not cand_tokens:
            continue
        score = len(target_tokens & cand_tokens) / len(target_tokens | cand_tokens)
        if score > best_score:
            best, best_score = c, score
    if best and best_score >= 0.5:
        return best["symbol"], best["name"]
    return None, None


def _slug_symbol(detected_name):
    """Derives a placeholder symbol from the detected name when no
    existing registry match is found - generic slugging, not a
    per-company rule."""
    tokens = [t for t in _normalize_name(detected_name).split()]
    slug = "".join(tokens)[:15].upper() or f"MANUAL{int(time.time())}"
    return slug


def save_upload_auto(filename, content):
    """Upload entrypoint that needs no company selected up front: detects
    the company from the document itself, resolves it against the
    existing registry (or registers a new company from the detected name
    if it's genuinely not there yet), then proceeds exactly like
    save_upload + process_document. Returns
    {symbol, name, matched, document_id, ...process_document result} or
    {"error": ...}."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_FORMATS:
        return {"error": f"Unsupported file format: .{ext}"}

    try:
        pages = parse_document(content, ext)
    except Exception as e:
        return {"error": f"Could not read document: {e}"}
    if not pages:
        return {"error": "No extractable text found in document."}

    detected_name = detect_company_name(pages)
    if not detected_name:
        return {"error": "Could not identify the company from this document. Please open Manual from that company's page instead."}

    # ISIN/BSE-scrip-code match FIRST, before the fuzzy name match: these
    # are stable, unambiguous, government/exchange-assigned identifiers
    # printed in the document itself, unlike the company's printed name -
    # which can legitimately differ from whatever name the registry has on
    # file after a corporate rename (e.g. "Prime Fresh Limited" was
    # formerly "Prime Customer Services Limited", and the registry's
    # existing row could be under either name). A name-only match would
    # find no candidate for a renamed company and fall through to
    # `_slug_symbol`, minting an untradeable placeholder symbol that then
    # breaks every market-price-dependent ratio (see
    # `_backfill_listing_identifiers`'s docstring). Falls back to the
    # existing fuzzy name match when the document has no ISIN/scrip code.
    ids = _extract_listing_identifiers(pages)
    symbol, canonical_name = None, None
    if ids["isin"] or ids["bse_code"]:
        from tools.supabase_client import get_client
        sb = get_client()
        or_clauses = []
        if ids["isin"]:
            or_clauses.append(f"isin.eq.{ids['isin']}")
        if ids["bse_code"]:
            or_clauses.append(f"bse_code.eq.{ids['bse_code']}")
        rows = sb.table("companies").select("symbol,name").or_(",".join(or_clauses)).limit(1).execute().data
        if rows:
            symbol, canonical_name = rows[0]["symbol"], rows[0]["name"]

    if not symbol:
        symbol, canonical_name = resolve_symbol_by_name(detected_name)
    matched = symbol is not None
    if not symbol:
        symbol = _slug_symbol(detected_name)
        canonical_name = detected_name

    document_id = save_upload(symbol, filename, content, display_name=canonical_name)
    result = process_document(document_id)
    if "error" in result:
        return result
    return {"symbol": symbol, "name": canonical_name, "matched": matched, "document_id": document_id, **result}


def analyse_documents(ar_filename, ar_content, xbrl_filename=None, xbrl_content=None, symbol=None,
                       shareholding_filename=None, shareholding_content=None,
                       qualitative_documents=None):
    """The 'UPLOAD DOCUMENTS -> ANALYSE' entrypoint: Annual Report (required)
    plus NSE/BSE XBRL filing (optional) plus Shareholding Pattern filing
    (optional, feeds Sr 67/68 Promoter Pledge %/Free Float %). If `symbol`
    isn't already known, the company is detected from the Annual Report
    itself. The Annual Report is wired into the shared cache/ar_pdfs+ar_text
    caches; the XBRL filing (if given) is wired into tools/nse_xbrl.py's
    manual-override cache; the Shareholding Pattern filing (if given) into
    tools/nse_xbrl.py's manual-shareholding-override cache - all three are
    what every existing fundamental ratio endpoint and the qualitative engine
    already read from, so no per-ratio/per-subpoint changes are needed.
    Returns {symbol, name, matched, document_id, annual_report: {...},
    xbrl: {...}|None, shareholding: {...}|None} or {"error": ...}."""
    if symbol:
        sym = symbol.strip().upper().replace(".NS", "")
        try:
            document_id = save_upload(sym, ar_filename, ar_content)
        except ValueError as e:
            return {"error": str(e)}
        ar_result = process_document(document_id)
        name, matched = None, True
    else:
        auto = save_upload_auto(ar_filename, ar_content)
        if "error" in auto:
            return auto
        sym, name, matched = auto["symbol"], auto.get("name"), auto.get("matched")
        document_id = auto["document_id"]
        ar_result = {k: v for k, v in auto.items() if k in ("status", "pages_processed", "fiscal_year")}

    if "error" in ar_result:
        return ar_result

    # The category (Financial XBRL Filing / Shareholding Pattern Filing) is
    # independent of the uploaded file's physical format (CLAUDE.md/upload
    # policy): any format in _ALLOWED_FORMATS is accepted here. Only .xml/
    # .xbrl carry the structured facts save_manual_xbrl/save_manual_shareholding
    # parse for Sr 67/68 (Promoter Pledge %/Free Float %) - any other allowed
    # format (e.g. a PDF copy of the same filing) is still saved and text-
    # extracted as a searchable supporting document instead of being rejected,
    # since this pipeline genuinely cannot pull structured XBRL facts out of a
    # PDF/spreadsheet, but CAN still make its text searchable like every other
    # supporting document.
    xbrl_result = None
    if xbrl_content:
        ext = (xbrl_filename or "").rsplit(".", 1)[-1].lower() if "." in (xbrl_filename or "") else ""
        if ext not in _ALLOWED_FORMATS:
            xbrl_result = {"error": f"Unsupported file format: .{ext}"}
        elif ext in ("xml", "xbrl"):
            try:
                from tools.nse_xbrl import save_manual_xbrl
                save_manual_xbrl(sym, xbrl_content.decode("utf-8", errors="ignore"))
                # Also recorded in uploaded_documents (document_type=
                # "financial_xbrl_filing") even though the structured Sr 67/68
                # facts above are read from nse_xbrl.py's own manual-override
                # cache, not this row - without this, an .xml/.xbrl upload was
                # invisible to get_document_coverage's "uploaded" check
                # (confirmed real: only the non-XML fallback branch below ever
                # called save_upload, so an .xml Financial XBRL Filing that
                # WAS correctly processed for its structured facts still
                # showed as "Missing" on the Document Coverage panel). Also
                # makes the filing's own facts searchable by the qualitative
                # engine's anchor-phrase scan, same as every other supporting
                # document.
                doc_id = save_upload(sym, xbrl_filename, xbrl_content, document_type="financial_xbrl_filing")
                process_supporting_document(doc_id)
                xbrl_result = {"status": "processed"}
            except Exception as e:
                xbrl_result = {"error": str(e)}
        else:
            try:
                doc_id = save_upload(sym, xbrl_filename, xbrl_content, document_type="financial_xbrl_filing")
                xbrl_result = {"status": "saved_not_structured",
                                "note": "Structured XBRL facts (Sr 67/68) require a .xml/.xbrl file; "
                                        "this file was saved and made text-searchable instead.",
                                **process_supporting_document(doc_id)}
            except Exception as e:
                xbrl_result = {"error": str(e)}

    shareholding_result = None
    if shareholding_content:
        ext = (shareholding_filename or "").rsplit(".", 1)[-1].lower() if "." in (shareholding_filename or "") else ""
        if ext not in _ALLOWED_FORMATS:
            shareholding_result = {"error": f"Unsupported file format: .{ext}"}
        elif ext in ("xml", "xbrl"):
            try:
                from tools.nse_xbrl import save_manual_shareholding
                save_manual_shareholding(sym, shareholding_content.decode("utf-8", errors="ignore"))
                # Also recorded in uploaded_documents (document_type=
                # "shareholding_pattern_filing") - confirmed real: without
                # this, an .xml Shareholding Pattern upload was correctly
                # processed for Sr 67/68 (Promoter Pledge %/Free Float %)
                # but had NO row in uploaded_documents at all, so
                # get_document_coverage's "uploaded" check - and every
                # Section C/D qualitative sub-point gated on this document
                # ("Upload: Latest NSE/BSE Shareholding Pattern filing") -
                # showed it as "Missing" even though it genuinely was
                # uploaded and used.
                doc_id = save_upload(sym, shareholding_filename, shareholding_content, document_type="shareholding_pattern_filing")
                process_supporting_document(doc_id)
                shareholding_result = {"status": "processed"}
            except Exception as e:
                shareholding_result = {"error": str(e)}
        else:
            try:
                doc_id = save_upload(sym, shareholding_filename, shareholding_content, document_type="shareholding_pattern_filing")
                shareholding_result = {"status": "saved_not_structured",
                                        "note": "Structured shareholding facts (Sr 67/68) require a .xml/.xbrl file; "
                                                "this file was saved and made text-searchable instead.",
                                        **process_supporting_document(doc_id)}
            except Exception as e:
                shareholding_result = {"error": str(e)}

    # Qualitative supporting documents (Corporate Governance Report, BRSR/
    # ESG, Investor Presentation, Earnings Call Transcript, Credit Rating
    # Report, Other Supporting Document) - all optional, none block
    # analysis, none feed the 68-ratio Fundamental engine. Saved AND
    # extracted immediately (process_supporting_document), so their text is
    # already cached and searchable (see get_supporting_document_pages /
    # _fetch_ar_evidence_excerpts's extra_manual_document_types) by the time
    # this call returns - not merely uploaded and left inert.
    qualitative_results = {}
    for doc_type, (fname, content) in (qualitative_documents or {}).items():
        if not content:
            continue
        try:
            doc_id = save_upload(sym, fname, content, document_type=doc_type)
            extraction = process_supporting_document(doc_id)
            qualitative_results[doc_type] = {"status": "uploaded", "filename": fname, **extraction}
        except Exception as e:
            qualitative_results[doc_type] = {"error": str(e), "filename": fname}

    return {"symbol": sym, "name": name, "matched": matched, "document_id": document_id,
            "annual_report": ar_result, "xbrl": xbrl_result, "shareholding": shareholding_result,
            "qualitative_documents": qualitative_results}


# The qualitative supporting-document categories this upload flow accepts,
# beyond the Annual Report/Financial XBRL/Shareholding Pattern that already
# feed the Fundamental engine. Each is saved AND text-extracted at upload
# time (process_supporting_document); tools.annual_report_financials.
# _fetch_ar_evidence_excerpts's extra_manual_document_types parameter lets
# any existing/future qualitative compute_fn search their real content
# alongside the Annual Report, using the exact same proven anchor-phrase
# scan/score/dedup logic - never a separate, unproven extraction method.
QUALITATIVE_DOCUMENT_TYPES = (
    "corporate_governance_report", "brsr_esg_report", "investor_presentation",
    "earnings_call_transcript", "credit_rating_report",
    # "corporate_actions" was already read by ~15 compute_fns in
    # tools/qualitative_engine.py (Q.1.2, R.1.1, R.1.2, R.3.1, R.3.2, R.6.1,
    # R.6.2, C.8.2, D.3.2 and others - see _MANUAL_DOC_LABEL /
    # _manual_doc_uploaded there) via extra_manual_document_types=
    # ('corporate_actions',), but had NO upload slot at all - a user could
    # never actually get a document into it. Promoted to a real slot here so
    # those already-written code paths can finally be exercised. Serves the
    # "NSE/BSE Corporate Announcements history" required_document text.
    "corporate_actions",
    # The following 3 are new: previously any task naming one of these as
    # its required_document had no dedicated slot and fell into the generic
    # "other_supporting_document" bucket, where document_analysis_engine.py's
    # _requires_external_source() gate unconditionally forced
    # EXTERNAL_DATA_REQUIRED regardless of what was uploaded there.
    "shareholding_pattern_filing", "insider_trading_disclosures",
    "quarterly_corporate_governance_filing",
    "other_supporting_document",
)

# Sub-categories the "Other Supporting Documents" upload slot accepts - one
# generic multi-file slot (per the frontend's own single "optional, upload
# multiple files" section), not one field per sub-type, since different
# companies publish different subsets of these and none is individually
# required. Kept here purely as documentation of what that slot covers, for
# whichever future compute_fn work classifies a specific uploaded file by
# its own content/filename within this bucket - not itself a separate
# document_type value (all still save as "other_supporting_document").
OTHER_SUPPORTING_DOCUMENT_SUBTYPES = (
    "Secretarial Compliance Report",
    "Related Party Transaction disclosures",
    "Related Party Transaction Policy",
    "Risk Management Policy / Risk Management Report",
    "Materiality Policy",
    "Whistleblower / Vigil Mechanism Policy",
    "Code of Conduct",
    "Business Continuity / Disaster Recovery disclosures",
    "Regulation 30 disclosures",
    "Board Meeting disclosures",
    "Subsidiary / Joint Venture disclosures",
    "Material event disclosures",
    "Corporate governance policies",
    "Sustainability policies",
    "Other official NSE/BSE regulatory filings",
    "Other official company Investor Relations documents",
)


def map_required_document_to_type(required_document):
    """Maps a DATA_MISSING sub-point's free-text `required_document` (set
    per-KPI in qualitative_engine.py, e.g. 'Corporate Governance Report',
    'NSE/BSE Insider Trading disclosures') onto one of the 6 real,
    uploadable QUALITATIVE_DOCUMENT_TYPES, so the dashboard's per-card
    Upload button always has somewhere real to send the file - keyword
    matching against the 5 named categories, falling back to the generic
    'other_supporting_document' bucket for anything else (live-NSE/BSE-only
    references like Corporate Actions History or Insider Trading
    disclosures have no dedicated slot yet, but still land in a real,
    searchable document rather than being silently unsupported)."""
    text = (required_document or "").lower()
    # Check the 3 new NSE/BSE-portal-specific slots BEFORE the generic
    # "governance" keyword match below, since "NSE/BSE quarterly Corporate
    # Governance filing" would otherwise match "governance" and be routed to
    # the annual Corporate Governance Report slot instead - a distinct
    # document (quarterly NSE filing vs. the Annual Report's own chapter).
    if "shareholding pattern" in text:
        return "shareholding_pattern_filing"
    if "insider trading" in text:
        return "insider_trading_disclosures"
    if "corporate governance filing" in text or ("quarterly" in text and "governance" in text):
        return "quarterly_corporate_governance_filing"
    if "corporate announcements" in text or "corporate actions" in text:
        return "corporate_actions"
    if "governance" in text:
        return "corporate_governance_report"
    if "brsr" in text or "esg" in text:
        return "brsr_esg_report"
    if "earnings call" in text or "concall" in text or "transcript" in text:
        return "earnings_call_transcript"
    if "investor presentation" in text:
        return "investor_presentation"
    if "credit rating" in text:
        return "credit_rating_report"
    return "other_supporting_document"


def save_upload(symbol, filename, content, display_name=None, document_type=None):
    """Persists the raw file to disk and an uploaded_documents row.
    Returns the document_id. Never processes here - processing is a
    separate step so the upload response is fast. `document_type` is
    optional, defaults to None for the existing Annual Report call sites
    (kept backward compatible) - set it for the qualitative supporting
    documents (see QUALITATIVE_DOCUMENT_TYPES) so the coverage summary can
    report exactly what was and wasn't uploaded for a symbol."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_FORMATS:
        raise ValueError(f"Unsupported file format: .{ext}")

    sym = symbol.strip().upper().replace(".NS", "")
    doc_dir = os.path.join(_UPLOAD_DIR, sym)
    os.makedirs(doc_dir, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    storage_path = os.path.join(doc_dir, f"{int(time.time())}_{safe_name}")
    with open(storage_path, "wb") as fh:
        fh.write(content)

    from tools.supabase_client import get_client
    sb = get_client()
    # uploaded_documents.symbol references companies(symbol) - make sure the
    # row exists (a company the user typed may not be pre-registered).
    existing = sb.table("companies").select("symbol").eq("symbol", sym).limit(1).execute().data
    if not existing:
        sb.table("companies").insert({"symbol": sym, "name": display_name or sym}).execute()

    row = {
        "symbol": sym, "filename": filename,
        "file_size_bytes": len(content), "file_format": ext,
        "storage_path": storage_path, "status": "uploaded",
    }
    if document_type:
        row["document_type"] = document_type
    r = sb.table("uploaded_documents").insert(row).execute()
    return r.data[0]["id"]


def get_document_coverage(symbol):
    """Which qualitative supporting-document categories (see
    QUALITATIVE_DOCUMENT_TYPES) have at least one uploaded_documents row for
    this symbol, and which are missing - never guessed, always a real
    query against what was actually uploaded and persisted. Returns None
    (not a crash) if db/008_qualitative_document_types.sql hasn't been run
    yet - the document_type column won't exist until then."""
    sym = symbol.strip().upper().replace(".NS", "")
    from tools.supabase_client import get_client
    sb = get_client()
    try:
        rows = (sb.table("uploaded_documents").select("document_type,filename,uploaded_at")
                .eq("symbol", sym).execute().data)
    except Exception as e:
        print(f"[manual_document_pipeline] get_document_coverage unavailable "
              f"(has db/008_qualitative_document_types.sql been run?): {e}")
        return None
    uploaded_types = {r["document_type"]: r for r in rows if r.get("document_type")}
    coverage = {}
    for doc_type in QUALITATIVE_DOCUMENT_TYPES:
        hit = uploaded_types.get(doc_type)
        coverage[doc_type] = {"uploaded": hit is not None,
                               "filename": hit["filename"] if hit else None}
    has_ar = any((r.get("document_type") is None) for r in rows)  # AR rows are untyped (backward compatible)
    coverage["annual_report"] = {"uploaded": has_ar, "filename": None}
    return coverage


# ---------------------------------------------------------------------------
# Qualitative supporting-document extraction: mirrors the Annual Report's
# own cache/ar_pdfs+cache/ar_text treatment (tools/ar_document_cache.py) but
# keyed by (symbol, document_type) instead of (symbol, fiscal_year), since a
# Corporate Governance Report/BRSR/Investor Presentation/etc. isn't fiscal-
# year-anchored the way the Annual Report is. Generic across every company
# and every document type - no company-specific or document-specific logic.
# ---------------------------------------------------------------------------

_SUPPORTING_DOC_TEXT_CACHE_DIR = os.path.join(_BASE_DIR, "cache", "manual_docs_text")


def _supporting_doc_cache_path(symbol, document_type):
    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    safe_type = re.sub(r"[^a-z0-9_]", "", document_type.lower())
    return os.path.join(_SUPPORTING_DOC_TEXT_CACHE_DIR, f"{sym}_{safe_type}.json")


def _write_supporting_doc_cache(symbol, document_type, pages, filename):
    import json
    os.makedirs(_SUPPORTING_DOC_TEXT_CACHE_DIR, exist_ok=True)
    p = _supporting_doc_cache_path(symbol, document_type)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pages": pages, "filename": filename}, fh)


def get_supporting_document_pages(symbol, document_type):
    """Cached extracted page-text for one uploaded qualitative supporting
    document (see QUALITATIVE_DOCUMENT_TYPES), or None if none has been
    uploaded and successfully extracted for this symbol+type. Never raises,
    never fabricates - a missing/unextracted document means None, not an
    empty placeholder that would look like "searched and found nothing"."""
    import json
    p = _supporting_doc_cache_path(symbol, document_type)
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            pages = data.get("pages")
            return pages if pages else None
    except Exception:
        pass
    return None


def get_all_supporting_document_pages(symbol):
    """{document_type: [pages...]} for every supporting-document type that
    has actually been uploaded AND successfully extracted for this symbol -
    only real, non-empty entries; a type with no uploaded document, or one
    that failed extraction, is simply absent from the dict (never a fake
    empty-string placeholder)."""
    out = {}
    for doc_type in QUALITATIVE_DOCUMENT_TYPES:
        pages = get_supporting_document_pages(symbol, doc_type)
        if pages:
            out[doc_type] = pages
    return out


def process_supporting_document(document_id):
    """Extracts and caches text from an uploaded qualitative supporting
    document (Corporate Governance/BRSR-ESG/Investor Presentation/Earnings
    Call/Credit Rating/Other), mirroring process_document()'s treatment of
    the Annual Report, so get_supporting_document_pages (and, through it,
    _fetch_ar_evidence_excerpts's extra_manual_document_types) can search
    its real extracted text. Never raises; writes status='error' on the
    uploaded_documents row on failure instead, with extracted_text_length
    left null (never coerced to 0) so the failure is distinguishable from a
    genuinely empty document."""
    from tools.supabase_client import get_client
    sb = get_client()

    doc_row = sb.table("uploaded_documents").select("*").eq("id", document_id).limit(1).execute().data
    if not doc_row:
        return {"error": "document not found"}
    doc = doc_row[0]
    symbol = doc["symbol"]
    document_type = doc.get("document_type")
    if not document_type:
        return {"error": "not a supporting document (missing document_type)"}

    sb.table("uploaded_documents").update({"status": "processing"}).eq("id", document_id).execute()

    try:
        with open(doc["storage_path"], "rb") as fh:
            content = fh.read()
        pages = parse_document(content, doc["file_format"])
        text_length = sum(len(p) for p in pages)
        if not pages or text_length == 0:
            raise ValueError("No extractable text found in document")

        _write_supporting_doc_cache(symbol, document_type, pages, doc["filename"])

        sb.table("uploaded_documents").update({
            "status": "processed", "pages_processed": len(pages),
            "extracted_text_length": text_length, "analysis_consumed": True,
            "processed_at": "now()",
        }).eq("id", document_id).execute()
        return {"status": "processed", "pages_processed": len(pages), "extracted_text_length": text_length}
    except Exception as e:
        sb.table("uploaded_documents").update({
            "status": "error", "error_message": str(e),
        }).eq("id", document_id).execute()
        return {"error": str(e)}


def process_document(document_id):
    """Parses the stored PDF and writes into the SAME cache/ar_pdfs +
    cache/ar_text caches the automatic pipeline uses, then updates
    companies.latest_ar_year/latest_ar_url so every existing ratio
    endpoint and qualitative sub-point picks this document up
    transparently, with no other code changes required. Does not run any
    extraction itself - that happens on demand via search_document() once
    the user searches for a specific metric. Never raises; writes
    status='error' on the uploaded_documents row on failure instead."""
    from tools.supabase_client import get_client
    sb = get_client()

    doc_row = sb.table("uploaded_documents").select("*").eq("id", document_id).limit(1).execute().data
    if not doc_row:
        return {"error": "document not found"}
    doc = doc_row[0]
    symbol = doc["symbol"]

    sb.table("uploaded_documents").update({"status": "processing"}).eq("id", document_id).execute()

    try:
        with open(doc["storage_path"], "rb") as fh:
            content = fh.read()
        pages = parse_document(content, doc["file_format"])
        if not pages:
            raise ValueError("No extractable text found in document")

        # NEVER fall back to today's calendar year (`time.localtime().tm_year`)
        # - confirmed real bug: this silently mislabeled an uploaded document
        # as fiscal year 2026 (the year the upload happened to occur in) when
        # content-based detection found no evidence, later causing an annual
        # ratio to be computed against the wrong period entirely with no
        # indication anything was wrong. If the document itself contains no
        # determinable fiscal year, that is honestly reported as a
        # processing error rather than guessed.
        year = _guess_fiscal_year(pages)
        if year is None:
            sb.table("uploaded_documents").update({
                "status": "error",
                "error_message": "Could not determine the fiscal year from this document's own content "
                                  "(no 'year ended'/'as at March 31, YYYY' statement date or 'FY YYYY'/"
                                  "'Annual Report YYYY' cover phrasing found) - the document may not be a "
                                  "standard Annual Report, or its text extraction may have failed. "
                                  "Please verify and re-upload.",
            }).eq("id", document_id).execute()
            return {"error": "Could not determine fiscal year from document content - not guessed from today's date."}

        _write_shared_ar_caches(symbol, year, pages, doc["storage_path"])
        _point_company_at_manual_ar(sb, symbol, year)
        _backfill_listing_identifiers(sb, symbol, pages)

        sb.table("uploaded_documents").update({
            "status": "processed", "fiscal_year": year,
            "pages_processed": len(pages), "processed_at": "now()",
        }).eq("id", document_id).execute()

        return {"status": "processed", "pages_processed": len(pages), "fiscal_year": year}
    except Exception as e:
        sb.table("uploaded_documents").update({
            "status": "error", "error_message": str(e),
        }).eq("id", document_id).execute()
        return {"error": str(e)}


def _guess_fiscal_year(pages):
    """Determines the fiscal year from evidence IN the document itself,
    generic across every company/filing - never from today's date or the
    filename. Priority order per spec ("1. Annual Report title/cover, 2.
    Financial statements' Year ended/As at dates, 3. Statement headers with
    current+comparative years, ... only as a fallback"):

    1. Cover/title page "FY"/"Financial Year"/"Annual Report 'YYYY-YY"
       phrasing - the report's own stated identity, checked first per spec,
       and unambiguous when present (a report is always explicitly titled
       with the period it covers).
    2. The financial statements' own "year ended"/"as at March 31, YYYY"
       language, used ONLY when the cover page has no clear year - scanned
       widely (up to 250 pages; large Integrated Annual Reports can run
       300-400+ pages before the audited statements themselves) and taking
       the MOST FREQUENT closing year mentioned (not just the max of
       whatever's found first) - a document's Directors' Report/MD&A
       narrative pages routinely discuss the PRIOR year's results in prose
       ("as at March 31, 2024, the Company had...") well before the actual
       statement pages are reached, and a small scan window or a naive
       max()/first-match can lock onto that comparative-year mention
       instead of the true current period - confirmed real: an early
       version of this fix, scanning only 60 pages and taking max(), read
       ANURAS's own document as FY2024 instead of FY2025 because its
       Directors' Report (a few pages in) references FY24 before the real
       P&L statement (~180 pages in) is ever reached. Frequency-based
       selection is robust to this: Schedule III repeats the CURRENT year's
       own closing date on every one of the statement's several pages
       (P&L, Balance Sheet, Cash Flow, dozens of Notes), so it is always
       the single most-mentioned year in the document once the real
       statement section is included in the scan, even if a handful of
       earlier narrative pages mention a different (comparative) year.
    3. A bare "YYYY-YY" pattern anywhere in the first few pages.

    Confirmed real bug this replaces: the previous version only checked the
    first 5 pages with weaker patterns, and its caller silently fell back
    to `time.localtime().tm_year` (TODAY'S calendar year) whenever this
    returned None - exactly the "infer the FY from today's date" failure
    mode explicitly ruled out by the project's document-driven-not-date-
    driven policy. Returns None (never a calendar-year guess) when no real
    evidence is found anywhere in the scanned pages - the caller must treat
    that honestly (needs review), not default to any year."""
    # Cover/opening pages - deliberately case-INSENSITIVE (confirmed real
    # miss: "Submission of Integrated Annual Report for the financial year
    # 2024-25" uses lowercase "financial year", which the previous
    # case-sensitive pattern never matched) and tolerant of words BETWEEN
    # the keyword and the year ("...Annual Report FOR THE financial year
    # 2024-25" - the keyword and the year are not adjacent), both standard,
    # generic SEBI/Companies-Act filing-cover-letter phrasing, not specific
    # to any one company. Prefers the "YYYY-YY" form (unambiguous - always
    # the audited period, e.g. "2024-25" means FY ending March 2025) over a
    # bare 4-digit year (which can be the PUBLICATION year on some covers).
    text = " ".join(pages[:5])
    m = re.search(r"(?:financial year|annual report)(?:[^.\n]{0,20})?\b(20\d{2})-(\d{2})\b", text, re.I)
    if m:
        return int(m.group(1)) + 1  # "2024-25" -> FY ends in 2025
    m = re.search(r"(?:FY|financial year|annual report)\s*[\'\"]?(20\d{2})\b", text, re.I)
    if m:
        return int(m.group(1))

    # Financial statements' own "year ended"/"as at March 31, YYYY" dates -
    # used only when the cover has no clear year. Scanned widely (large
    # Integrated Annual Reports can run 300-400+ pages before the audited
    # statements are reached) and taking the MOST FREQUENT closing year
    # (not the first/max match) - a Directors' Report/MD&A narrative
    # routinely mentions the PRIOR year's date in prose well before the
    # real statement pages, and Schedule III repeats the CURRENT year's own
    # closing date on every one of the statement's several pages (P&L,
    # Balance Sheet, Cash Flow, dozens of Notes), so it's the single
    # most-mentioned year once the real statement section is included.
    stmt_text = " ".join(pages[:250]).lower()
    stmt_dates = re.findall(
        r"(?:year ended|as at|as on)\s+(?:31st?\s+)?march,?\s+(\d{4})", stmt_text)
    if stmt_dates:
        from collections import Counter
        return int(Counter(stmt_dates).most_common(1)[0][0])

    m = re.search(r"20\d{2}-\d{2}", text)
    if m:
        return int(m.group(0)[:4]) + 1
    return None


def _write_shared_ar_caches(symbol, fiscal_year, pages, pdf_storage_path):
    """Mirrors tools/ar_table_extractor.py + tools/ar_document_cache.py's
    on-disk cache layout so every existing consumer of get_ar_pages()
    transparently reads the manually uploaded document."""
    import json
    import shutil

    sym = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    pdf_cache_dir = os.path.join(_BASE_DIR, "cache", "ar_pdfs")
    text_cache_dir = os.path.join(_BASE_DIR, "cache", "ar_text")
    os.makedirs(pdf_cache_dir, exist_ok=True)
    os.makedirs(text_cache_dir, exist_ok=True)

    shutil.copyfile(pdf_storage_path, os.path.join(pdf_cache_dir, f"{sym}_{fiscal_year}.pdf"))
    with open(os.path.join(text_cache_dir, f"{sym}_{fiscal_year}.json"), "w", encoding="utf-8") as fh:
        json.dump({"pages": pages, "pdf_url": f"manual-upload://{sym}_{fiscal_year}", "fiscal_year": fiscal_year}, fh)


def _point_company_at_manual_ar(sb, symbol, fiscal_year):
    sym = symbol.strip().upper().replace(".NS", "")
    sb.table("companies").update({
        "latest_ar_year": fiscal_year,
        "latest_ar_url": f"manual-upload://{sym}_{fiscal_year}",
        "registry_status": "resolved",
        "registry_updated_at": "now()",
    }).eq("symbol", sym).execute()


_ISIN_RE = re.compile(r"ISIN[^A-Z0-9]{0,25}([A-Z]{2}[A-Z0-9]{9}\d)")
_BSE_CODE_RE = re.compile(
    r"(?:BSE\s*(?:Limited)?\s*\(BSE\)|Stock\s*Code[^:\n]{0,20}BSE|BSE\s*(?:Scrip|Stock)\s*Code)"
    r"[^0-9\n]{0,20}(\d{6})", re.I)


def _extract_listing_identifiers(pages):
    """Scans the Annual Report's own text for its ISIN and BSE scrip code -
    the company's real, stable market identifiers - printed on every
    Indian AR's 'Corporate Information'/General Shareholder Information
    page (e.g. "International Standard Identification Number (ISIN):
    INE442V01012" and "Stock Code BSE Limited (BSE) : 540404"). Generic
    regex scan, not tied to any one company's phrasing/layout. Returns
    {"isin": str|None, "bse_code": str|None} - never fabricates; a field
    is None if genuinely not found in the text.

    Why this matters: the company's internal registry `symbol` (assigned
    from a fuzzy/best-effort match, or a synthetic slug when no registry
    match is found - see resolve_symbol_by_name/_slug_symbol above) is NOT
    guaranteed to be the company's real tradeable market ticker, especially
    for SME/small-cap companies or ones that changed their legal name
    without a matching ticker rename. Without the real ISIN/BSE scrip code,
    every market-price-dependent ratio (P/E, P/B, P/S, Dividend Yield,
    EV/EBITDA, FCF Yield, Price/Cash Flow, Altman Z-Score, and everything
    derived from them - see tools/market_price.py) silently fails for such
    a company even though the Annual Report + a live price would otherwise
    be sufficient (confirmed real on Prime Fresh Limited: registry symbol
    "LANDMARKACHIEVE" - a synthetic slug - vs. its actual BSE-listed
    trading symbol "PRIMEFRESH", scrip code 540404)."""
    isin = None
    bse_code = None
    for p in pages:
        text = p.get("text", "") if isinstance(p, dict) else (p or "")
        if not text:
            continue
        if isin is None:
            m = _ISIN_RE.search(text)
            if m:
                isin = m.group(1)
        if bse_code is None:
            m = _BSE_CODE_RE.search(text)
            if m:
                bse_code = m.group(1)
        if isin and bse_code:
            break
    return {"isin": isin, "bse_code": bse_code}


def _backfill_listing_identifiers(sb, symbol, pages):
    """Fills companies.isin/bse_code from the Annual Report's own text when
    the registry doesn't already have them - never overwrites an existing
    value (a document-derived value is a fallback, not an override of
    whatever the registry already trusts). Never raises - a lookup/update
    failure here must not block the rest of document processing."""
    try:
        found = _extract_listing_identifiers(pages)
        if not found["isin"] and not found["bse_code"]:
            return
        sym = symbol.strip().upper().replace(".NS", "")
        row = sb.table("companies").select("isin,bse_code").eq("symbol", sym).limit(1).execute().data
        current = row[0] if row else {}
        patch = {}
        if found["isin"] and not current.get("isin"):
            patch["isin"] = found["isin"]
        if found["bse_code"] and not current.get("bse_code"):
            patch["bse_code"] = found["bse_code"]
        if patch:
            sb.table("companies").update(patch).eq("symbol", sym).execute()
    except Exception as e:
        print(f"[manual_document_pipeline] listing-identifier backfill failed for {symbol}: {e}")
