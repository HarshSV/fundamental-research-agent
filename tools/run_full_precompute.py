"""
Kicks off the full NSE/BSE registry precompute run. Reuses app.py's own
`load_scrip_master_async()` to build the exact same full symbol list the
running dashboard's autocomplete uses (top 100+ curated names + every other
active NSE equity symbol from Angel One's scrip master), then hands the
whole list to tools/precompute_worker.run().

Long-running by design (thousands of stocks x ~21 ratios, each involving a
PDF download+parse) - meant to be started with nohup/background and
checked on periodically via refresh_jobs' status counts, not watched live.
Safe to kill and restart: precompute_worker.run() skips (symbol, ratio_no)
pairs already marked 'done'.
"""

import sys
sys.path.insert(0, ".")

import app as navrist_app
from tools import precompute_worker

# Optional: python tools/run_full_precompute.py --workers 4
# Runs N companies concurrently instead of one at a time. Keep this modest -
# NSE/BSE will start rate-limiting or blocking a client that opens too many
# concurrent connections, which makes the run slower overall, not faster.
workers = 1
if "--workers" in sys.argv:
    idx = sys.argv.index("--workers")
    workers = int(sys.argv[idx + 1])
    print(f"[full-precompute] running with {workers} concurrent companies")

print("[full-precompute] loading full NSE scrip registry (same source as the live dashboard)...")
# Angel One's scrip-master endpoint occasionally times out - when it does,
# load_scrip_master_async() silently falls back to just the ~98 curated
# names in STOCK_REGISTRY's static list (not a crash, just a much smaller
# registry), which would otherwise cause a "full" precompute run to quietly
# cover only 98 companies instead of ~2,400. Retry a few times rather than
# trusting the first attempt.
for attempt in range(5):
    navrist_app.load_scrip_master_async()
    if len(navrist_app.STOCK_REGISTRY) > 500:
        break
    print(f"[full-precompute] attempt {attempt + 1} only got {len(navrist_app.STOCK_REGISTRY)} "
          f"companies (scrip-master fetch likely timed out) - retrying...")
companies = navrist_app.STOCK_REGISTRY
print(f"[full-precompute] {len(companies)} companies loaded. Starting precompute run...")

precompute_worker.run(companies, workers=workers)

print("[full-precompute] DONE.")
