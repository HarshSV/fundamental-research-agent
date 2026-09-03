"""
Storage for qualitative-analysis sub-points (A.1, A.2, ... per the sourcing-pathway
spreadsheet). Mirrors `db_ratio_reader.py`'s shape/behaviour (upsert on compute,
timestamped, never raises) but keyed by `subpoint_id` (e.g. "A.1") instead of a
numeric ratio_no, since qualitative sub-points aren't part of the Sr 1-92 ratio list.

Table (create once in Supabase - no migration runner in this repo, see README note
if this is missing):
    create table qualitative_values (
        id bigint generated always as identity primary key,
        symbol text not null,
        subpoint_id text not null,
        payload jsonb not null,
        confidence_tag text not null,
        retrieved_at timestamptz not null default now(),
        unique (symbol, subpoint_id)
    );
"""

from datetime import datetime, timezone

from tools.supabase_client import get_client

# Bump this whenever ANY qualitative extraction/classification logic
# changes (an anchor-phrase list, a compute_fn's classification rule, a
# scoring threshold, etc.) - mirrors tools/annual_report_financials.py's
# `_EXTRACTION_LOGIC_VERSION` mechanism for the fundamental pipeline, but
# centralized here instead of at every one of the ~240 compute_fn call
# sites (each of which does its own inline TTL-based freshness check
# independently - there is no single orchestrator choke point to fold a
# version tag into). `write_qualitative`/`read_qualitative` ARE that
# choke point: every compute_fn calls both, so stamping the payload here
# on write and rejecting a stale-version payload here on read makes a
# logic-version bump invalidate every cached row for every symbol/
# sub-point at once - without editing any compute_fn. Previously a code
# fix here had NO way to invalidate a previously-cached (up to 30-day-old)
# wrong result short of an explicit `force=True` recompute - the same
# stale-cache bug class already found and fixed on the fundamental side.
_QUALITATIVE_LOGIC_VERSION = "40"


def write_qualitative(symbol, subpoint_id, payload, confidence_tag, name=None):
    """Upserts the latest computed value for (symbol, subpoint_id). Never raises -
    a DB write failure must never break the live response the user is waiting on.

    qualitative_values.symbol has a foreign key into companies(symbol) - a
    symbol that only exists via live BSE/NSE resolution (not yet run through
    the batch seed_company_registry.py/precompute_worker.py path) has no
    companies row yet, so the upsert below silently fails every time
    (confirmed real: TPINDIA, resolvable and fully computable live, could
    never cache because "companies" had no row for it). Upserting a minimal
    companies row first (real name if the caller has one, symbol as a
    placeholder otherwise - overwritten with the real name whenever the
    batch registry path runs) makes every resolvable symbol cacheable, not
    just the pre-seeded ones."""
    try:
        sb = get_client()
        sb.table("companies").upsert({
            "symbol": symbol, "name": name or symbol,
        }, on_conflict="symbol", ignore_duplicates=True).execute()
        payload = dict(payload or {})
        payload["_logic_version"] = _QUALITATIVE_LOGIC_VERSION
        sb.table("qualitative_values").upsert({
            "symbol": symbol,
            "subpoint_id": subpoint_id,
            "payload": payload,
            "confidence_tag": confidence_tag,
            # retrieved_at's DB default only fires on the row's first INSERT
            # - an upsert that resolves to an UPDATE (recomputing an
            # existing sub-point) never touches a column absent from its
            # own SET list, so every re-run kept showing the original
            # first-ever-computed date even though the payload/status genuinely
            # refreshed (confirmed real: A.2.A's payload updated on
            # recompute but retrieved_at stayed frozen at its first-write
            # date). Setting it explicitly here makes every write refresh it.
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="symbol,subpoint_id").execute()
    except Exception as e:
        print(f"[qualitative_db] write-back failed for {symbol} {subpoint_id}: {e}")


# Internal engine tags -> the final, user-facing status vocabulary. The
# internal tags (SEARCH_INCONCLUSIVE, SINGLE_SOURCE, NOT_FOUND, ...) are
# how ~240 compute_fns communicate INTERNALLY (a nuanced record of which
# evidence pathway ran and what it found), but none of them should ever
# reach the frontend as a raw debug status - "SEARCH_INCONCLUSIVE" tells a
# user nothing about WHY a KPI is empty. Every compute_fn already writes a
# specific `rationale`/`note` explaining the actual reason before setting
# an internal tag, so this mapping preserves that real reason text while
# normalizing the STATUS LABEL itself to one of six final states. Applied
# once, centrally, at serve-time (see app.py's /api/v1/qualitative/{symbol}
# endpoint) - never by touching any of the ~240 individual compute_fns.
_USER_FACING_STATUS = {
    "SINGLE_SOURCE": "VERIFIED",
    "MULTI_SOURCE": "VERIFIED",
    "VERIFIED": "VERIFIED",
    "CONFLICT_UNRESOLVED": "NEEDS_REVIEW",
    "NEEDS_REVIEW": "NEEDS_REVIEW",
    "SEARCH_INCONCLUSIVE": "NOT_DISCLOSED",
    "NOT_FOUND": "NOT_DISCLOSED",
    "NOT_DISCLOSED": "NOT_DISCLOSED",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
    "EXTERNAL_DATA_REQUIRED": "DATA_MISSING",
    "DATA_MISSING": "DATA_MISSING",
    "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    # Phase 3C - tools.qualitative_evidence.EvidenceStatus values, written
    # by tools.qualitative_task_engine.evaluate_task (the universal engine).
    # Mapped onto the SAME six-state user-facing vocabulary above rather
    # than introducing a second one, per "integrate the new result model
    # into qualitative_db, don't create a second persistence/vocabulary
    # system". PARTIALLY_VERIFIED intentionally maps to VERIFIED (single-
    # source-but-real-evidence, consistent with how SINGLE_SOURCE already
    # mapped) rather than a new bucket the frontend doesn't know yet;
    # VERIFIED_ABSENT and CONTRADICTORY_EVIDENCE get their own honest
    # buckets distinct from NOT_DISCLOSED/NEEDS_REVIEW.
    "PARTIALLY_VERIFIED": "VERIFIED",
    "VERIFIED_ABSENT": "VERIFIED_ABSENT",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_DATA",
    "CONTRADICTORY_EVIDENCE": "NEEDS_REVIEW",
    "ERROR": "DATA_MISSING",
}


def to_user_facing_status(internal_tag):
    """Maps an internal confidence_tag to the final six-state vocabulary
    (VERIFIED/NEEDS_REVIEW/NOT_DISCLOSED/DATA_MISSING/NOT_APPLICABLE/
    INSUFFICIENT_DATA). An unrecognized tag defaults to NOT_DISCLOSED
    (the safest "we don't have a confirmed answer" bucket) rather than
    leaking through as-is."""
    return _USER_FACING_STATUS.get((internal_tag or "").upper(), "NOT_DISCLOSED")


def read_qualitative(symbol, subpoint_id):
    """Returns the stored payload dict (with `retrieved_at` merged in), or None if
    nothing has been computed yet / the table doesn't exist / any DB error."""
    try:
        sb = get_client()
        r = (sb.table("qualitative_values").select("*")
             .eq("symbol", symbol).eq("subpoint_id", subpoint_id).limit(1).execute())
        if not r.data:
            return None
        row = r.data[0]
        payload = dict(row["payload"] or {})
        # A row written before the current `_QUALITATIVE_LOGIC_VERSION` (or
        # by any code path that predates this versioning at all - treated
        # as version 0) is stale by definition, regardless of its own
        # age-based TTL - a logic/extraction fix invalidates it immediately
        # rather than waiting out the per-compute_fn TTL or requiring
        # `force=True` at every call site.
        if payload.get("_logic_version") != _QUALITATIVE_LOGIC_VERSION:
            return None
        payload["confidence_tag"] = row["confidence_tag"]
        payload["retrieved_at"] = row["retrieved_at"]
        return payload
    except Exception:
        return None
