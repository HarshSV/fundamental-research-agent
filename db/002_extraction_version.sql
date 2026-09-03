-- Adds extraction/calculation versioning to `ratio_values` (spec §21 /
-- Phase-1 TODO), so a change to shared extraction or formula logic can make
-- old cached rows a transparent cache miss instead of requiring a manual
-- per-symbol purge.
--
-- Run this ONCE in Supabase's SQL Editor, same as db/001_schema.sql. Safe
-- to re-run: idempotent (IF NOT EXISTS).
--
-- After this runs, callers that pass `extraction_version=` to
-- `tools.db_ratio_reader.write_db_ratio`/`try_db_ratio` (currently:
-- anything using `tools.fundamental_fact_store.EXTRACTION_VERSION`) will
-- have that column populated/filtered; existing callers that don't pass it
-- are unaffected - the column stays NULL for their rows and those reads
-- simply don't filter on it, exactly as before this migration.

alter table ratio_values
    add column if not exists extraction_version smallint;

create index if not exists idx_ratio_values_extraction_version
    on ratio_values(symbol, ratio_no, extraction_version);
