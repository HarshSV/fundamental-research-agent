"""Calculation breakdown (provenance) payload for every ratio - ONE model, built from the very result the
contract just computed, never recalculated for display.

`build_breakdown(key, res, fs, deps)` is called by `ratio_contract.compute_ratio` and attaches the payload as
`res["breakdown"]`. It only READS what the calculation used:

  * the leg descriptors (`numerator`/`denominator`) carry the UNROUNDED `value_raw` the arithmetic divided
    (plus the fact they were read from, signed `parts`, or an `expr` chain for composites like market cap),
  * derived ratios carry their parents' unrounded `value_raw` (and the parents' own breakdowns, nested),
  * every leaf input is looked up in the FactSet (period, statement basis, source file/page, extraction method).

After assembling the expression it RE-EVALUATES it from the displayed raw inputs and compares with the result's
`value_raw` (`reconciles`). A breakdown that does not reconcile is flagged, never silently shown as if it did, so
"formula says one thing / calculation uses another / evidence shows a third" cannot pass unnoticed (see tests).

Schema (all numbers are plain floats; `*_display` are display strings made here so the UI never formats money):

    {"schema": 1, "version": BREAKDOWN_VERSION, "ratio_key", "status", "unit",
     "formula":      "Cost of Goods Sold ÷ Average Inventory",          # what the engine actually divides
     "definition":   "<approved methodology text>",
     "inputs":   [{"id","name","detail","fact","value_raw","value_display","unit","period","basis","source",
                   "source_file","statement","page","raw_label","method","estimated","status","note"}],
     "steps":    [{"id","label","formula","expression","result_raw","result_display","unit"}],   # intermediates
     "parents":  [{"ratio_key","label","value_raw","value_display","value_calc","status","unit","breakdown"}],
     "calculation": {"formula","expression","result_raw","result_display","multiplier"} | None,
     "result":   {"value_raw","value_display","value_calc","unit","status"},
     "reconciles": True | False | None, "missing": [...], "notes": [...], "basis", "period", "source"}
"""
import math
import re

BREAKDOWN_VERSION = 2

_BS_FACTS = {"total_assets", "total_current_assets", "total_current_liabilities", "equity", "equity_full", "cash",
             "other_bank_balances", "inventory", "receivables", "payables", "ppe", "rou_assets", "cwip", "intangibles",
             "goodwill", "net_fixed_assets_legacy", "shares_outstanding", "nci", "total_liabilities_reported",
             "total_liabilities", "retained_earnings", "lt_borrowings"}
_PL_FACTS = {"revenue", "pat", "pat_total", "pbt", "tax_expense", "finance_costs", "depreciation", "total_expenses",
             "employee_benefit_expense", "other_expenses", "eps_total", "eps_owners", "eps", "dividend_per_share"}
_CF_FACTS = {"operating_cash_flow", "capex_ppe_purchase", "capex_intangible_purchase", "capex_disposal_proceeds",
             "borrowings_repayment", "lease_repayment", "interest_paid", "dividend_paid_cf", "dividends_paid"}
_STATEMENT = {"total_debt": "Balance Sheet", **{k: "Balance Sheet" for k in _BS_FACTS}, **{k: "Statement of Profit and Loss" for k in _PL_FACTS},
              **{k: "Cash Flow Statement" for k in _CF_FACTS}}

# derived facts that really come from a note / a disclosure outside the three statements: no statement page is claimed
_DERIVED_STATEMENT = {"purchases": "Notes to the financial statements (cost of materials consumed)",
                      "dps": "Directors' Report / dividend disclosure"}

_OPS = {"working_capital": "sub", "eps_growth_rate": "growth"}     # final step is not a plain quotient
_SQRT = {"graham_number"}

_MULT_TEXT = {1e7: "1,00,00,000"}


def _F(k):
    return ("F", k)


def _C(v, text):
    return ("C", v, text)


# fact -> expression over other facts, where the stored fact is not a plain +/- tag (evaluated left-to-right,
# a nested list is a parenthesised sub-expression)
_FACT_EXPR = {
    "bvps": [_F("equity"), "×", _C(1e7, "1,00,00,000"), "÷", _F("shares_outstanding")],
    "tax_rate": [_F("tax_expense"), "÷", _F("pbt")],
    "nopat": [_F("ebit"), "×", [_C(1.0, "1"), "−", _F("tax_rate")]],
    "invested_capital": [_F("total_debt"), "+", _F("equity_full"), "−", _F("cash")],
}
_FACT_NAME = {"total_current_assets": "Total Current Assets", "total_current_liabilities": "Total Current Liabilities",
              "total_assets": "Total Assets", "pbt": "Profit Before Tax", "finance_costs": "Finance Costs",
              "ppe": "Property, Plant & Equipment", "rou_assets": "Right-of-use Assets",
              "cwip": "Capital Work-in-Progress", "intangibles": "Intangible Assets", "total_debt": "Total Debt",
              "cash": "Cash and Cash Equivalents", "operating_cash_flow": "Operating Cash Flow",
              "capex": "Capital Expenditure", "ebit": "EBIT", "depreciation": "Depreciation & Amortisation",
              "capex_ppe_purchase": "Purchase of PPE", "capex_intangible_purchase": "Purchase of Intangible Assets",
              "equity": "Owners' Equity", "equity_full": "Total Equity incl. NCI", "nci": "Non-Controlling Interest",
              "shares_outstanding": "Equity Shares Outstanding", "tax_expense": "Total Tax Expense",
              "tax_rate": "Effective Tax Rate", "revenue": "Revenue from Operations", "pat": "Profit After Tax (owners)",
              "pat_total": "Profit After Tax (whole entity)", "eps": "Basic EPS (owners)", "dps": "Dividend per Share",
              "total_liabilities": "Total Liabilities", "retained_earnings": "Retained Earnings",
              "gross_profit": "Gross Profit", "ebitda": "EBITDA", "fcf": "Free Cash Flow", "net_debt": "Net Debt",
              "nopat": "NOPAT", "invested_capital": "Invested Capital", "bvps": "Book Value per Share",
              "working_capital": "Working Capital", "other_expenses": "Other Expenses", "lt_borrowings": "Long-term Borrowings",
              "capital_employed": "Capital Employed", "net_fixed_assets": "Net Fixed Assets",
              "dividends_paid": "Dividends Paid", "receivables": "Trade Receivables", "payables": "Trade Payables",
              "inventory": "Inventory"}


# ---------------------------------------------------------------------------------------------
# formatting (display only - arithmetic always uses value_raw)
# ---------------------------------------------------------------------------------------------
def _indian(n, dp):
    neg = n < 0
    s = f"{abs(n):.{dp}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def _canon_unit(u):
    return {"cr": "₹ Cr", "INR_CRORE": "₹ Cr", "INR_PER_SHARE": "₹", "ABSOLUTE_SHARES": "shares", "RATIO": "ratio",
            None: "₹ Cr", "": ""}.get(u, u)


def fmt(v, unit, dp=None):
    """Display string for a value in `unit` (dp=None -> 2). Negatives use a true minus sign before the symbol."""
    if v is None:
        return "Not disclosed"
    if v < 0:
        return "−" + fmt(-v, unit, dp)
    u = _canon_unit(unit)
    if u == "shares":
        return _indian(v, 0)
    d = (4 if u in ("ratio", "frac") else 2) if dp is None else dp
    if u == "₹ Cr":
        return f"₹{_indian(v, d)} Cr"
    if u == "₹":
        return f"₹{_indian(v, d)}"
    if u == "%":
        return f"{v:,.{d}f}%"
    if u == "frac%":                                   # a fraction displayed as a percentage (Piotroski ratios)
        return f"{v * 100:,.{d}f}%"
    if u in ("x", "days"):
        return f"{v:,.{d}f}{'x' if u == 'x' else ' days'}"
    return f"{v:,.{d}f}"


def _close(a, b, rel=1e-9, abs_=1e-9):
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def _short(label):
    """'Average Inventory (opening + closing) ÷ 2' -> 'Average Inventory' (the full label stays on the input row)."""
    label = label or ""
    base = label.split(" = ")[0]
    keep_closing = " = " in label and base.rstrip().endswith("(closing)")
    s = re.split(r"\s+\(|\s+-\s+|\s+÷\s+2", base, maxsplit=1)[0].strip()
    return (s + (" (closing)" if keep_closing else "")) or label


def _sym(node):
    """Name of a node inside a symbolic formula. A step node keeps its own (already short) label - so an explicit
    '(closing)' survives - and a composite (contains + or −) is parenthesised so precedence is unambiguous."""
    s = node["label"] if ("step" in node or node.get("const")) else _short(node["label"])
    return f"({s})" if (" − " in s or " + " in s) else s


def _doc_label(src):
    if not src:
        return None, None
    if src.startswith("manual-upload://"):
        return "Uploaded Annual Report", src[len("manual-upload://"):] + ".pdf"
    return "Annual Report", src.rstrip("/").rsplit("/", 1)[-1] or None


def _nice(k):
    return _FACT_NAME.get(k, (k or "").replace("_", " ").title())


# ---------------------------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------------------------
class _B:
    def __init__(self, fs, res, deps, tol=1e-9):
        self.fs, self.res, self.deps, self.tol = fs, res, deps or {}, tol
        self.inputs, self.steps, self.parents, self.notes = {}, [], [], []
        self.fy = getattr(fs, "fiscal_year", None)
        self.basis = None
        if fs is not None:
            self.basis = "consolidated" if fs.selection.selected_basis == "CONSOLIDATED" else "standalone"

    # --- rollback (a decomposition that does not add up is dropped, never half-shown) ----------
    def snap(self):
        return dict(self.inputs), list(self.steps), list(self.parents), list(self.notes)

    def restore(self, s):
        self.inputs, self.steps, self.parents, self.notes = dict(s[0]), list(s[1]), list(s[2]), list(s[3])

    # --- leaves ---------------------------------------------------------------------------
    def _period(self, which):
        if self.fy is None:
            return None
        return f"FY{self.fy}" if which == "cur" else f"FY{self.fy - 1}"

    def _add_input(self, ident, **kw):
        if ident not in self.inputs:
            self.inputs[ident] = {"id": ident, **kw}
        return self.inputs[ident]

    def _page_for(self, statement):
        ex = (self.fs.extras or {}) if self.fs is not None else {}
        if statement == "Balance Sheet":
            return ex.get("bs_page")
        if statement == "Statement of Profit and Loss":
            return ex.get("pl_page")
        return None

    def leaf(self, fact_key, which="cur", label=None, unit=None, absval=False):
        f = self.fs.get(fact_key) if self.fs is not None else None
        val = None if f is None else (f.value if which == "cur" else f.prior_value)
        if absval and val is not None:
            val = abs(val)
        u = _canon_unit(unit or (f.unit if f is not None else None))
        ident = f"{fact_key}:{which}" + (":abs" if absval else "")
        src, fname = _doc_label(getattr(f, "source_document", None))
        derived = f is not None and f.extraction_method in ("derived", "document_text")
        full = label or _nice(fact_key)
        node = {"label": full, "value_raw": val, "unit": u, "input": ident}
        name = full if len(full) <= 48 else _short(full)
        stmt = _STATEMENT.get(fact_key)
        if derived:
            stmt = _DERIVED_STATEMENT.get(fact_key, stmt)
        detail = full if name != full else None
        if absval and val is not None:
            detail = (detail + " · " if detail else "") + "reported as a cash outflow (negative); its magnitude is used"
        no_page = derived and fact_key in _DERIVED_STATEMENT
        self._add_input(
            ident, name=name, **({"detail": detail} if detail else {}), fact=fact_key, value_raw=val,
            value_display=fmt(val, u), unit=u, period=self._period(which), basis=self.basis, source=src, source_file=fname,
            statement=stmt, page=(None if no_page else getattr(f, "source_page", None)),
            raw_label=getattr(f, "raw_label", None), method=getattr(f, "extraction_method", None),
            estimated=bool(getattr(f, "estimated", False)),
            status=("missing" if val is None else ("derived" if derived else "reported")),
            note=(None if val is not None else "Required input was not disclosed in the source."),
            **({"derivation": getattr(f, "source_tag", None)} if derived else {}))
        return node

    def doc_label(self):
        return _doc_label(((self.fs.extras or {}).get("source_url")) if self.fs is not None else None)[0]

    def plain(self, label, val, unit, source=None, note=None, statement=None, page=None, period="__fy__", dp=None):
        u = _canon_unit(unit)
        ident = f"x:{len(self.inputs)}:{label}"
        name = label if len(label) <= 48 else _short(label)
        self._add_input(ident, name=name, **({"detail": label} if name != label else {}), fact=None, value_raw=val,
                        value_display=fmt(val, u, dp), unit=u,
                        period=self._period("cur") if period == "__fy__" else period, basis=self.basis if period == "__fy__" else None,
                        source=source, source_file=None, statement=statement,
                        page=page if page is not None else self._page_for(statement), raw_label=None, method=None,
                        estimated=False, status="missing" if val is None else "reported", note=note)
        return {"label": label, "value_raw": val, "unit": u, "input": ident, **({"dp": dp} if dp else {})}

    def const(self, v, text):
        return {"label": text, "value_raw": v, "unit": "", "const": True, "text": text}

    # --- steps ----------------------------------------------------------------------------
    def _step(self, label, formula, expression, raw, unit, *, dp=None):
        sid = f"s{len(self.steps) + 1}"
        u = _canon_unit(unit)
        self.steps.append({"id": sid, "label": label, "formula": formula, "expression": expression,
                           "result_raw": raw, "result_display": fmt(raw, u, dp), "unit": u})
        return {"label": label, "value_raw": raw, "unit": u, "step": sid, **({"dp": dp} if dp else {})}

    @staticmethod
    def _disp(n, dp=None):
        if n.get("const"):
            return n["text"]
        return fmt(n["value_raw"], n["unit"], dp if dp is not None else n.get("dp"))

    def combine(self, label, terms, unit=None):
        """terms = [(node, sign)] -> a sum/difference step; returns the step's node (value from the terms)."""
        total, f_parts, e_parts = 0.0, [], []
        for i, (n, sg) in enumerate(terms):
            if n["value_raw"] is None:
                return None
            total += sg * n["value_raw"]
            sep = "" if (i == 0 and sg > 0) else (" + " if sg > 0 else (" − " if i else "−"))
            f_parts.append(sep + _sym(n))
            shown = self._disp(n)
            if i > 0 and n["value_raw"] < 0:
                shown = f"({shown})"
            e_parts.append(sep + shown)
        return self._step(label, "".join(f_parts), "".join(e_parts), total, unit or terms[0][0]["unit"])

    def chain(self, label, items, unit, dp=None):
        """items = [node, op, node, op, node ...] evaluated left-to-right (ops: + − × ÷)."""
        nodes, ops = items[0::2], items[1::2]
        if any(n["value_raw"] is None for n in nodes):
            return None
        acc = nodes[0]["value_raw"]
        f_parts, e_parts = [_sym(nodes[0])], [self._disp(nodes[0])]
        for op, n in zip(ops, nodes[1:]):
            v = n["value_raw"]
            if op == "÷" and not v:
                return None
            acc = {"+": acc + v, "−": acc - v, "×": acc * v, "÷": (acc / v if v else None)}[op]
            f_parts.append(f" {op} {_sym(n)}")
            shown = self._disp(n)
            if op in ("×", "÷", "−") and v < 0 and not n.get("const"):
                shown = f"({shown})"
            e_parts.append(f" {op} {shown}")
        return self._step(label, "".join(f_parts), "".join(e_parts), acc, unit, dp=dp)

    def average(self, label, prior, cur):
        if prior["value_raw"] is None or cur["value_raw"] is None:
            return None
        raw = (prior["value_raw"] + cur["value_raw"]) / 2.0
        return self._step(label, f"({prior['label']} + {cur['label']}) ÷ 2",
                          f"({self._disp(prior)} + {self._disp(cur)}) ÷ 2", raw, cur["unit"])

    # --- facts -> nodes (expanding derived facts into what they were really built from) ---------
    def _tokens(self, tokens, which):
        items = []
        for t in tokens:
            if isinstance(t, str):
                items.append(t)
            elif isinstance(t, list):
                sub = self._tokens(t, which)
                n = self.chain("(" + " ".join(x if isinstance(x, str) else x["label"] for x in sub) + ")", sub, "ratio", dp=4)
                if n is None:
                    return None
                items.append(n)
            elif t[0] == "F":
                n = self.fact_node(t[1], which, _nice(t[1]))
                if n is None or n["value_raw"] is None:
                    return None
                items.append(n)
            else:
                items.append(self.const(t[1], t[2]))
        return items

    def _debt_node(self, f, label):
        ex = (self.fs.extras or {})
        raw = ex.get("debt_components_raw")
        if not raw:
            return None
        terms = [(self.plain("Borrowings (long-term + short-term + current maturities)", raw["borrowings"], "₹ Cr",
                             source=self.doc_label(), statement="Balance Sheet"), 1)]
        if raw.get("leases_included") and raw.get("leases") is not None:
            terms.append((self.plain("Lease liabilities (non-current + current)", raw["leases"], "₹ Cr",
                                     source=self.doc_label(), statement="Balance Sheet"), 1))
        elif raw.get("lease_status") == "not_found":
            self.notes.append("Lease liabilities were not found on the balance sheet, so none are included in Total Debt.")
        if raw.get("ofl_evaluated") and raw.get("ofl"):
            terms.append((self.plain("Other financial liabilities (debt-like, qualifying)", raw["ofl"], "₹ Cr",
                                     source=self.doc_label(), statement="Balance Sheet"), 1))
        node = self.combine(_short(label), terms, "₹ Cr")
        if node is None or abs(node["value_raw"] - f.value) > 0.006:
            return None
        # the extractor rounds Total Debt to 2 decimals before any ratio uses it - the USED value is shown
        st = self.steps[-1]
        st["result_raw"], st["result_display"] = f.value, fmt(f.value, "₹ Cr")
        node["value_raw"] = f.value
        return node

    def fact_node(self, fact_key, which="cur", label=None):
        f = self.fs.get(fact_key) if self.fs is not None else None
        label = label or _nice(fact_key)
        if f is None or f.extraction_method != "derived":
            return self.leaf(fact_key, which, label)
        want = f.value if which == "cur" else f.prior_value
        if want is None:
            return self.leaf(fact_key, which, label)
        snap = self.snap()
        if fact_key == "total_debt" and which == "cur":
            n = self._debt_node(f, label)
            if n is not None:
                return n
            self.restore(snap)
            return self.leaf(fact_key, which, label)
        if fact_key in _FACT_EXPR:
            items = self._tokens(_FACT_EXPR[fact_key], which)
            if items is not None:
                u = {"bvps": "₹", "tax_rate": "ratio"}.get(fact_key, "₹ Cr")
                n = self.chain(_short(label), items, u)
                if n is not None and _close(n["value_raw"], want, 1e-7):
                    return n
            self.restore(snap)
            return self.leaf(fact_key, which, label)
        tag = f.source_tag or ""
        if not re.fullmatch(r"[a-z_]+([+\-][a-z_]+)+", tag):
            return self.leaf(fact_key, which, label)
        toks = re.findall(r"([+\-]?)([a-z_]+)", tag)
        if any(self.fs.get(k) is None for _, k in toks):
            return self.leaf(fact_key, which, label)
        for use_abs in (False, True):             # cash-flow outflows are stored negative; capex adds their magnitudes
            terms = []
            for sg, k in toks:
                n = self.fact_node(k, which, _nice(k)) if not use_abs else self.leaf(k, which, _nice(k), absval=True)
                terms.append((n, -1 if sg == "-" else 1))
            got = None if any(n["value_raw"] is None for n, _ in terms) else sum(sg * n["value_raw"] for n, sg in terms)
            if got is not None and _close(want, got, 1e-7):
                return self.combine(_short(label), terms, "₹ Cr")
            self.restore(snap)
        return self.leaf(fact_key, which, label)

    # --- legs -> nodes --------------------------------------------------------------------
    def _parent_node(self, d):
        pk = d.get("parent_key")
        p = self.deps.get(pk)
        if p is None or p.get("value_raw") is None:
            return None
        pu = d.get("unit") or p.get("unit") or "x"
        self.parents.append({"ratio_key": pk, "label": p.get("label") or pk, "value_raw": p["value_raw"], "unit": _canon_unit(pu),
                             "value_display": fmt(p["value_raw"], pu, 2), "value_calc": fmt(p["value_raw"], pu, 4),
                             "status": p.get("status"), "breakdown": p.get("breakdown")})
        return {"label": p.get("label") or pk, "value_raw": p["value_raw"], "unit": _canon_unit(pu), "dp": 4, "parent": pk}

    def leg_node(self, d):
        if not d:
            return None
        label = d.get("label") or ""
        raw = d.get("value_raw")
        fact = d.get("fact")
        f = self.fs.get(fact) if (fact and self.fs is not None) else None
        unit = d["unit"] if d.get("unit") is not None else ((f.unit if f is not None else None) or "₹ Cr")
        which = d.get("which", "cur")
        if raw is None and d.get("value_cr") is not None:
            raw = d["value_cr"]                              # legacy rounded leg - flagged
            self.notes.append(f"{_short(label)} is available only at 2-decimal precision for this ratio.")
        kind = d.get("kind")
        if kind == "market":
            return self.plain(label, raw, unit, source=d.get("source"), period="Live quote")
        if kind == "parent":
            n = self._parent_node(d)
            if n is not None and _close(n["value_raw"], raw, 1e-9):
                return n
        snap = self.snap()
        if d.get("expr"):
            items = []
            for t in d["expr"]:
                if isinstance(t, str):
                    items.append(t)
                elif t.get("const") is not None and "label" not in t:
                    items.append(self.const(t["const"], t["text"]))
                else:
                    items.append(self.leg_node(t))
            if all(i is not None for i in items):
                n = self.chain(_short(label), items, d["unit"] if d.get("unit") is not None else "₹ Cr")
                if n is not None and _close(n["value_raw"], raw, 1e-7):
                    return n
            self.restore(snap)
        parts = d.get("parts")
        if parts:
            tol = d.get("parts_tol")
            terms = []
            for p in parts:
                pl = p.get("label")
                n = None
                if p.get("leg"):
                    n = self.leg_node(p["leg"])
                elif p.get("fact"):
                    n = self.leaf(p["fact"], "cur", pl)
                    if n["value_raw"] is None or not _close(n["value_raw"], p["value_raw"], 1e-7):
                        self.inputs.pop(n["input"], None)
                        n = None
                if n is None:
                    n = self.plain(pl, p["value_raw"], unit, source=p.get("source") or self.doc_label(), note=p.get("note"),
                                   statement=p.get("statement"), page=p.get("page"))
                terms.append((n, p.get("sign", 1)))
            node = self.combine(_short(label), terms, unit)
            if node is not None:
                if _close(node["value_raw"], raw, 1e-7):
                    return node
                if tol and abs(node["value_raw"] - raw) <= tol:       # extractor rounded the total to 2dp: show what was USED
                    st = self.steps[-1]
                    st["result_raw"], st["result_display"] = raw, fmt(raw, node["unit"])
                    node["value_raw"] = raw
                    return node
            self.restore(snap)                                       # parts did not add up to the used value
        if fact and f is not None:
            if d.get("averaged"):
                short = _short(label).replace("Average ", "")
                prior = self.fact_node(fact, "prior", f"{self._period('prior')} {short}")
                cur = self.fact_node(fact, "cur", f"{self._period('cur')} {short}")
                node = self.average(_short(label), prior, cur)
                if node is not None and _close(node["value_raw"], raw, 1e-7):
                    return node
                self.restore(snap)
            else:
                n = self.fact_node(fact, which, label)
                if n["value_raw"] is not None and _close(n["value_raw"], raw, 1e-7):
                    if "prior-year unavailable" in label:
                        self.notes.append("Prior-year balance unavailable: the closing balance was used instead of an average.")
                    return n
                self.restore(snap)
        # a value we cannot trace to a statement fact: still show exactly what was used, with no invented source
        return self.plain(label, raw, unit, source=d.get("source"), dp=d.get("dp"), statement=d.get("statement"),
                          page=d.get("page"), note=d.get("note"))


# ---------------------------------------------------------------------------------------------
# derived ratios: left-to-right token sequences over their parents' UNROUNDED values
# ---------------------------------------------------------------------------------------------
_PARENTS_EXPR = {
    "days_inventory_outstanding": [("const", 365.0, "365"), "÷", ("parent", "inventory_turnover")],
    "days_sales_outstanding": [("const", 365.0, "365"), "÷", ("parent", "receivables_turnover")],
    "days_payables_outstanding": [("const", 365.0, "365"), "÷", ("parent", "payables_turnover")],
    "cash_conversion_cycle": [("parent", "days_sales_outstanding"), "+", ("parent", "days_inventory_outstanding"), "−",
                              ("parent", "days_payables_outstanding")],
    "retention_ratio": [("const", 100.0, "100"), "−", ("parent", "dividend_payout_ratio")],
    "sustainable_growth_rate": [("parent", "roe"), "×", ("parent", "retention_ratio"), "÷", ("const", 100.0, "100")],
}


def _eval_tokens(vals, ops):
    acc = vals[0]
    for op, v in zip(ops, vals[1:]):
        acc = {"+": acc + v, "−": acc - v, "×": acc * v, "÷": (acc / v if v else None)}[op]
        if acc is None:
            return None
    return acc


def _build_derived(b, key, res):
    seq = _PARENTS_EXPR[key]
    vals, f_parts, e_parts, ops = [], [], [], []
    for t in seq:
        if isinstance(t, str):
            ops.append(t)
            f_parts.append(f" {t} ")
            e_parts.append(f" {t} ")
            continue
        if t[0] == "const":
            vals.append(t[1])
            f_parts.append(t[2])
            e_parts.append(t[2])
        else:
            p = b.deps.get(t[1])
            label = (p or {}).get("label") or t[1]
            pv = (p or {}).get("value_raw")
            pu = (p or {}).get("unit") or "x"
            if p is not None:
                b.parents.append({"ratio_key": t[1], "label": label, "value_raw": pv, "unit": _canon_unit(pu),
                                  "value_display": fmt(pv, pu, 2), "value_calc": fmt(pv, pu, 4),
                                  "status": p.get("status"), "breakdown": p.get("breakdown")})
            vals.append(pv)
            f_parts.append(label)
            e_parts.append(fmt(pv, "", 4))
    if any(v is None for v in vals):
        return None
    out = _eval_tokens(vals, ops)
    return {"formula": "".join(f_parts), "expression": "".join(e_parts), "value": out, "mult": 1.0}


# ---------------------------------------------------------------------------------------------
# num / den ratios
# ---------------------------------------------------------------------------------------------
def _mult_suffix(m):
    return _MULT_TEXT.get(m) or f"{m:g}"


def _build_two_leg(b, key, res):
    nd, dd = res.get("numerator"), res.get("denominator")
    nn, dn = b.leg_node(nd), b.leg_node(dd)
    if nn is None or dn is None or nn["value_raw"] is None or dn["value_raw"] is None:
        return None
    nv, dv = nn["value_raw"], dn["value_raw"]
    raw = res.get("value_raw")
    op = _OPS.get(key)
    if op == "sub":
        return {"formula": f"{_sym(nn)} − {_sym(dn)}", "expression": f"{b._disp(nn)} − {b._disp(dn)}", "value": nv - dv, "mult": 1.0}
    if op == "growth":
        return {"formula": f"({_sym(nn)} {b._period('cur')} ÷ {_sym(dn)} {b._period('prior')} − 1) × 100"
                if b.fy else f"({_sym(nn)} ÷ {_sym(dn)} − 1) × 100",
                "expression": f"({b._disp(nn)} ÷ {b._disp(dn)} − 1) × 100", "value": (nv / dv - 1) * 100 if dv else None, "mult": 100.0}
    mult = None
    for m in (1.0, 100.0, 365.0, 1e7):
        if dv and raw is not None and _close(nv / dv * m, raw, b.tol):
            mult = m
            break
    if mult is None:
        if raw is not None:
            return {"formula": f"{_sym(nn)} ÷ {_sym(dn)}", "expression": None, "value": None, "mult": None, "unreconciled": True}
        mult = 100.0 if _canon_unit(res.get("unit")) == "%" else 1.0       # withheld result: show the arithmetic only
    sym = f"{_sym(nn)} ÷ {_sym(dn)}"
    exp = f"{b._disp(nn)} ÷ {b._disp(dn)}"
    if mult != 1.0:
        sym, exp = f"({sym}) × {_mult_suffix(mult)}", f"({exp}) × {_mult_suffix(mult)}"
    return {"formula": sym, "expression": exp, "value": (nv / dv * mult) if dv else None, "mult": mult}


def _build_single(b, key, res):
    """One composite leg is the whole ratio (Free Cash Flow, Graham Number)."""
    node = b.leg_node(res.get("numerator"))
    if node is None or node["value_raw"] is None:
        return None
    if key in _SQRT:
        step = next((s for s in b.steps if s["id"] == node.get("step")), None)
        inner = b._disp(node, 4)
        return {"formula": f"√({step['formula'] if step else _sym(node)})",
                "expression": f"√({inner})", "value": math.sqrt(node["value_raw"]), "mult": 1.0}
    step = next((s for s in b.steps if s["id"] == node.get("step")), None)
    if step is None:
        return {"formula": _sym(node), "expression": b._disp(node), "value": node["value_raw"], "mult": 1.0}
    b.steps.remove(step)                                    # it IS the calculation - not an intermediate
    return {"formula": step["formula"], "expression": step["expression"], "value": step["result_raw"], "mult": 1.0}


# ---------------------------------------------------------------------------------------------
# composite scores
# ---------------------------------------------------------------------------------------------
def _mcap_node(b, price, source):
    p = b.plain("Market price", price, "₹", source=source, period="Live quote")
    sh = b.leaf("shares_outstanding", "cur", "Equity Shares Outstanding", unit="shares")
    return b.chain("Market Capitalisation", [p, "×", sh, "÷", b.const(1e7, "1,00,00,000")], "₹ Cr")


def _build_altman(b, key, res):
    mp = res.get("market_price") or {}
    if mp.get("value") is None:
        return None
    wc = b.fact_node("working_capital", "cur", "Working Capital")
    ta = b.leaf("total_assets", "cur", "Total Assets")
    _ref = b.fs.get("retained_earnings") if b.fs is not None else None
    re_ = b.leaf("retained_earnings", "cur", "Retained Earnings (Other-equity note)" if _ref is not None and (_ref.source_tag or "") == "retained_earnings(note)"
                 else "Retained Earnings (Other Equity proxy)")
    ebit = b.fact_node("ebit", "cur", "EBIT")
    tl = b.leaf("total_liabilities", "cur", "Total Liabilities")
    rev = b.leaf("net_sales", "cur", "Sales (Net Sales)")
    mc = _mcap_node(b, mp["value"], mp.get("source"))
    if mc is None:
        return None
    terms = [(1.2, wc, ta), (1.4, re_, ta), (3.3, ebit, ta), (0.6, mc, tl), (1.0, rev, ta)]
    total, nodes = 0.0, []
    for coef, a, d in terms:
        if a["value_raw"] is None or not d["value_raw"]:
            return None
        v = coef * a["value_raw"] / d["value_raw"]
        total += v
        nodes.append(b._step(f"{coef:g} × ({_short(a['label'])} ÷ {_short(d['label'])})", f"{coef:g} × ({_short(a['label'])} ÷ {_short(d['label'])})",
                             f"{coef:g} × ({b._disp(a)} ÷ {b._disp(d)})", v, "ratio", dp=4))
    expr = " + ".join(fmt(n["value_raw"], "ratio", 4) for n in nodes)
    return {"formula": "1.2×(WC ÷ TA) + 1.4×(RE ÷ TA) + 3.3×(EBIT ÷ TA) + 0.6×(Market Cap ÷ TL) + 1.0×(Sales ÷ TA)",
            "expression": expr, "value": sum(n["value_raw"] for n in nodes), "mult": 1.0}


def _ratio_side(b, spec, which):
    n = b.fact_node(spec["num"], which, _nice(spec["num"]))
    d = b.fact_node(spec["den"], which, _nice(spec["den"]))
    return n, d


def _build_piotroski(b, key, res):
    tests = res.get("tests") or []
    passed_list = []
    for t in tests:
        spec = t.get("spec")
        if not t.get("applicable") or not spec:
            b._step(t["name"], t["name"], t.get("detail") or "Not evaluated", None, "")
            b.steps[-1]["result_display"] = "Not evaluated"
            continue
        sp, expr = spec["type"], ""
        ok = bool(t["passed"])
        if sp == "ratio":
            (n1, d1), (n0, d0) = _ratio_side(b, spec, "cur"), _ratio_side(b, spec, "prior")
            u = spec["unit"]
            cur = f"{b._disp(n1)} ÷ {b._disp(d1)} = {fmt(spec['cur'], u)}"
            if spec["vs"] == "zero":
                expr = f"{spec['label'].split(' = ')[0]} {cur} {spec['op']} 0"
            else:
                prior = f"{b._disp(n0)} ÷ {b._disp(d0)} = {fmt(spec['prior'], u)}"
                expr = f"{b._period('cur')}: {cur}  {spec['op']}  {b._period('prior')}: {prior}"
            for nn, dd, v in ((n1, d1, spec["cur"]), (n0, d0, spec["prior"])):
                if nn["value_raw"] is not None and dd["value_raw"] and not _close(nn["value_raw"] / dd["value_raw"], v, 1e-9):
                    b.notes.append(f"{t['name']}: the displayed inputs do not reproduce the ratio exactly.")
        elif sp == "facts":
            l = b.fact_node(spec["lhs"], "cur", _nice(spec["lhs"]))
            if spec.get("rhs"):
                r = b.fact_node(spec["rhs"], "cur", _nice(spec["rhs"]))
                expr = f"{_nice(spec['lhs'])} {b._disp(l)} {spec['op']} {_nice(spec['rhs'])} {b._disp(r)}"
            else:
                expr = f"{_nice(spec['lhs'])} {b._disp(l)} {spec['op']} 0"
        elif sp == "dilution":
            s1 = b.leaf("shares_outstanding", "cur", "Equity Shares Outstanding", unit="shares")
            s0 = b.leaf("shares_outstanding", "prior", "Equity Shares Outstanding", unit="shares")
            expr = (f"{b._period('cur')}: {b._disp(s1)} shares ≤ {b._period('prior')}: {b._disp(s0)} × 1.001 "
                    f"= {_indian(spec['limit'], 0)}")
        passed_list.append(1 if ok else 0)
        b._step(t["name"], t["name"], expr, 1.0 if ok else 0.0, "")
        b.steps[-1]["result_display"] = "Pass (1)" if ok else "Fail (0)"
    if res.get("value_raw") is None:
        return None
    score = sum(passed_list)
    return {"formula": "F-Score = number of the 9 tests passed (each 1 point)", "expression": " + ".join(str(x) for x in passed_list),
            "value": float(score), "mult": 1.0, "display": f"{score} of 9"}


def _build_beneish(b, key, res):
    vr = res.get("variables_raw")
    if not vr:
        return None
    lk = res.get("leverage_fact") or "total_debt"

    P, Cu = "prior", "cur"
    # facts for both years
    f = {}
    for k in ("receivables", "net_sales", "gross_profit", "total_current_assets", "ppe", "total_assets", "depreciation",
              "other_expenses", "total_current_liabilities"):
        f[k] = (b.fact_node(k, Cu, _nice(k)), b.fact_node(k, P, _nice(k)))
    f["debt"] = (b.fact_node(lk, Cu, _nice(lk)), b.fact_node(lk, P, _nice(lk)))
    pt = b.fact_node("pat_total", Cu, "Profit After Tax (whole entity)")
    ocf = b.fact_node("operating_cash_flow", Cu, "Operating Cash Flow")

    def D(k, i):
        return b._disp(f[k][i])

    def V(k, i):
        return f[k][i]["value_raw"]
    defs = {
        "DSRI": ("(Receivables ÷ Revenue) this year ÷ prior year",
                 lambda: (V("receivables", 0) / V("net_sales", 0)) / (V("receivables", 1) / V("net_sales", 1)),
                 lambda: f"({D('receivables', 0)} ÷ {D('net_sales', 0)}) ÷ ({D('receivables', 1)} ÷ {D('net_sales', 1)})"),
        "GMI": ("(Gross Profit ÷ Revenue) prior year ÷ this year",
                lambda: (V("gross_profit", 1) / V("net_sales", 1)) / (V("gross_profit", 0) / V("net_sales", 0)),
                lambda: f"({D('gross_profit', 1)} ÷ {D('net_sales', 1)}) ÷ ({D('gross_profit', 0)} ÷ {D('net_sales', 0)})"),
        "AQI": ("(1 − (Current Assets + PPE) ÷ Total Assets) this year ÷ prior year",
                lambda: (1 - (V("total_current_assets", 0) + V("ppe", 0)) / V("total_assets", 0)) /
                (1 - (V("total_current_assets", 1) + V("ppe", 1)) / V("total_assets", 1)),
                lambda: f"(1 − ({D('total_current_assets', 0)} + {D('ppe', 0)}) ÷ {D('total_assets', 0)}) ÷ "
                        f"(1 − ({D('total_current_assets', 1)} + {D('ppe', 1)}) ÷ {D('total_assets', 1)})"),
        "SGI": ("Revenue this year ÷ prior year", lambda: V("net_sales", 0) / V("net_sales", 1),
                lambda: f"{D('net_sales', 0)} ÷ {D('net_sales', 1)}"),
        "DEPI": ("(Dep ÷ (PPE + Dep)) prior year ÷ this year",
                 lambda: (V("depreciation", 1) / (V("ppe", 1) + V("depreciation", 1))) /
                 (V("depreciation", 0) / (V("ppe", 0) + V("depreciation", 0))),
                 lambda: f"({D('depreciation', 1)} ÷ ({D('ppe', 1)} + {D('depreciation', 1)})) ÷ "
                         f"({D('depreciation', 0)} ÷ ({D('ppe', 0)} + {D('depreciation', 0)}))"),
        "SGAI": ("(Other Expenses ÷ Revenue) this year ÷ prior year (Other Expenses = SG&A proxy)",
                 lambda: (V("other_expenses", 0) / V("net_sales", 0)) / (V("other_expenses", 1) / V("net_sales", 1)),
                 lambda: f"({D('other_expenses', 0)} ÷ {D('net_sales', 0)}) ÷ ({D('other_expenses', 1)} ÷ {D('net_sales', 1)})"),
        "TATA": ("(Net Profit − Operating Cash Flow) ÷ Total Assets",
                 lambda: (pt["value_raw"] - ocf["value_raw"]) / V("total_assets", 0),
                 lambda: f"({b._disp(pt)} − {b._disp(ocf)}) ÷ {D('total_assets', 0)}"),
        "LVGI": ("((Debt + Current Liabilities) ÷ Total Assets) this year ÷ prior year",
                 lambda: ((V("debt", 0) + V("total_current_liabilities", 0)) / V("total_assets", 0)) /
                 ((V("debt", 1) + V("total_current_liabilities", 1)) / V("total_assets", 1)),
                 lambda: f"(({D('debt', 0)} + {D('total_current_liabilities', 0)}) ÷ {D('total_assets', 0)}) ÷ "
                         f"(({D('debt', 1)} + {D('total_current_liabilities', 1)}) ÷ {D('total_assets', 1)})"),
    }
    for name, (ftxt, fn, ex) in defs.items():
        val = fn()
        if not _close(val, vr[name], 1e-9):
            b.notes.append(f"{name}: the displayed inputs do not reproduce the index exactly.")
        b._step(name, ftxt, ex(), val, "ratio", dp=4)
    coef = (("DSRI", 0.92), ("GMI", 0.528), ("AQI", 0.404), ("SGI", 0.892), ("DEPI", 0.115), ("SGAI", -0.172), ("TATA", 4.679),
            ("LVGI", -0.327))
    m = -4.84
    parts = ["−4.84"]
    for name, c in coef:
        m = m + c * vr[name] if c > 0 else m - (-c) * vr[name]
        iv = f"{vr[name]:.4f}" if vr[name] >= 0 else f"(−{abs(vr[name]):.4f})"
        parts.append(f" {'+' if c > 0 else '−'} {abs(c):g} × {iv}")
    return {"formula": "M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI",
            "expression": "".join(parts), "value": m, "mult": 1.0}


_CUSTOM = {"altman_z_score": _build_altman, "piotroski_f_score": _build_piotroski, "beneish_m_score": _build_beneish}


# ---------------------------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------------------------
def build_breakdown(key, res, fs, deps=None, tol=1e-9, fy=None, basis=None):
    b = _B(fs, res, deps, tol)
    if fy is not None:
        b.fy = fy
    if basis is not None:
        b.basis = basis
    unit = _canon_unit(res.get("unit"))
    raw = res.get("value_raw")
    status = res.get("status")
    out = {"schema": 1, "version": BREAKDOWN_VERSION, "ratio_key": key, "status": status, "unit": unit,
           "formula": None, "definition": res.get("methodology"), "inputs": [], "steps": [], "parents": [],
           "calculation": None, "result": {"value_raw": raw, "value_display": fmt(raw, unit) if raw is not None else None,
                                           "value_calc": fmt(raw, unit, 4) if raw is not None else None,
                                           "unit": unit, "status": status},
           "reconciles": None, "missing": [], "notes": [], "basis": b.basis,
           "period": f"FY{b.fy}" if b.fy else None, "source": None}
    calc = None
    try:
        if key in _PARENTS_EXPR:
            calc = _build_derived(b, key, res)
        elif key in _CUSTOM:
            calc = _CUSTOM[key](b, key, res)
        elif res.get("numerator") and res.get("denominator"):
            calc = _build_two_leg(b, key, res)
        elif res.get("numerator"):
            calc = _build_single(b, key, res)
    except Exception as e:                                         # a display problem must never break the ratio
        out["notes"].append(f"Calculation breakdown could not be assembled ({type(e).__name__}: {e}).")
        calc = None

    # unavailable / withheld results: list every input the ratio needs, honestly
    if not b.inputs and not b.parents:
        for i in res.get("inputs") or []:
            if i.get("fact"):
                b.leaf(i["fact"], "cur", _nice(i["fact"]))
    out["missing"] = [i["name"] for i in b.inputs.values() if i["value_raw"] is None]
    if calc:
        out["formula"] = calc["formula"]
        disp = calc.get("display")
        if calc.get("unreconciled"):
            out["reconciles"] = False
        elif raw is not None and calc.get("value") is not None:
            out["reconciles"] = _close(calc["value"], raw, b.tol)
            if out["reconciles"]:
                out["calculation"] = {"formula": calc["formula"], "expression": calc["expression"], "result_raw": raw,
                                      "result_display": disp or fmt(raw, unit), "multiplier": calc.get("mult")}
                if disp:
                    out["result"]["value_display"] = disp
                    out["result"]["value_calc"] = disp
        elif raw is None and calc.get("expression"):
            out["calculation"] = {"formula": calc["formula"], "expression": calc["expression"], "result_raw": None,
                                  "result_display": None, "multiplier": calc.get("mult")}
        if out["reconciles"] is False:
            out["notes"].append("The shown inputs do not reproduce the stored result exactly; treat this breakdown with caution.")
    if out["formula"] is None:
        out["formula"] = res.get("formula")
    out["inputs"] = list(b.inputs.values())
    out["steps"] = b.steps
    out["parents"] = b.parents
    out["notes"] = list(dict.fromkeys(out["notes"] + b.notes))
    if res.get("reason") and raw is None:
        out["reason"] = res["reason"]
    if out["missing"]:
        out["missing_message"] = "Required input was not disclosed in the source."
    src = [x for x in (b.fy and f"FY{b.fy}", b.basis and b.basis.capitalize()) if x]
    pages = sorted({i["page"] for i in out["inputs"] if i.get("page")})
    doc = next((i["source"] for i in out["inputs"] if i.get("source") and i.get("fact")), None) or \
        next((i["source"] for i in out["inputs"] if i.get("source") and not str(i["source"]).startswith("Live")), None)
    out["source"] = " ".join(src) + (f" · {doc}" if doc else "") + (f", p.{', '.join(str(p) for p in pages)}" if pages else "") \
        if (src or doc) else None
    return out


def legacy_breakdown(key, out, formula=None, fy=None, basis=None):
    """Breakdown for providers that hand back the legacy `numerator`/`denominator` shape (the dedicated bank module).
    Legs that carry `value_raw` reconcile exactly; a leg available only as a rounded `value_cr` is flagged and reconciled
    within its rounding error. A ratio the bank discloses directly is a numerator-only leg (its own printed value)."""
    n, d = out.get("numerator"), out.get("denominator")
    if not n:
        return None
    res = {"numerator": n, "denominator": d,
           "value_raw": out.get("value_raw") if out.get("value_raw") is not None else out.get("value"),
           "unit": out.get("unit"), "status": out.get("status"), "methodology": out.get("methodology") or out.get("note"),
           "reason": out.get("reason"), "formula": formula}
    exact = all(x is None or x.get("value_raw") is not None for x in (n, d))
    fs = None
    bd = build_breakdown(key, res, fs, None, tol=1e-9 if exact else 5e-3, fy=fy, basis=basis)
    bd["source"] = (out.get("sources") or [{}])[0].get("label") if out.get("sources") else bd.get("source")
    return bd
