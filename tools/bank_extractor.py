"""Layout-aware reader for RBI-format bank annual reports (Banking Regulation Act Schedules 1-18).

Why this exists: the earlier bank reader matched a label and took the next two numbers within 250 characters, which
silently picked the wrong row (Kotak "Advances" read from a prose line, Deposits Note rows read from sub-lines) and never
normalised units (ICICI/Kotak print in Rs '000). This reader works on word coordinates, so every figure comes from the
SAME printed row as its label, then proves what it read with the statements' own accounting identities:

  * Schedule 3: Demand + Savings + Term deposits == Total deposits == Balance-sheet Deposits
  * Balance sheet: Total liabilities == Total assets
  * every figure is converted to Rs Crore from the unit declared on ITS OWN page

BASIS POLICY (documented, global): bank ratios are computed on the bank's STANDALONE statements. The RBI-mandated
disclosures (asset quality, CRAR, PCR, Schedule 3) exist only at the standalone bank level, and a bank group's consolidated
P&L contains insurance / broking / AMC lines (Kotak: other income Rs 41,233 Cr vs Rs 6,000 Cr standalone) that make NIM and
cost-to-income meaningless. The basis is always reported in the result.

Nothing here is company-specific; a figure that cannot be proven is returned as None (unknown), never 0.
"""
import re

_NUM_TOK = re.compile(r"^(?:\(-?\d[\d,]*(?:\.\d+)?\)|-?\d[\d,]*(?:\.\d+)?)%?$")   # a bare "2)" is a label fragment, not a figure
_DASH = {"-", "–", "—"}


def _unit_factor_to_crore(text):
    """Rs Crore multiplier from the unit declared on a page (header such as '(` in '000)', '(₹ in thousands)', 'in Crore',
    'in million', 'in lakh'). Defaults to crore when nothing is declared."""
    t = text or ""
    if re.search(r"\(\s*000s?\s*omitted\s*\)", t, re.I) or re.search(r"[`₹HC]?\s*in\s*(?:[‘'’]?\s*000s?|thousands?)\b", t, re.I) or re.search(r"\(\s*[`₹H]?\s*[‘'’]000\s*\)", t):
        return 1e-4
    if re.search(r"[`₹H]\s*in\s*million", t, re.I) or re.search(r"\(\s*in\s*[`₹H]?\s*million", t, re.I):
        return 0.1
    if re.search(r"[`₹H]\s*in\s*lakh", t, re.I):
        return 0.01
    return 1.0


def page_lines(page, ytol=3.0):
    """Reading-order text lines of a page as lists of tokens (a row of a table is one line)."""
    ws = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
    rows = []
    for w in ws:
        for r in rows:
            if abs(r[0] - w[1]) <= ytol:
                r[1].append(w)
                break
        else:
            rows.append([w[1], [w]])
    return [[x[4] for x in sorted(r[1], key=lambda x: x[0])] for r in sorted(rows, key=lambda r: r[0])]


def _num(tok):
    if tok in _DASH:
        return 0.0
    t = tok.strip()
    pct = t.endswith("%")
    t = t.rstrip("%")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if (neg and v > 0) else v


def parse_row(tokens):
    """-> (label, [numbers]) : trailing numeric tokens are the values, everything before them is the label. A leading small
    integer (the 'Schedule' reference column) is dropped when at least two more figures follow it."""
    nums, i = [], len(tokens)
    while i > 0 and (_NUM_TOK.match(tokens[i - 1]) or tokens[i - 1] in _DASH):
        i -= 1
    vals = tokens[i:]
    label = " ".join(tokens[:i]).strip()
    n = [_num(v) for v in vals]
    if len(n) >= 3 and vals[0].isdigit() and int(vals[0]) <= 99:
        n = n[1:]
    return label, [x for x in n if x is not None]


def rows_of(page):
    return [parse_row(t) for t in page_lines(page)]


def _norm(label):
    s = label.lower()
    s = re.sub(r"\(.*?\)", " ", s)                       # (a)+(b), (Refer Note ..), (%)
    for _ in range(3):                                      # 'A. I. Demand deposits' / 'A I. Demand' / '(i) From banks'
        s = re.sub(r"^\s*(?:\(?[ivx]+[.)]|\(?[ab][.)]|\d+[.)]|[ab](?=\s+[ivx]+[.)]))\s*", "", s)
    s = re.sub(r"(?<=[a-z])\d+\b", "", s)                 # footnote digits glued to a word: 'assets2 to net advances3'
    s = re.sub(r"[^a-z0-9 &/\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_row(rows, pattern, *, start=0, need=2):
    """First row (from `start`) whose normalised label matches `pattern` and which carries >= `need` figures."""
    rx = re.compile(pattern)
    for k in range(start, len(rows)):
        label, nums = rows[k]
        if len(nums) >= need and rx.search(_norm(label)):
            return k, label, nums
    return None


def _pair(hit, factor=1.0):
    if not hit:
        return None
    _, _, nums = hit
    return (round(nums[0] * factor, 4), round(nums[1] * factor, 4))


# --------------------------------------------------------------------------------------------------------------------
# page discovery
# --------------------------------------------------------------------------------------------------------------------
def _basis_of(lines_text):
    """Statement basis from the page's own caption/footer. Captions are sometimes letter-spaced ('C O N S O L I D AT E D'),
    so the comparison ignores spaces."""
    head = re.sub(r"\s+", "", " ".join(lines_text[:14]).lower())
    if "consolidated" in head:
        return "consolidated"
    if "standalone" in head or "standlone" in head or "stand-alone" in head:
        return "standalone"
    whole = re.sub(r"\s+", "", " ".join(lines_text).lower())
    if "consolidated" in whole:
        return "consolidated"
    if "standalone" in whole or "standlone" in whole:
        return "standalone"
    return None


def classify_pages(doc):
    """[(page_index, kind, basis, rows, text)] for balance-sheet faces, P&L faces and Schedule 3 pages."""
    out = []
    for i in range(doc.page_count):
        try:
            tl = page_lines(doc[i])
        except Exception:
            continue
        lines = [" ".join(t) for t in tl]
        raw = "\n".join(lines)
        low = raw.lower()
        head = "\n".join(lines[:10]).lower()
        if not re.search(r"deposits|interest earned|interest income", low):
            continue
        rows = [parse_row(t) for t in tl]
        kind = None
        if re.search(r"^schedule\s*3\b[^\n]{0,12}deposits", low, re.M):
            kind = "SCH3"
        elif re.search(r"schedule\s*\d+\s*[-–]", head):
            kind = None                                             # some other schedule page
        else:
            labels = {_norm(r[0]) for r in rows if len(r[1]) >= 2}
            has = lambda rx: any(re.search(rx, l) for l in labels)
            if has(r"^deposits$") and has(r"^advances$") and has(r"^investments$") and has(r"^borrowings$"):
                kind = "BS"
            elif has(r"^interest earned") and has(r"^interest expended") and has(r"^operating expenses"):
                kind = "PL"
        if kind:
            out.append((i, kind, _basis_of(lines), rows, raw))
    return out


def _resolve_basis(pages):
    """Pages whose header does not name the basis inherit it from the closest preceding page that does (statements are
    printed as standalone block then consolidated block, or the reverse)."""
    res, last = [], None
    for (i, kind, basis, rows, low) in pages:
        b = basis or last
        if basis:
            last = basis
        res.append((i, kind, b, rows, low))
    return res


# --------------------------------------------------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------------------------------------------------
def _deposit_component(rows, pattern_parent, stop_pattern):
    """A Schedule-3 component printed either as one row or as a parent row with 'from banks' / 'from others' sub-rows."""
    hit = find_row(rows, pattern_parent)
    if hit:
        return hit[2][:2], "row"
    rx = re.compile(pattern_parent)
    for k, (label, nums) in enumerate(rows):
        if rx.search(_norm(label)) and not nums:
            tot = [0.0, 0.0]
            got = 0
            for label2, nums2 in rows[k + 1:k + 6]:
                n2 = _norm(label2)
                if re.search(stop_pattern, n2):
                    break
                if len(nums2) >= 2 and re.search(r"from banks|from others|from other", n2):
                    tot[0] += nums2[0]
                    tot[1] += nums2[1]
                    got += 1
            if got:
                return tuple(tot), "sum-of-sub-rows"
    return None, None


def extract_bank(doc, want="standalone"):
    """Reads the bank's statements. -> dict of named figures, each {'cur','prior','page','unit_factor'} in Rs Crore (or %),
    plus 'basis', 'identities' (what was proven) and 'problems' (what could not be proven)."""
    pages = _resolve_basis(classify_pages(doc))
    res = {"basis": want, "problems": [], "identities": {}}
    sel = lambda kind: [p for p in pages if p[1] == kind and p[2] == want]
    bs_l, pl_l, s3_l = sel("BS"), sel("PL"), sel("SCH3")
    if not bs_l:
        res["problems"].append(f"No {want} balance-sheet page with Deposits/Advances/Investments/Borrowings rows was found.")
        return res

    def put(name, pair, page_i, factor, method="row"):
        if pair is not None:
            res[name] = {"cur": pair[0], "prior": pair[1], "page": page_i + 1, "unit_factor": factor, "method": method}

    i, _, _, rows, low = bs_l[0]
    f = _unit_factor_to_crore(low)
    for name, rx in (("deposits", r"^deposits$"), ("advances", r"^advances$"), ("investments", r"^investments$"),
                     ("borrowings", r"^borrowings$"),
                     ("cash_rbi", r"^cash and balances with reserve bank|^balances with reserve bank"),
                     ("balances_banks", r"^balances with banks and money at call")):
        hit = find_row(rows, rx)
        put(name, _pair(hit, f), i, f)
    tl = [r for r in rows if re.search(r"^total", _norm(r[0])) and len(r[1]) >= 2]
    if len(tl) >= 2:                              # the two 'Total' rows of a balance sheet (liabilities, assets) must be equal
        a, b = tl[0][1][0], tl[1][1][0]
        res["identities"]["balance_sheet_total"] = abs(a - b) <= 0.001 * max(abs(a), abs(b), 1)
    if pl_l:
        i, _, _, rows, low = pl_l[0]
        f = _unit_factor_to_crore(low)
        for name, rx in (("interest_earned", r"^interest earned"), ("interest_expended", r"^interest expended"),
                         ("other_income", r"^other income"), ("operating_expenses", r"^operating expenses")):
            put(name, _pair(find_row(rows, rx), f), i, f)
    else:
        res["problems"].append(f"No {want} profit-and-loss page with Interest Earned/Expended/Operating expenses rows was found.")

    # Schedule 3 with its own identity proof
    for (i, _, _, rows, low) in s3_l[:1]:
        f = _unit_factor_to_crore(low)
        dem, m1 = _deposit_component(rows, r"^demand deposits$", r"^savings|^term")
        sav = find_row(rows, r"^savings bank deposits$|^savings deposits$")
        ter, m2 = _deposit_component(rows, r"^term deposits$", r"^total")
        tot = find_row(rows, r"^total deposits$")
        if not tot and dem and sav and ter:
            # some banks print the grand total as a bare 'Total': take the 'Total' row equal to Demand + Savings + Term
            want_sum = (dem[0] + sav[2][0] + ter[0])
            for lab, nums in rows:
                if len(nums) >= 2 and _norm(lab) == "total" and abs(nums[0] - want_sum) <= 0.005 * want_sum:
                    tot = (0, lab, nums)
                    break
        put("demand_deposits", dem, i, f, m1 or "row")
        put("savings_deposits", _pair(sav), i, f) if sav else None
        if sav:
            put("savings_deposits", (sav[2][0] * f, sav[2][1] * f), i, f)
        put("term_deposits", ter, i, f, m2 or "row") if ter else None
        if ter:
            put("term_deposits", (ter[0] * f, ter[1] * f), i, f, m2 or "row")
        if dem:
            put("demand_deposits", (dem[0] * f, dem[1] * f), i, f, m1 or "row")
        if tot:
            put("schedule3_total", (tot[2][0] * f, tot[2][1] * f), i, f)
        if all(k in res for k in ("demand_deposits", "savings_deposits", "term_deposits", "schedule3_total")):
            s = res["demand_deposits"]["cur"] + res["savings_deposits"]["cur"] + res["term_deposits"]["cur"]
            res["identities"]["schedule3_components_sum_to_total"] = abs(s - res["schedule3_total"]["cur"]) <= 0.005 * res["schedule3_total"]["cur"]
        if "deposits" in res and "schedule3_total" in res:
            res["identities"]["schedule3_total_equals_balance_sheet"] = \
                abs(res["schedule3_total"]["cur"] - res["deposits"]["cur"]) <= 0.01 * res["deposits"]["cur"]
    if not s3_l:
        res["problems"].append("Schedule 3 (Deposits) page was not found for this basis.")

    # disclosed ratios (RBI mandated disclosures) - searched within this basis' block of pages
    lo = bs_l[0][0]
    other = [p[0] for p in pages if p[2] != want and p[0] > lo]
    hi = min(other) if other else doc.page_count
    res["_disclosure_range"] = (max(lo - 40, 0), hi)
    return res


_DISCLOSED = {
    "gross_npa_pct": (r"gross npa(s)?( ratio)?( to gross advances)?$|^gross npa(s)? to gross advances|gross non.performing (assets|advances) (to|ratio)|^gross npa ratio|^gross npas? %", (0.0, 60.0)),
    "net_npa_pct": (r"^net npa(s)?( ratio)?( to net advances)?$|^net npa(s)? to net advances|net non.performing (assets|advances) (to|ratio)|^net npa ratio|^net npas? %", (0.0, 60.0)),
    "crar_pct": (r"capital to risk[- ]weighted assets? ratio|^capital adequacy ratio|^crar|^total capital ratio|capital adequacy ratio \(crar\)", (0.0, 60.0)),
    "pcr_pct": (r"provision coverage ratio|^pcr", (0.0, 200.0)),
    "nim_pct": (r"^net interest margin|^nim", (-5.0, 20.0)),
    "cost_income_pct": (r"cost to income ratio|cost-to-income ratio|^cost income ratio", (0.0, 300.0)),
}


def find_disclosed_ratios(doc, rng):
    """Ratios the bank itself prints (RBI 'Disclosures' notes / key-ratio tables) within [rng) pages. Returns
    {name: {'cur','prior','page','label'}} using the first row whose label matches and whose value is in a plausible range."""
    out = {}
    for i in range(rng[0], min(rng[1], doc.page_count)):
        try:
            rows = rows_of(doc[i])
        except Exception:
            continue
        for name, (rx, (lo, hi)) in _DISCLOSED.items():
            if name in out:
                continue
            r = re.compile(rx)
            for label, nums in rows:
                nl = _norm(label)
                if len(nums) >= 1 and r.search(nl) and len(nl) <= 110 and not re.search(
                        r"require|minimum|maintain|should|shall|regulat|guideline|stipulat|buffer", nl):
                    v = nums[0]
                    if lo <= v <= hi:
                        out[name] = {"cur": v, "prior": nums[1] if len(nums) > 1 else None, "page": i + 1, "label": label[:80]}
                        break
    return out


_PROSE = {
    "pcr_pct": r"provision coverage ratio",
    "gross_npa_pct": r"gross npa(?:s)?(?: ratio)?|gross non.performing assets? ratio",
    "net_npa_pct": r"net npa(?:s)?(?: ratio)?|net non.performing assets? ratio",
}


def find_disclosed_prose(doc, rng, names):
    """Fallback for a disclosure printed as a sentence ('The Provision Coverage Ratio of the Bank ... is 80.38% as at ...')
    rather than a table row. Requires the figure to follow the label within one sentence, and skips regulatory-minimum prose."""
    out = {}
    for i in range(rng[0], min(rng[1], doc.page_count)):
        if all(n in out for n in names):
            break
        try:
            text = " ".join(" ".join(t) for t in page_lines(doc[i]))
        except Exception:
            continue
        for name in names:
            if name in out or name not in _PROSE:
                continue
            for m in re.finditer(_PROSE[name], text, re.I):
                tail = text[m.end():m.end() + 170]
                mm = re.search(r"\b(?:is|was|stood at|at|of|being)\s+(\d{1,3}(?:\.\d+)?)\s*%", tail)
                if mm and not re.search(r"minimum|require|regulat", text[max(0, m.start() - 60):m.end() + 60], re.I):
                    lo, hi = _DISCLOSED[name][1]
                    v = float(mm.group(1))
                    if lo <= v <= hi:
                        out[name] = {"cur": v, "prior": None, "page": i + 1,
                                     "label": (text[max(0, m.start() - 20):m.end() + mm.end() + 20]).strip()[:110]}
                        break
    return out


def find_capital_amounts(doc, rng):
    """Total capital funds and total risk-weighted assets (amounts, Rs Crore) from the Basel III capital table, so CRAR can be
    computed (and proven) instead of trusting a printed ratio. Both rows must be on the same page."""
    for i in range(rng[0], min(rng[1], doc.page_count)):
        try:
            tl = page_lines(doc[i])
        except Exception:
            continue
        rows = [parse_row(t) for t in tl]
        text = " ".join(" ".join(t) for t in tl)
        cap = find_row(rows, r"^total capital( funds)?( tier 1 ?\+ ?tier 2)?$|^total eligible capital|^total capital funds|^total regulatory capital")
        rwa = find_row(rows, r"^total risk[- ]weighted assets|^risk[- ]weighted assets( total)?$|^total rwa|^total risk weighted (assets|exposures)")
        if cap and rwa and cap[2][0] > 1000 and rwa[2][0] > 1000 and cap[2][0] < rwa[2][0]:
            f = _unit_factor_to_crore(text)
            return {"capital": {"cur": cap[2][0] * f, "prior": cap[2][1] * f, "label": cap[1][:60]},
                    "rwa": {"cur": rwa[2][0] * f, "prior": rwa[2][1] * f, "label": rwa[1][:60]}, "page": i + 1}
    return None


# --------------------------------------------------------------------------------------------------------------------
# NBFC / HFC (Ind AS Division III) statements
# --------------------------------------------------------------------------------------------------------------------
def _rows_in_x(page, lo, hi, ytol=3.0):
    ws = [w for w in page.get_text("words") if lo <= w[0] < hi]
    ws.sort(key=lambda w: (w[1], w[0]))
    rows = []
    for w in ws:
        for r in rows:
            if abs(r[0] - w[1]) <= ytol:
                r[1].append(w)
                break
        else:
            rows.append([w[1], [w]])
    return [parse_row([x[4] for x in sorted(r[1], key=lambda x: x[0])]) for r in sorted(rows, key=lambda r: r[0])]


def extract_nbfc(doc):
    """Ind AS NBFC/HFC statements. Pages that print the balance sheet and the P&L side by side are read per column half.
    Basis: consolidated first (a lending group's statements are comparable), standalone if that is all there is."""
    cands = {"BS": [], "PL": []}
    for i in range(doc.page_count):
        try:
            page = doc[i]
            tl = page_lines(page)
        except Exception:
            continue
        low = " ".join(" ".join(t) for t in tl).lower()
        if not ("total assets" in low or "finance costs" in low):
            continue
        basis = _basis_of([" ".join(t) for t in tl])
        w = page.rect.width
        for variant in (rows_of(page), _rows_in_x(page, 0, w / 2), _rows_in_x(page, w / 2 - 20, w + 1)):
            labs = {_norm(r[0]) for r in variant if len(r[1]) >= 2}
            has = lambda rx: any(re.search(rx, l) for l in labs)
            if has(r"^loans$") and has(r"^investments$") and has(r"^total assets$"):
                cands["BS"].append((i, basis, variant, low))
            if has(r"^interest income$") and has(r"^finance costs$") and (has(r"^total income$") or has(r"^total revenue from operations$")):
                cands["PL"].append((i, basis, variant, low))
    out = {"format": "nbfc", "problems": [], "identities": {}}
    for want in ("consolidated", "standalone"):
        bs = [c for c in cands["BS"] if c[1] == want]
        pl = [c for c in cands["PL"] if c[1] == want]
        if bs and pl:
            break
    else:
        bs = cands["BS"][:1]
        pl = cands["PL"][:1]
        want = (bs[0][1] if bs else None) or "unknown"
    if not bs or not pl:
        out["problems"].append("No Ind AS NBFC balance sheet (Loans / Investments / Total assets) and P&L (Interest income / Finance costs) pair found.")
        return out
    out["basis"] = want
    i, _, rows, low = bs[0]
    f = _unit_factor_to_crore(low)
    for name, rx in (("loans", r"^loans$"), ("investments", r"^investments$"), ("cash_equivalents", r"^cash and cash equivalents$"),
                     ("total_assets", r"^total assets$")):
        hit = find_row(rows, rx)
        if hit:
            out[name] = {"cur": hit[2][0] * f, "prior": hit[2][1] * f, "page": i + 1, "unit_factor": f}
    i, _, rows, low = pl[0]
    f = _unit_factor_to_crore(low)
    for name, rx in (("interest_income", r"^interest income$"), ("finance_costs", r"^finance costs$"),
                     ("total_income", r"^total income$"), ("employee_cost", r"^employee benefits? expenses?$"),
                     ("depreciation", r"^depreciation"), ("other_expenses", r"^other expenses$|^others expenses$")):
        hit = find_row(rows, rx)
        if hit:
            out[name] = {"cur": hit[2][0] * f, "prior": hit[2][1] * f, "page": i + 1, "unit_factor": f}
    out["_disclosure_range"] = (bs[0][0], doc.page_count)
    return out


# --------------------------------------------------------------------------------------------------------------------
# core per-share / profit facts of a bank, so the generic valuation ratios (P/E, P/B, EPS growth, BVPS, ROA, yields, payout)
# can run on an RBI-format filing exactly as they do on a Schedule III one
# --------------------------------------------------------------------------------------------------------------------
_FACE_VALUE_RE = re.compile(r"shares?\s+of\s+(?:[`₹]|rs\.?|inr|[CHKJ])\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*each", re.I)


def extract_bank_core(doc, r):
    """From an `extract_bank` result: Net profit, Basic EPS, Capital, Reserves & surplus, Total assets, face value and the
    share count (= Capital / face value) of the bank's standalone statements. Every figure comes from its printed row;
    anything not found stays absent."""
    out = {}
    bs_p, pl_p = (r.get("deposits") or {}).get("page"), (r.get("interest_earned") or {}).get("page")
    if not bs_p:
        return out
    bs_rows, bs_text = rows_of(doc[bs_p - 1]), " ".join(" ".join(t) for t in page_lines(doc[bs_p - 1]))
    f_bs = _unit_factor_to_crore(bs_text)
    cap = find_row(bs_rows, r"^capital$")
    res = find_row(bs_rows, r"^reserves and surplus$|^reserves & surplus$")
    tots = [x for x in bs_rows if _norm(x[0]) == "total" and len(x[1]) >= 2]
    if cap:
        out["capital"] = {"cur": cap[2][0] * f_bs, "prior": cap[2][1] * f_bs, "page": bs_p}
    if res:
        out["reserves"] = {"cur": res[2][0] * f_bs, "prior": res[2][1] * f_bs, "page": bs_p}
    ta_row = find_row(bs_rows, r"^total assets$")
    if ta_row:
        out["total_assets"] = {"cur": ta_row[2][0] * f_bs, "prior": ta_row[2][1] * f_bs, "page": bs_p}
    elif len(tots) >= 2:
        out["total_assets"] = {"cur": tots[1][1][0] * f_bs, "prior": tots[1][1][1] * f_bs, "page": bs_p}
    if pl_p:
        pl_rows, pl_text = rows_of(doc[pl_p - 1]), " ".join(" ".join(t) for t in page_lines(doc[pl_p - 1]))
        f_pl = _unit_factor_to_crore(pl_text)
        np_ = find_row(pl_rows, r"^net profit(?:/)?(?: loss)?( for the (year|period))?( i ii)?$|^profit for the (year|period)$")
        if np_:
            out["pat"] = {"cur": np_[2][0] * f_pl, "prior": np_[2][1] * f_pl, "page": pl_p}
        eps = find_row(pl_rows, r"^basic$|^basic eps$")
        if eps:
            out["eps"] = {"cur": eps[2][0], "prior": eps[2][1], "page": pl_p}
        fv = find_row(pl_rows, r"^face value per share$|^face value$", need=1)
        if fv:
            out["face_value"] = fv[2][0]
    if "face_value" not in out and cap:               # the capital note: "... equity shares of Rs 1 each"
        for i in range(max(bs_p - 2, 0), min(bs_p + 40, doc.page_count)):
            txt = " ".join(" ".join(t) for t in page_lines(doc[i]))
            if re.search(r"schedule\s*1\b[^\n]{0,15}capital", txt, re.I) or re.search(r"authori[sz]ed capital", txt, re.I):
                m = _FACE_VALUE_RE.search(txt)
                if m:
                    out["face_value"] = float(m.group(1))
                    break
    return out
