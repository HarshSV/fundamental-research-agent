-- Additive-only migration for the 68-ratio Fundamental framework
-- (tools/fundamental_ratio_registry.py). Widens fundamental_analysis_
-- results.status to add 'not_applicable' (sector-inapplicable, e.g. bank
-- ratios for a non-financial company) and 'insufficient_data' (the ratio
-- is structurally impossible in the document-only manual workflow, e.g.
-- Beta without an approved historical price source). Does NOT touch any
-- column, index, or RLS policy, and does NOT drop/replace the table -
-- only the CHECK constraint on `status`. Run once in Supabase's SQL
-- Editor. Safe to re-run.

alter table fundamental_analysis_results
    drop constraint if exists fundamental_analysis_results_status_check;

alter table fundamental_analysis_results
    add constraint fundamental_analysis_results_status_check
    check (status in ('verified', 'needs_review', 'not_disclosed', 'not_applicable', 'insufficient_data'));
