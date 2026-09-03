"""
Qualitative batch worker - Phase 1C. Analogous to tools/precompute_worker.py
(the ratio batch runner) but operates over qualitative_research_runs /
qualitative_research_jobs (db/004_qualitative_research_jobs.sql) instead of
refresh_jobs, and calls tools/qualitative_task_registry.py's registered
compute_fn for a given task_id instead of a fixed RATIO_FETCHERS list.

Eligibility is fully registry-driven (tools/qualitative_task_registry.py's
`batch_enabled` flag) - NOT a hand-maintained ID list. `batch_enabled` is
computed by the generator as: defined AND implemented AND persisted AND
NOT derived_rollup AND NOT llm_dependent (the LLM exclusion is itself
mechanically detected from source, including 2+ hop delegation through
helper modules like tools/moat_peer_scoring.py - see
generate_qualitative_task_registry.py's _reaches_llm). A task the registry
doesn't mark batch_enabled - the E.1 rollup, C.1 (ambiguous), anything in
G-U with no handler, or an LLM-dependent task like A.1/A.2/A.5/A.6 - is
rejected up front by run_task_for_universe(), not silently skipped.

qualitative_values (db/001_schema.sql) remains the single source of truth
for computed results - this module never writes there directly; it only
calls the registry's compute_fn, which internally calls
tools.qualitative_engine.write_qualitative(). qualitative_research_runs/
qualitative_research_jobs record EXECUTION STATE only (did the batch run,
what happened), exactly as scoped in db/004_qualitative_research_jobs.sql's
own header comment.
"""

import importlib
import sys
import time
import traceback

sys.path.insert(0, ".")

from tools.supabase_client import get_client
from tools.qualitative_task_registry import TASK_BY_ID, TASK_REGISTRY

# A job is retried while attempts < MAX_ATTEMPTS. This bounds retries so a
# systematically-broken company/task pair (e.g. AR PDF permanently 404s)
# doesn't get retried forever across repeated resume runs.
MAX_ATTEMPTS = 3


def _resolve_compute_fn(dotted_path):
    module_path, func_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _is_migrated(task):
    """Delegates to the shared gate (`tools.qualitative_migration.
    is_migrated`) - kept as a thin alias here so existing callers/tests
    that import `_is_migrated` from this module keep working. The gate
    itself, and its full rationale, now lives in one place shared with the
    manual-upload orchestrator (see qualitative_migration.py's docstring)."""
    from tools.qualitative_migration import is_migrated
    return is_migrated(task)


def _resolve_execution_fn(task):
    """Phase 3C - ONE engine, different callers (spec section 17). Delegates
    to the shared `tools.qualitative_migration.resolve_execution_fn`, so the
    batch worker and the manual-upload orchestrator can never disagree about
    which path a given task_id executes through."""
    from tools.qualitative_migration import resolve_execution_fn
    return resolve_execution_fn(task, _resolve_compute_fn)


def list_eligible_tasks(sections=None):
    """Every task_id the registry currently marks batch_enabled=True,
    optionally filtered to a set of section letters (e.g. {'A','B','C',
    'D','E','F'}). This is THE eligibility source of truth - no
    hand-maintained ID list anywhere in this module."""
    tasks = [t for t in TASK_REGISTRY if t["batch_enabled"]]
    if sections:
        tasks = [t for t in tasks if t["section"] in sections]
    return sorted(t["task_id"] for t in tasks)


def get_task_or_raise(task_id):
    task = TASK_BY_ID.get(task_id)
    if task is None:
        raise ValueError(f"Task '{task_id}' does not exist in the task registry.")
    if not task["batch_enabled"] or not task["compute_fn"]:
        reason = []
        if not task["defined"]:
            reason.append("framework row is blank/undefined")
        if not task["implemented"]:
            reason.append("no compute_fn implemented")
        if task["derived_rollup"]:
            reason.append("derived rollup, not an independent job")
        if task.get("llm_dependent"):
            reason.append("LLM-dependent and Groq/OpenRouter is currently disabled")
        raise ValueError(
            f"Task '{task_id}' is not batch_enabled in the registry"
            + (f" ({'; '.join(reason)})" if reason else "") + "."
        )
    return task


def load_universe(sb, limit=None, symbols=None):
    """Snapshot the company universe from the persisted `companies` table - 
    NOT app.py's in-memory STOCK_REGISTRY - so the snapshot is deterministic
    and reproducible independent of any live Angel One fetch. `symbols`, if
    given, restricts to that explicit list (used for small test batches);
    `limit` caps the count (paginated, since a single .execute() truncates
    at Supabase's default page size)."""
    if symbols:
        rows = []
        for s in symbols:
            r = sb.table("companies").select("symbol,name").eq("symbol", s.upper()).execute()
            rows.extend(r.data or [])
        return rows

    companies = []
    start = 0
    page_size = 1000
    while True:
        resp = (sb.table("companies").select("symbol,name")
                .order("symbol").range(start, start + page_size - 1).execute())
        batch = resp.data or []
        companies.extend(batch)
        if len(batch) < page_size or (limit and len(companies) >= limit):
            break
        start += page_size
    if limit:
        companies = companies[:limit]
    return companies


def create_run(sb, task_id, companies):
    symbols = [c["symbol"] for c in companies]
    run = sb.table("qualitative_research_runs").insert({
        "task_id": task_id,
        "universe_snapshot": symbols,
        "universe_count": len(symbols),
        "status": "PENDING",
    }).execute()
    run_id = run.data[0]["run_id"]

    # Job rows are created PENDING up front so progress ("N/total") is
    # queryable even before the run starts processing, and so a crash right
    # after run creation still leaves a resumable job list.
    job_rows = [{"run_id": run_id, "symbol": c["symbol"], "task_id": task_id, "status": "PENDING"} for c in companies]
    for i in range(0, len(job_rows), 500):
        sb.table("qualitative_research_jobs").insert(job_rows[i:i + 500]).execute()

    return run_id


def _load_resumable_jobs(sb, run_id):
    """Jobs still needing work: PENDING/RUNNING (stale-crashed)/FAILED with
    attempts remaining. COMPLETED/INSUFFICIENT_DATA/NOT_APPLICABLE are
    terminal and are skipped - this is what makes resume idempotent."""
    jobs = []
    start = 0
    page_size = 1000
    while True:
        resp = (sb.table("qualitative_research_jobs").select("*")
                .eq("run_id", run_id)
                .in_("status", ["PENDING", "RUNNING", "FAILED"])
                .range(start, start + page_size - 1).execute())
        batch = resp.data or []
        jobs.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return [j for j in jobs if j["status"] != "FAILED" or j["attempts"] < MAX_ATTEMPTS]


def _classify_result(payload):
    """Maps the engine's confidence_tag onto a job status. Never invents a
    COMPLETED result - a payload with no confidence_tag or an unrecognized
    one is treated as FAILED (surfaced, not silently swallowed).

    Recognizes both vocabularies: the legacy compute_fn tags
    (SINGLE_SOURCE/SEARCH_INCONCLUSIVE/...) AND the universal engine's
    `tools.qualitative_evidence.EvidenceStatus` values - both write through
    this SAME classifier so job-status semantics stay identical regardless
    of which execution path produced the result."""
    tag = (payload or {}).get("confidence_tag")
    if tag in ("SINGLE_SOURCE", "VERIFIED", "CONFLICT_UNRESOLVED",
               "PARTIALLY_VERIFIED", "VERIFIED_ABSENT", "NEEDS_REVIEW", "CONTRADICTORY_EVIDENCE"):
        return "COMPLETED"
    if tag in ("SEARCH_INCONCLUSIVE", "NOT_DISCLOSED", "INSUFFICIENT_EVIDENCE"):
        return "INSUFFICIENT_DATA"
    if tag == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    return "FAILED"


def run_one_job(sb, run_id, task_id, symbol, name, compute_fn, force=False):
    """Runs one (symbol, task) job. Never raises - an exception here would
    otherwise take down the whole batch for one bad company, exactly the
    failure mode Phase 1C requires guarding against."""
    try:
        sb.table("qualitative_research_jobs").update({
            "status": "RUNNING", "started_at": "now()",
        }).eq("run_id", run_id).eq("symbol", symbol).eq("task_id", task_id).execute()
    except Exception as e:
        # A transient network blip marking the job RUNNING must not
        # prevent attempting the actual compute - confirmed real: this
        # exact call, sitting outside any guard, was the true source of a
        # second "unexpected top-level failure" seen during Phase 1E
        # resume testing even after run_one_job's own compute/write-back
        # was made resilient. The job row simply stays PENDING/whatever it
        # was, which is still correctly picked up by _load_resumable_jobs.
        print(f"[qualitative_batch] could not mark {symbol} {task_id} RUNNING (continuing anyway): {e}")

    try:
        payload = compute_fn(symbol, name, force=force)
        status = _classify_result(payload)
        sb.table("qualitative_research_jobs").update({
            "status": status, "completed_at": "now()", "last_error": None,
        }).eq("run_id", run_id).eq("symbol", symbol).eq("task_id", task_id).execute()
        return status
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()[-1000:]}"
        print(f"[qualitative_batch] {symbol} {task_id} FAILED: {e}")
        # This write-back is itself guarded - a transient network error
        # (e.g. WinError 10035) can hit twice in a row, once during
        # compute_fn and again on this very update call. Without this
        # guard, an unguarded second failure here left the job stuck at
        # RUNNING forever with no last_error (confirmed real: 9 jobs in
        # the Phase 1E 5-company/98-task test - A.2.B/A.4/C.5.2/C.6.1/
        # E.1.1/F.3.2 - were left exactly this way). Still resumable via
        # resume_run_id (RUNNING is in the resumable set), but the job
        # row should reflect the real failure whenever the write succeeds.
        try:
            current = (sb.table("qualitative_research_jobs").select("attempts")
                       .eq("run_id", run_id).eq("symbol", symbol).eq("task_id", task_id).execute())
            attempts = (current.data[0]["attempts"] if current.data else 0) + 1
            sb.table("qualitative_research_jobs").update({
                "status": "FAILED", "completed_at": "now()",
                "attempts": attempts, "last_error": err[:2000],
            }).eq("run_id", run_id).eq("symbol", symbol).eq("task_id", task_id).execute()
        except Exception as e2:
            print(f"[qualitative_batch] could not even record the failure for {symbol} {task_id}: {e2}")
        return "FAILED"


def run_task_for_universe(task_id, symbols=None, limit=None, workers=3, force=False, resume_run_id=None):
    """Main entrypoint.
 - task_id: must be in PHASE_1_ALLOWED_TASKS ("E.1.1" or "E.1.3").
 - symbols: explicit small test universe (e.g. ["HINDUNILVR","TCS"]).
 - limit: cap the universe size (mutually usable with symbols=None).
 - resume_run_id: continue an existing run instead of creating a new
        one - re-processes only its unfinished (PENDING/RUNNING/retryable
        FAILED) jobs.
    One failed/crashed company never stops the loop - every per-job call is
    wrapped in run_one_job's own try/except, and this function's own loop
    body is additionally guarded so an unexpected error in the DB update
    calls themselves can't kill the run either."""
    task = get_task_or_raise(task_id)
    compute_fn, execution_path = _resolve_execution_fn(task)
    print(f"[qualitative_batch] {task_id} executing via: {execution_path}")
    sb = get_client()

    if resume_run_id:
        run_id = resume_run_id
        sb.table("qualitative_research_runs").update({"status": "RUNNING"}).eq("run_id", run_id).execute()
        jobs = _load_resumable_jobs(sb, run_id)
        print(f"[qualitative_batch] resuming run {run_id} ({task_id}): {len(jobs)} job(s) left")
    else:
        companies = load_universe(sb, limit=limit, symbols=symbols)
        if not companies:
            raise ValueError("Universe snapshot is empty - refusing to create a run with 0 companies.")
        run_id = create_run(sb, task_id, companies)
        sb.table("qualitative_research_runs").update({
            "status": "RUNNING", "started_at": "now()",
        }).eq("run_id", run_id).execute()
        jobs = _load_resumable_jobs(sb, run_id)
        print(f"[qualitative_batch] created run {run_id} ({task_id}): {len(jobs)} companies")

    # Need each job's `name` for the engine call - companies table has it.
    name_by_symbol = {}
    for j in jobs:
        if j["symbol"] not in name_by_symbol:
            r = sb.table("companies").select("name").eq("symbol", j["symbol"]).limit(1).execute()
            name_by_symbol[j["symbol"]] = (r.data[0]["name"] if r.data else j["symbol"])

    counts = {"COMPLETED": 0, "INSUFFICIENT_DATA": 0, "NOT_APPLICABLE": 0, "FAILED": 0}

    def _process(job):
        try:
            return run_one_job(sb, run_id, task_id, job["symbol"], name_by_symbol.get(job["symbol"]), compute_fn, force=force)
        except Exception as e:
            # Belt-and-braces: run_one_job already catches engine errors;
            # this guards against a failure in the guard itself (e.g. a
            # dropped Supabase connection mid-update).
            print(f"[qualitative_batch] unexpected top-level failure for {job['symbol']} {task_id}: {e}")
            return "FAILED"

    if workers <= 1:
        for i, job in enumerate(jobs, 1):
            status = _process(job)
            counts[status] = counts.get(status, 0) + 1
            print(f"[qualitative_batch] ({i}/{len(jobs)}) {job['symbol']} {task_id} -> {status}")
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process, job): job for job in jobs}
            done = 0
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    status = fut.result()
                except Exception as e:
                    print(f"[qualitative_batch] company thread crashed for {job['symbol']}: {e}")
                    status = "FAILED"
                counts[status] = counts.get(status, 0) + 1
                done += 1
                print(f"[qualitative_batch] ({done}/{len(jobs)}) {job['symbol']} {task_id} -> {status}")

    # Run-level FAILED is reserved for total failure (every job in this
    # invocation failed) - a partial failure still marks the run COMPLETED
    # since individual job failures remain visible/retryable at the job
    # level (qualitative_research_jobs.status), per the spec's job-level
    # FAILED vs run-level FAILED distinction.
    total_failed = len(jobs) > 0 and counts["FAILED"] == len(jobs)
    run_status = "FAILED" if total_failed else "COMPLETED"
    sb.table("qualitative_research_runs").update({
        "status": run_status, "completed_at": "now()",
    }).eq("run_id", run_id).execute()
    print(f"[qualitative_batch] run {run_id} finished: {counts} -> run.status={run_status}")
    return run_id, counts


def run_eligible_tasks_for_universe(sections=None, symbols=None, limit=None, workers=3, force=False):
    """Runs every currently registry-eligible task (see list_eligible_tasks)
    against the same company set, one run per task_id - used for small
    controlled multi-task validation (e.g. a 5-company sample across all
    A-F batch-ready tasks) without ever hand-listing task IDs. Returns
    {task_id: (run_id, counts)}. One task's failure does not stop the
    others - each run_task_for_universe call is independently guarded."""
    results = {}
    for task_id in list_eligible_tasks(sections=sections):
        try:
            results[task_id] = run_task_for_universe(
                task_id, symbols=symbols, limit=limit, workers=workers, force=force,
            )
        except Exception as e:
            print(f"[qualitative_batch] task {task_id} run failed to start: {e}")
            results[task_id] = (None, {"error": str(e)})
    return results


if __name__ == "__main__":
    # Small smoke-test batch by default, e.g.:
    #   python tools/qualitative_batch_worker.py E.1.1 HINDUNILVR TCS INFY
    if len(sys.argv) < 2:
        print("usage: python tools/qualitative_batch_worker.py <task_id> [SYMBOL ...]")
        sys.exit(1)
    task_id = sys.argv[1]
    symbols = [s.upper() for s in sys.argv[2:]] or ["HINDUNILVR", "TCS", "INFY"]
    run_task_for_universe(task_id, symbols=symbols, workers=1)
