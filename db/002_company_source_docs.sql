-- Adds the "which document did we fetch this company's data from" fields to
-- companies, per the user's explicit request to have this recorded before
-- any ratio precompute runs. Run once in Supabase's SQL Editor, same as
-- 001_schema.sql. Safe to re-run (IF NOT EXISTS on every column).

alter table companies add column if not exists bse_scrip_code text;
alter table companies add column if not exists annual_report_years jsonb;      -- all fiscal years BSE has a filing for, newest first
alter table companies add column if not exists latest_ar_year smallint;       -- newest fiscal year found
alter table companies add column if not exists latest_ar_url text;            -- the actual PDF URL used as the source document
alter table companies add column if not exists registry_status text;         -- 'resolved' | 'no_scrip_code' | 'no_filings' | 'error'
alter table companies add column if not exists registry_error text;
alter table companies add column if not exists registry_updated_at timestamptz;
