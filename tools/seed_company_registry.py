"""
Seeds `companies` with EVERY NSE-listed symbol (via app.py's own
`load_scrip_master_async()` - same source the live dashboard's autocomplete
uses) and, for each one, resolves its BSE scrip code and finds the actual
Annual Report PDF it will be extracted from - the "source document" the
user explicitly asked to have recorded before any ratio precompute runs.

This does NOT compute any ratios - it only answers "does this company
resolve to a real BSE filing, and which PDF/year would we use." That makes
it fast to run to completion (one BSE lookup per company, not 21x), and it
gives a genuinely useful company-level health signal on its own: any
company with registry_status != 'resolved' will fail EVERY ratio later, so
this surfaces that gap up front instead of only discovering it 21 ratios
deep into the precompute run.

Resumable: skips companies whose companies.registry_status is already
'resolved' unless --force is passed, so it's safe to stop/restart.
"""

import sys
import time

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools.annual_report_financials import list_annual_report_years, _find_annual_report_pdf
from tools.bse_scraper import _resolve_scrip_code


def seed_one(sb, symbol, name):
    try:
        code = _resolve_scrip_code(symbol, name)
        if not code:
            row = {
                "symbol": symbol, "name": name,
                "registry_status": "no_scrip_code",
                "registry_error": "Could not resolve a BSE scrip code for this symbol/name.",
                "registry_updated_at": "now()",
            }
            sb.table("companies").upsert(row).execute()
            return "no_scrip_code"

        years = list_annual_report_years(symbol, name) or []
        if not years:
            row = {
                "symbol": symbol, "name": name, "bse_scrip_code": code,
                "registry_status": "no_filings",
                "registry_error": "BSE scrip code resolved, but no Annual Report filings found.",
                "registry_updated_at": "now()",
            }
            sb.table("companies").upsert(row).execute()
            return "no_filings"

        latest_year = years[0]
        pdf_url = _find_annual_report_pdf(symbol, name, latest_year)
        row = {
            "symbol": symbol, "name": name, "bse_scrip_code": code,
            "annual_report_years": years,
            "latest_ar_year": latest_year,
            "latest_ar_url": pdf_url,
            "registry_status": "resolved" if pdf_url else "no_filings",
            "registry_error": None if pdf_url else "Filing years listed but no PDF URL returned.",
            "registry_updated_at": "now()",
        }
        sb.table("companies").upsert(row).execute()
        return row["registry_status"]
    except Exception as e:
        sb.table("companies").upsert({
            "symbol": symbol, "name": name,
            "registry_status": "error", "registry_error": str(e)[:500],
            "registry_updated_at": "now()",
        }).execute()
        return "error"


def run(companies, force=False):
    sb = get_client()

    already_resolved = set()
    if not force:
        try:
            # Paginated: a single .execute() call caps out at Supabase's
            # default page size (~1000 rows) - with 1800+ resolved companies
            # that silently truncated already_resolved, causing already-done
            # companies past the cap to be needlessly re-checked.
            start, page_size = 0, 1000
            while True:
                resp = (sb.table("companies").select("symbol")
                        .eq("registry_status", "resolved").range(start, start + page_size - 1).execute())
                batch = resp.data or []
                already_resolved.update(row["symbol"] for row in batch)
                if len(batch) < page_size:
                    break
                start += page_size
        except Exception as e:
            print(f"[seed-registry] could not load existing companies, starting fresh: {e}")

    total = len(companies)
    counts = {}
    for i, c in enumerate(companies, 1):
        symbol, name = c["symbol"], c.get("name", c["symbol"])
        if symbol in already_resolved:
            continue
        status = seed_one(sb, symbol, name)
        counts[status] = counts.get(status, 0) + 1
        print(f"[seed-registry] ({i}/{total}) {symbol} -> {status}")

    print(f"[seed-registry] DONE. Counts: {counts}")


if __name__ == "__main__":
    import app as navrist_app
    navrist_app.load_scrip_master_async()
    run(navrist_app.STOCK_REGISTRY)
