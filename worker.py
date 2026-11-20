"""The background half of Navrist: price alerts, the pattern autoscan and the report / ratio precompute.

Run it next to the API (python worker.py). The API runs with NAVRIST_ROLE=api and answers web requests only; this process runs with
NAVRIST_ROLE=worker and does everything that takes long, so a heavy job can never slow a search down. Importing app builds the same
FastAPI object but nothing is served: the alerts worker and the autoscan start while it is imported (see app.py), and the precompute
jobs are started below. Results go where they always went (the cache folder, the pattern-scan files, Supabase), which the API reads.
"""
import os
import time

os.environ["NAVRIST_ROLE"] = "worker"

import app  # noqa: E402  (must come after the role is set)

if __name__ == "__main__":
    print("[worker] Navrist background worker running (alerts, pattern autoscan, report and ratio precompute).", flush=True)
    app.start_precompute_jobs()
    while True:
        time.sleep(3600)
