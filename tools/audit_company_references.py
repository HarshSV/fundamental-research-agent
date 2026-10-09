"""Read-only audit: every database row that references a set of company
identifiers (symbols) or names. Used before removing a company record so the
blast radius (including ON DELETE CASCADE children) is known and nothing
unrelated is touched.

    venv/Scripts/python.exe tools/audit_company_references.py SYM1 SYM2 --name "prime fresh"

Writes nothing to the database.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.supabase_client import get_client  # noqa: E402

# table -> column holding the company symbol
SYMBOL_TABLES = {
    "companies": "symbol",
    "ratio_values": "symbol",
    "qualitative_values": "symbol",
    "refresh_jobs": "symbol",
    "qualitative_research_jobs": "symbol",
    "qualitative_research_runs": "symbol",
    "uploaded_documents": "symbol",
    "extracted_values": "symbol",
    "fundamental_analysis_results": "symbol",
    "chat_messages": "symbol",
    "price_eod": "symbol",
    "price_intraday": "symbol",
}


def count(sb, table, col, values):
    try:
        r = sb.table(table).select(col, count="exact").in_(col, values).limit(1).execute()
        return r.count
    except Exception as e:
        return f"n/a ({str(e)[:60]})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--name", action="append", default=[])
    a = ap.parse_args()
    syms = [s.upper() for s in a.symbols]
    sb = get_client()

    print("== rows by symbol ==")
    for t, col in SYMBOL_TABLES.items():
        print(f"{t:32} {col:8} {count(sb, t, col, syms)}")

    print("\n== companies rows (full) ==")
    rows = sb.table("companies").select("*").in_("symbol", syms).execute().data
    for r in rows:
        print(json.dumps(r, default=str))

    for nm in a.name:
        print(f"\n== companies by name ilike %{nm}% ==")
        for r in sb.table("companies").select("symbol,name,isin,bse_code,bse_scrip_code,registry_status").ilike("name", f"%{nm}%").execute().data:
            print(json.dumps(r, default=str))
        print(f"== uploaded_documents by name ilike %{nm}% ==")
        try:
            for r in sb.table("uploaded_documents").select("document_id,symbol,display_name,filename,status").ilike("display_name", f"%{nm}%").execute().data:
                print(json.dumps(r, default=str))
        except Exception as e:
            print("n/a", str(e)[:80])


if __name__ == "__main__":
    main()
