"""Multi-company breakdown audit (run by hand, real extraction on cached PDFs, no DB/network writes):

    python tests/breakdown_probe.py [SYM:FY ...]

For every contract ratio that produced a number it checks that a breakdown exists, that its calculation
reconciles with the stored value_raw, and that every input shown carries its provenance. Prints the gaps."""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratio_regression_probe as P

DEFAULT = ["ASIANPAINT:2025", "TCS:2025", "MARUTI:2025", "HDFCBANK:2025", "POONAWALLA:2025", "RELIANCE:2025",
           "BATAINDIA:2025", "HINDUNILVR:2025", "ITC:2025", "ZEEL:2025", "SUZLON:2025", "ELECTHERM:2025", "ANURAS:2025"]


def run(sym, fy):
    from tools import ratio_contract as rc
    from tools.fundamental_fact_store import get_canonical_facts
    fs = get_canonical_facts(sym, sym, fy)
    if fs.facts.get("_error"):
        return None, [("-", "-", fs.facts["_error"][:60])]
    res = rc.compute_all(fs, {"price": 100.0, "source": "regression-test"})
    gaps, n = [], 0
    for k, r in res.items():
        if r.get("value_raw") is None:
            continue
        n += 1
        b = r.get("breakdown")
        if not b:
            gaps.append((k, "no breakdown", ""))
        elif b.get("reconciles") is not True or not b.get("calculation"):
            gaps.append((k, f"reconciles={b.get('reconciles')}", "; ".join(b.get("notes") or [])[:90]))
        else:
            for i in b["inputs"]:
                if i["value_raw"] is not None and not (i.get("source") or i.get("statement")):
                    gaps.append((k, "input without provenance", i["name"]))
    return n, gaps


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    P._setup(".")
    tot_gaps = 0
    for a in (sys.argv[1:] or DEFAULT):
        sym, fy = a.split(":")
        try:
            n, gaps = run(sym, int(fy))
        except Exception as e:
            print(f"{a}: ERROR {type(e).__name__}: {e}")
            continue
        print(f"{a}: {n} numeric ratios, {len(gaps)} gaps")
        for g in gaps:
            print("    ", *g)
        tot_gaps += len(gaps)
    print("TOTAL GAPS", tot_gaps)
