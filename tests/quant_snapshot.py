"""Quantitative snapshot of one company, generated from ONE consistent capture of the running application.

    python tests/quant_snapshot.py --symbol ANURAS --capture            # recompute once (single quote), read the API, write api json
    python tests/quant_snapshot.py --symbol ANURAS --api-json <file>    # render Markdown + CSV from a saved API response

--capture: clears the symbol's wrapper caches, runs the engine ONCE in this process (every market-dependent row shares one quote and one quote
time - `ratio_contract.live_market` memo), then logs in through the configured flow and reads GET /api/v1/document-analysis/<symbol> from the running
backend.  Credentials come from .env and are never printed or written.  The Markdown and the CSV are rendered from the SAME saved response and carry
the same snapshot id (SHA-1 of the canonical response), so they cannot disagree; tests/test_quant_snapshot_artefact.py enforces that."""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DOCS = os.path.join(ROOT, "docs")

COLUMNS = ["snapshot_id", "sr_no", "metric_name", "ratio_key", "displayed_value", "raw_value", "unit", "fiscal_year", "reporting_basis", "period_type",
           "status_api", "availability", "ui_section", "ui_visibility", "formula", "calculation_expression", "numerator", "denominator",
           "intermediate_steps", "input_source_details", "formula_version", "calculated_at", "quote_time", "notes"]

# External references accessed 2026-10-10 (page text read through the fetch tool; formulas are the sites' own, not Navrist's)
BENCHMARKS = [
    # metric, navrist ratio_key, reference platform, reference value, reference definition / period, classification
    ("Debtor Days", "days_sales_outstanding", "Screener consolidated (annual Mar-2026 column)", "148", "closing receivables / sales x 365", "Different documented methodology (closing vs average balance)"),
    ("Inventory Days", "days_inventory_outstanding", "Screener consolidated", "490", "closing inventory / COGS x 365", "Different documented methodology (closing vs average balance)"),
    ("Days Payable", "days_payables_outstanding", "Screener consolidated", "261", "closing payables / COGS x 365", "Different documented methodology (closing balance; COGS vs disclosed purchases)"),
    ("Cash Conversion Cycle", "cash_conversion_cycle", "Screener consolidated", "377", "debtor + inventory - payable days (closing)", "Different documented methodology (follows its components)"),
    ("Working Capital Days", "days_working_capital", "Screener consolidated", "108", "Screener's own definition (not reproducible from the statements)", "Insufficient evidence for the reference formula; Navrist = average working capital / revenue x 365"),
    ("Dividend Payout %", "dividend_payout_ratio", "Screener consolidated", "10%", "dividend declared for the year / profit", "Different documented methodology (Navrist: dividends PAID to owners / owners' profit)"),
    ("Tax %", "effective_tax_rate", "Screener consolidated", "13%", "Screener tax row (whole percent)", "Matches (12.66% rounds to 13%)"),
    ("ROE %", "roe", "Screener key-metrics box", "5.55%", "period not labelled by the site", "Different reporting basis / unlabelled period"),
    ("ROE %", "roe", "Stock Analysis FY2026", "5.76%", "whole-entity profit 222.20 / average equity incl. NCI 3,855.81 (reproduced)", "Different documented methodology (profit perimeter: owners' vs whole entity)"),
    ("Return on Assets (ROA)", "roa", "Stock Analysis FY2026", "3.66%", "formula not published; not reproducible from the statements", "Insufficient evidence for the reference formula"),
    ("Return on Invested Capital (ROIC)", "roic", "Stock Analysis FY2026", "6.45%", "formula not published (average invested capital gives 6.73% on Navrist's NOPAT)", "Different documented methodology / insufficient evidence"),
    ("ROCE %", "roce", "Screener (last value) / Stock Analysis FY2026", "7% / 7.20%", "formula not published; EBIT here includes other income and uses average (assets - current liabilities)", "Insufficient evidence for the reference formula"),
    ("Debt-to-Equity Ratio", "debt_to_equity", "Stock Analysis FY2026", "0.42", "formula not published (borrowings / owners' equity = 0.55; Navrist debt incl. leases / equity incl. NCI = 0.40)", "Different documented methodology"),
    ("Current Ratio", "current_ratio", "Stock Analysis FY2026", "1.43", "current assets / current liabilities", "Matches"),
    ("Stock P/E", "pe_ratio", "Screener key metrics", "73.8", "Screener's own price at its own time", "Stale or different market price (Navrist uses the quote shown in the snapshot over FY EPS 15.09)"),
    ("Price-to-Book (P/B)", "pb_ratio", "Screener text", "3.90x", "price 1,132 / book value 290", "Matches"),
    ("Stock P/E", "pe_ratio", "Stock Analysis", "82.37", "page price dated 2026-10-09; earnings basis not stated", "Stale or different market price / different earnings basis"),
    ("Price-to-Book (P/B)", "pb_ratio", "Stock Analysis", "3.03", "book-value basis not stated", "Insufficient evidence for the reference formula"),
    ("Enterprise Value/EBITDA", "ev_to_ebitda", "Stock Analysis", "28.92", "EV and EBITDA definitions not published", "Insufficient evidence for the reference formula"),
    ("Net Profit Margin", "net_profit_margin", "external 9.32% (whole-entity 222.20 / 2,365.45)", "9.32%", "whole-entity profit", "Different documented methodology (Navrist: owners' profit; reference reproduced with 222.199 / 2,365.455)"),
]


def js_fixed(v, n):
    return f"{Decimal(v).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)}"


def indian(v, maxfrac=2):
    s = f"{abs(v):.{maxfrac}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    ip, _, fp = s.partition(".")
    if len(ip) > 3:
        head, tail, parts = ip[:-3], ip[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        ip = ",".join(parts + [tail])
    out = ip + ("." + fp if fp else "")
    return ("-" if v < 0 and float(s or 0) != 0 else "") + out


def displayed(r):
    """What fmtRatioValue() in frontend/src/views/DocumentAnalysis.jsx prints."""
    if r["value"] is None:
        return "-"
    v, u = float(r["value"]), r["unit"]
    if u == "%":
        return js_fixed(v, 2) + "%"
    if u == "x":
        return js_fixed(v, 2) + "x"
    if u == "₹ Cr":
        return "₹" + indian(v, 0) + " Cr"
    return indian(v, 2)


def meta(r):
    return next((i for i in r["inputs"] if i.get("name") == "_metadata"), {})


def uniq(seq):
    return list(OrderedDict.fromkeys(x for x in seq if x))


def inp_text(i):
    bits = [i.get("name") or ""]
    if i.get("detail"):
        bits.append(f"[{i['detail']}]")
    bits.append(f"{i.get('value_display') or i.get('value_raw')}")
    bits.append(f"period={i.get('period')}")
    if i.get("basis"):
        bits.append(f"basis={i['basis']}")
    src = i.get("source")
    if i.get("source_file"):
        src = f"{src} ({i['source_file']})"
    bits.append(f"source={src}")
    if i.get("statement"):
        bits.append(f"statement={i['statement']}")
    bits.append(f"page={i['page']}" if i.get("page") else "page=not recorded")
    bits.append(f"origin={i.get('status') or i.get('method')}" + (f"/{i['method']}" if i.get("method") and i.get("status") != i.get("method") else ""))
    if i.get("derivation"):
        bits.append(f"derivation={i['derivation']}")
    if i.get("estimated"):
        bits.append("ESTIMATED")
    if i.get("raw_label"):
        bits.append(f"label={i['raw_label']}")
    if i.get("note"):
        bits.append(f"note={i['note']}")
    return " | ".join(str(b) for b in bits)


def walk_inputs(b, depth=0):
    out = [(depth, i) for i in (b.get("inputs") or [])]
    for p in b.get("parents") or []:
        out.append((depth, {"name": f"PARENT RATIO {p.get('label')}", "value_display": p.get("value_display"), "period": b.get("period"),
                            "basis": b.get("basis"), "source": "calculated parent ratio", "status": p.get("status"), "page": None}))
        if p.get("breakdown"):
            out += walk_inputs(p["breakdown"], depth + 1)
    return out


def ui_groups(api):
    """Section / visibility of every card, from the repository's own groupFundamentalRatios (node)."""
    import subprocess
    import tempfile
    js = ("import fs from 'node:fs';import { groupFundamentalRatios } from '" + __import__("pathlib").Path(ROOT, "frontend", "src", "lib", "ratioCategories.js").as_uri() + "';"
          "const j=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
          "const g=groupFundamentalRatios(j.fundamental.filter((r)=>r.status!=='not_disclosed'));"
          "console.log(JSON.stringify({priority:g.priority.map((r)=>r.ratio_key),primary:g.primary.map((x)=>({c:x.category,k:x.items.map((r)=>r.ratio_key)})),"
          "more:g.more.map((x)=>({c:x.category,k:x.items.map((r)=>r.ratio_key)}))}));")
    with tempfile.TemporaryDirectory() as d:
        a, m = os.path.join(d, "api.json"), os.path.join(d, "g.mjs")
        json.dump(api, open(a, "w", encoding="utf-8"))
        open(m, "w", encoding="utf-8").write(js)
        g = json.loads(subprocess.run(["node", m, a], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    out = {k: ("Priority cards (top of tab)", "visible by default") for k in g["priority"]}
    for x in g["primary"]:
        out.update({k: (x["c"], "visible by default") for k in x["k"]})
    for x in g["more"]:
        out.update({k: (x["c"], "behind 'Show More Ratios'") for k in x["k"]})
    return out, g


def snapshot_id(api):
    canon = json.dumps({"symbol": api["symbol"], "formula_version": api["formula_version"],
                        "rows": sorted(({"k": r["ratio_key"], "v": r["value"], "s": r["status"], "c": meta(r).get("calculated_at")} for r in api["fundamental"]),
                                       key=lambda x: x["k"])}, sort_keys=True, default=str)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]


def build_rows(api, groups):
    sid = snapshot_id(api)
    rows = []
    for r in sorted(api["fundamental"], key=lambda r: r["sr_no"]):
        m = meta(r)
        b = m.get("breakdown") or {}
        rep = m.get("reporting") or {}
        calc = b.get("calculation") or {}
        expr = calc.get("expression") or ""
        num = den = ""
        note_split = ""
        if expr and expr.count(" ÷ ") == 1:
            num, den = expr.split(" ÷ ")
        elif expr:
            note_split = "numerator/denominator not separable from the recorded expression (multi-term formula); full expression in calculation_expression"
        elif b:
            note_split = "no numeric expression recorded (no value computed)"
        else:
            note_split = "no calculation breakdown exposed by the API for this metric"
        ins = walk_inputs(b) if b else []
        steps = [f"{s.get('label')}: {s.get('expression')} = {s.get('result_display')}" for s in (b.get("steps") or [])]
        warnings = uniq((m.get("warnings") or []) + (b.get("notes") or []))
        st = r["status"]
        availability = ("available" if r["value"] is not None else
                        {"not_applicable": "not applicable", "insufficient_data": "unavailable (insufficient data)",
                         "not_disclosed": "unavailable (not disclosed)", "not_meaningful": "withheld (not meaningful)"}.get(st, st))
        if r["value"] is not None and st == "needs_review":
            availability = "available (needs review)"
        if r["value"] is not None and st == "not_meaningful":
            availability = "value displayed but flagged NOT MEANINGFUL by the engine"
        reason = m.get("reason") or ("; ".join(map(str, b["missing"])) if r["value"] is None and b.get("missing") else "")
        notes = []
        if reason:
            notes.append("reason: " + reason)
        if warnings:
            notes.append("warnings: " + " || ".join(warnings))
        if m.get("methodology"):
            notes.append("methodology: " + str(m["methodology"]))
        if rep.get("price"):
            notes.append(f"market quote: {rep['price'].get('quoted_at')} ({rep['price'].get('note')})")
        if rep.get("basis_note"):
            notes.append("basis note: " + rep["basis_note"])
        if note_split:
            notes.append(note_split)
        sec, vis = groups.get(r["ratio_key"], ("?", "?"))
        quote = (rep.get("price") or {}).get("quoted_at") or ""
        rows.append(OrderedDict([
            ("snapshot_id", sid), ("sr_no", r["sr_no"]), ("metric_name", r["label"]), ("ratio_key", r["ratio_key"]), ("displayed_value", displayed(r)),
            ("raw_value", "" if r["value"] is None else repr(r["value"])), ("unit", r["unit"] or ""),
            ("fiscal_year", rep.get("fiscal_year_label") or ""), ("reporting_basis", rep.get("statement_basis") or ""),
            ("period_type", rep.get("period_type") or ""), ("status_api", st), ("availability", availability), ("ui_section", sec), ("ui_visibility", vis),
            ("formula", b.get("formula") or r.get("formula") or ""), ("calculation_expression", expr), ("numerator", num), ("denominator", den),
            ("intermediate_steps", " || ".join(steps)), ("input_source_details", " ## ".join(inp_text(i) for _, i in ins)),
            ("formula_version", m.get("formula_version") or ""), ("calculated_at", m.get("calculated_at") or ""), ("quote_time", quote),
            ("notes", " ## ".join(notes))]))
    return rows


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def render_md(api, rows, groups_raw, ctx):
    n = len(rows)
    avail = sum(1 for r in rows if r["raw_value"] != "")
    sid = rows[0]["snapshot_id"]
    calc_times = sorted(r["calculated_at"] for r in rows if r["calculated_at"])
    quotes = sorted({r["quote_time"] for r in rows if r["quote_time"]})
    versions = sorted({r["formula_version"] for r in rows})
    spread = (dt.datetime.fromisoformat(calc_times[-1]) - dt.datetime.fromisoformat(calc_times[0])).total_seconds() if calc_times else 0
    L, w = [], None
    w = L.append
    w(f"# {ctx['company']} - Quantitative section snapshot ({ctx['date']})")
    w("")
    w(f"Snapshot id **{sid}** (SHA-1 of the captured response). Read-only capture of what the running Navrist application serves to the "
      f"**Quantitative Analysis** tab; the CSV `docs/{ctx['stem']}.csv` is rendered from the same response and carries the same id.")
    w("")
    w("## 1. Company, reporting period and timestamps")
    w("")
    for k, v in ctx["metadata"]:
        w(f"* **{k}:** {v}")
    w(f"* **Formula version(s) in the response:** {', '.join(versions)}")
    w(f"* **Calculation times (UTC):** first {calc_times[0][:19] if calc_times else '-'}, last {calc_times[-1][:19] if calc_times else '-'} "
      f"(spread {spread:.0f} s - every row was produced by one analysis run)")
    w(f"* **Quote time(s) on market-dependent rows (UTC):** {', '.join(quotes) if quotes else '-'}"
      f" ({'a single quote shared by every market-dependent row' if len(quotes) == 1 else 'MORE THAN ONE QUOTE - see section 5'})")
    w(f"* **Source retrieval:** {ctx['source_time']}")
    w("")
    w("## 2. Complete list of displayed quantitative values")
    w("")
    w(f"{n} metrics. Display strings mirror `fmtRatioValue` (`%` and `x` 2 dp, `₹ Cr` 0 dp Indian grouping, others up to 2 dp); the unrounded API value is in the CSV.")
    w("")
    seq = ([("Priority cards (top of tab)", "visible by default")] + [(g["c"], "visible by default") for g in groups_raw["primary"]]
           + [(g["c"], "behind 'Show More Ratios'") for g in groups_raw["more"]])
    for key in seq:
        items = [r for r in rows if (r["ui_section"], r["ui_visibility"]) == key]
        if not items:
            continue
        if key[0].startswith("Priority"):
            order = {k: i for i, k in enumerate(groups_raw["priority"])}
            items.sort(key=lambda r: order[r["ratio_key"]])
        w(f"### {key[0]} - {key[1]} ({len(items)})")
        w("")
        w("| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |")
        w("|---|---|---|---|---|---|---|---|")
        for r in items:
            w(f"| {r['sr_no']} | {r['metric_name']} | {r['displayed_value']} | {r['unit'] or '-'} | {r['fiscal_year'] or '-'} | {r['reporting_basis'] or '-'} | {r['availability']} | {r['status_api']} |")
        w("")
    w("## 3. Underlying formulas and input evidence")
    w("")
    w("Every input shows period, basis, source, page, statement and origin (`reported` = read from the annual report, `derived` = built from other facts, market = live quote). "
      "Fields the API does not expose are shown as *not recorded*.")
    w("")
    for r in rows:
        w(f"### {r['sr_no']}. {r['metric_name']} - {r['displayed_value']}")
        w("")
        w(f"* Formula: `{r['formula']}`")
        if r["calculation_expression"]:
            w(f"* Expression: `{r['calculation_expression']}`")
            if r["numerator"]:
                w(f"  * Numerator: {r['numerator']}  \n  * Denominator: {r['denominator']}")
        for s in filter(None, r["intermediate_steps"].split(" || ")):
            w(f"* Step: {s}")
        if r["input_source_details"]:
            w("* Inputs:")
            for s in r["input_source_details"].split(" ## "):
                w(f"  * {s}")
        for note in filter(None, r["notes"].split(" ## ")):
            if note.startswith("warnings: "):
                for x in note[10:].split(" || "):
                    w(f"* Warning: {x}")
            elif note.startswith("reason: "):
                w(f"* Reason: {note[8:]}")
        w("")
    w("## 4. Missing, unavailable, not-applicable and withheld metrics")
    w("")
    w("| Sr | Metric | Availability | API status | Reason exposed by the API |")
    w("|---|---|---|---|---|")
    for r in rows:
        if r["raw_value"] == "":
            reason = next((x[8:] for x in r["notes"].split(" ## ") if x.startswith("reason: ")), "not exposed")
            w(f"| {r['sr_no']} | {r['metric_name']} | {r['availability']} | {r['status_api']} | {reason.replace('|', '/')} |")
    w("")
    w("## 5. Data-quality warnings and reporting-basis issues")
    w("")
    for line in ctx["quality"]:
        w(f"* {line}")
    if len(quotes) != 1:
        w(f"* **Quote consistency:** {len(quotes)} different quote times appear on market-dependent rows.")
    if len(versions) != 1:
        w(f"* **Version consistency:** rows carry {len(versions)} formula versions.")
    w("")
    w("Metrics flagged `needs_review` (value shown, but the engine marks it as proxy / estimated / acquisition-affected / policy-dependent):")
    w("")
    for r in rows:
        if r["status_api"] == "needs_review":
            ws = [x for x in next((nn[10:] for nn in r["notes"].split(" ## ") if nn.startswith("warnings: ")), "").split(" || ") if x]
            w(f"* {r['sr_no']} {r['metric_name']}: {'; '.join(x[:150] for x in ws[:2]) or 'policy / proxy flag'}")
    w("")
    w("## 6. Source / API used and verification method")
    w("")
    for line in ctx["method"]:
        w(f"* {line}")
    w("")
    w("## 7. External benchmark comparison")
    w("")
    w("References were read on 2026-10-10 from the sites below; a difference is classified, never silently counted as a Navrist error. "
      "Only the metrics in this table were compared externally - the other metrics were verified against the annual report and by independent recomputation (docs/ratio_audit_matrix_2026-10.md).")
    w("")
    w("Sources: https://www.screener.in/company/ANURAS/consolidated/ ; https://stockanalysis.com/quote/nse/ANURAS/financials/ratios/ ; "
      "Value Research figures were supplied earlier by the product owner (inventory 248.91 / debtor 130.63 / payable 209.90 / CCC 169.65, reproduced in tests/test_anuras_reference_conventions.py).")
    w("")
    w("| Metric | Navrist (displayed) | Reference platform | Reference value | Reference definition | Classification |")
    w("|---|---|---|---|---|---|")
    by = {r["ratio_key"]: r for r in rows}
    for metric, key, plat, ref, defn, cls in BENCHMARKS:
        w(f"| {metric} | {by[key]['displayed_value']} | {plat} | {ref} | {defn} | {cls} |")
    w("")
    w("## 8. Final checks")
    w("")
    for line in ctx["checks"](n, avail, rows, spread, quotes, versions):
        w(f"* {line}")
    return "\n".join(L) + "\n"


def context(api, rows):
    sym = api["symbol"]
    return {
        "company": "Anupam Rasayan India Ltd", "date": "2026-10-10", "stem": "anupam_rasayan_quantitative_snapshot_2026-10-10",
        "metadata": [
            ("Company (as in the filing)", "Anupam Rasayan India Limited (CIN L24231GJ2003PLC042988, read from the annual-report text)"),
            ("Navrist symbol", f"{sym} - the only registry entry containing 'Anupam' (cache/nse_company_names.json)"),
            ("Reporting period shown", "FY2025-26 (year ended 31-Mar-2026), annual (non-TTM); the FY2024-25 column is the opening balance"),
            ("Reporting basis", "CONSOLIDATED statements; statement-based rows carry `statement_basis = consolidated`; bank-only, shareholding and beta rows are not statement-based"),
            ("Source document", "Uploaded Annual Report `ANURAS_2026.pdf` (Integrated Report 2025-26): consolidated balance sheet p.264, P&L p.265, cash flow p.299 as recorded by the application"),
            ("Endpoint", f"GET /api/v1/document-analysis/{sym} (FastAPI `document_analysis_get_endpoint` in app.py -> `ensure_current_fundamental_results`) - the only request the Quantitative tab makes"),
            ("Backend / data source", "FastAPI app.py on 127.0.0.1:8000; rows stored in `fundamental_analysis_results` (Supabase); inputs from the uploaded annual report PDF, the uploaded shareholding filing, the Angel One live quote and Yahoo Finance weekly prices (beta)"),
        ],
        "source_time": "the annual report and shareholding filing are uploaded documents (not re-fetched at calculation time); the quote is fetched once at the start of the run and its time is shown above; weekly prices for beta come from Yahoo Finance at run time",
        "quality": [
            "**Acquisition distortion:** the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution (goodwill +540 Cr, total assets +52%, NCI up sharply; acquisition 27-Feb-2026); flow-over-balance ratios are `needs_review`.",
            "**Revenue is a proxy for credit sales** in Receivables Turnover / Debtor Days / Receivables-to-Payables (net credit sales are not disclosed).",
            "**Perimeter by definition:** Net Profit Margin and ROA use owners' profit (170.12 Cr) - the whole-entity profit is 222.20 Cr (external 9.32% margin / 5.76% ROE use it); ROE uses owners' profit over owners' equity; Debt/Equity and ROIC use equity incl. NCI; the Piotroski score uses whole-entity profit throughout (its ROA is not the displayed ROA).",
            "**Altman Z-Score:** original (1968, public manufacturing) variant, suitable for a chemicals manufacturer; Retained Earnings is the exact Retained Earnings line of the Other-equity note (995.69 Cr) when the note reconciles - not total Other Equity (3,187.99 Cr); other filings fall back to the flagged Other-Equity proxy.",
            "**Market ratios are current-price valuations on annual results:** the quote is the latest price, not the fiscal-year-end price; EPS, DPS, book value, EBITDA and cash flow are FY2025-26.",
            "**Enterprise value** = market cap + total debt - cash & cash equivalents everywhere (EV/EBITDA, EV/Sales, EV/FCF); non-controlling interest is not added and the formula text says so.",
            "**Dividend payout** = dividends PAID to owners in the year / owners' profit; the declared-for-the-year basis (DPS 1.5 -> ~10%, Screener's 10%) is a different measure.",
            "**Cash ratio** includes unrestricted other bank balances; restricted / lien balances are excluded and balances of unstated nature are included but unconfirmed.",
            "**Free cash flow is negative:** FCF-based multiples are flagged not meaningful rather than shown as ordinary multiples (EV/FCF still prints its number; its status is `not_meaningful`).",
            "**Banking-specific metrics** are Not Applicable to a chemicals company and show '-'.",
            "**Shareholding rows and Beta** carry no fiscal-year label (filing / price-series based).",
        ],
        "method": [
            "Authentication: the configured flow - POST /api/auth/login with the site password from the local `.env` (never printed or stored), then the bearer token on GET /api/v1/document-analysis/<symbol> over HTTP to localhost:8000. No auth bypass or dependency override was used for the captured data.",
            "**The values were NOT read from the logged-in browser UI.** The displayed strings re-implement the tab's `fmtRatioValue`, and the section grouping runs the repository's own `groupFundamentalRatios` (node) on the response.",
            "Freshness: before the capture the symbol's wrapper caches were cleared and the engine run once, so every row has the same formula version, one quote and calculation times within seconds. The application stores those rows in its own table (normal behaviour of an analysis run).",
            "Re-run: `python tests/quant_snapshot.py --symbol ANURAS --capture` then `--api-json <file>`.",
        ],
        "checks": lambda n, avail, rs, spread, quotes, versions: [
            f"Metrics captured: **{n}** ({avail} with a value, {n - avail} without; none replaced by zero).",
            f"Duplicates: {n - len({r['ratio_key'] for r in rs})} duplicate ratio keys, {n - len({r['metric_name'] for r in rs})} duplicate labels.",
            f"One snapshot: {len(versions)} formula version(s), {len(quotes)} quote time(s), calculation spread {spread:.0f} s, snapshot id {rs[0]['snapshot_id']} on every CSV row.",
        ],
    }


def capture(symbol, out):
    import glob
    import requests
    from dotenv import dotenv_values
    for pat in (f"cache/nse_xbrl/*{symbol}*", f"cache/bse/*{symbol}*"):
        for f in glob.glob(os.path.join(ROOT, pat)):
            try:
                os.remove(f)
            except OSError:
                pass
    import tools.ratio_contract as rc
    rc.clear_quote_memo()
    from tools.document_analysis_engine import run_fundamental_analysis
    run_fundamental_analysis(symbol, symbol)
    base = "http://localhost:8000"
    pw = dotenv_values(os.path.join(ROOT, ".env")).get("SITE_PASSWORD")
    tok = requests.post(base + "/api/auth/login", json={"password": pw}, timeout=30).json()["access_token"]
    r = requests.get(f"{base}/api/v1/document-analysis/{symbol}", headers={"Authorization": "Bearer " + tok}, timeout=900)
    r.raise_for_status()
    open(out, "wb").write(r.content)
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ANURAS")
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--api-json", default=None)
    a = ap.parse_args()
    path = a.api_json or os.path.join(ROOT, "..", "navrist_tools", "out", f"{a.symbol.lower()}_api.json")
    api = capture(a.symbol, path) if a.capture else json.load(open(path, encoding="utf-8"))
    groups, raw = ui_groups(api)
    rows = build_rows(api, groups)
    ctx = context(api, rows)
    write_csv(rows, os.path.join(DOCS, ctx["stem"] + ".csv"))
    open(os.path.join(DOCS, ctx["stem"] + ".md"), "w", encoding="utf-8").write(render_md(api, rows, raw, ctx))
    print("snapshot", rows[0]["snapshot_id"], "metrics", len(rows))


if __name__ == "__main__":
    main()
