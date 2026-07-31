"""One-off targeted re-derivation for ratio_no 10/11/12/39 (Current Ratio,
Quick Ratio, Cash Ratio, Operating Cash Flow Ratio) across every registered
company — these were the ones corrupted by a regression (TCL/Cash label
guard applied too broadly) that was live during the full precompute run
on 2026-07-31. Bypasses the resumable skip_done set entirely (that set
still marks these pairs "done" even though their result was wrong) and
always recomputes fresh, now that the regression is fixed."""
import sys
sys.path.insert(0, ".")
from tools.supabase_client import get_client
from tools.precompute_worker import compute_one, upsert_company, RATIO_FETCHERS

TARGET_RATIO_NOS = {10, 11, 12, 34, 35, 36, 39, 40, 41}
targets = [(rn, fn) for rn, fn in RATIO_FETCHERS if rn in TARGET_RATIO_NOS]

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

print(f"[refix] {len(all_companies)} companies x {len(targets)} ratios")
done_companies = 0
for c in all_companies:
    symbol, name = c["symbol"], c.get("name", c["symbol"])
    try:
        upsert_company(sb, symbol, name)
    except Exception as e:
        print(f"[refix] company upsert failed for {symbol}: {e}")
        continue
    for ratio_no, fetcher in targets:
        compute_one(sb, symbol, name, ratio_no, fetcher)
    done_companies += 1
    print(f"[refix] ({done_companies}/{len(all_companies)}) {symbol} done")

print("[refix] DONE")
