"""
Storage for qualitative-analysis sub-points (A.1, A.2, ... per the sourcing-pathway
spreadsheet). Mirrors `db_ratio_reader.py`'s shape/behaviour (upsert on compute,
timestamped, never raises) but keyed by `subpoint_id` (e.g. "A.1") instead of a
numeric ratio_no, since qualitative sub-points aren't part of the Sr 1-92 ratio list.

Table (create once in Supabase — no migration runner in this repo, see README note
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

from tools.supabase_client import get_client


def write_qualitative(symbol, subpoint_id, payload, confidence_tag, name=None):
    """Upserts the latest computed value for (symbol, subpoint_id). Never raises —
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
        sb.table("qualitative_values").upsert({
            "symbol": symbol,
            "subpoint_id": subpoint_id,
            "payload": payload,
            "confidence_tag": confidence_tag,
        }, on_conflict="symbol,subpoint_id").execute()
    except Exception as e:
        print(f"[qualitative_db] write-back failed for {symbol} {subpoint_id}: {e}")


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
        payload["confidence_tag"] = row["confidence_tag"]
        payload["retrieved_at"] = row["retrieved_at"]
        return payload
    except Exception:
        return None
