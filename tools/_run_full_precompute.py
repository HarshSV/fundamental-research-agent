"""One-off driver: full re-derivation pass across every registered company,
using skip_done=False so today's shared-code fixes (PBT ordering, payables
MSME wording, P&L page-detection, ICR/DPS formulas, DB freshness guard)
overwrite every previously-cached ratio_values row, not just gaps.
User-authorized 2026-07-30 to clear the stale-cache backlog across all
2,400+ registered companies rather than leaving it to the (non-recurring)
default skip_done=True backfill behavior."""
import sys
sys.path.insert(0, ".")
from tools.supabase_client import get_client
from tools.precompute_worker import run

sb = get_client()
all_companies = []
page_size = 1000
offset = 0
while True:
    r = sb.table("companies").select("symbol,name").range(offset, offset + page_size - 1).execute()
    rows = r.data or []
    all_companies.extend(rows)
    if len(rows) < page_size:
        break
    offset += page_size

print(f"[full-precompute] loaded {len(all_companies)} companies, resuming (skip_done=True - retries only errored/not-yet-done pairs)")
run(all_companies, sleep_between=0.0, skip_done=True, workers=4)
print("[full-precompute] DONE")
