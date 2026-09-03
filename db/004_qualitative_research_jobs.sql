-- Qualitative research run/job tracking - Phase 1A.
-- Run this ONCE in Supabase's SQL Editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
-- Safe to re-run: every statement is idempotent (IF NOT EXISTS).
--
-- This does NOT duplicate qualitative_values (db/001_schema.sql) - that table
-- remains the single source of truth for computed results (symbol, subpoint_id,
-- payload, confidence_tag). These two tables track batch EXECUTION STATE only:
-- which (run, company, task) triples have been attempted, their outcome, and
-- how many times they were retried. A qualitative_values row can exist without
-- a job row (e.g. results produced by a live /generate-report call rather than
-- a batch run) and a job row can exist before qualitative_values is written
-- (e.g. status = RUNNING, or a FAILED/INSUFFICIENT_DATA job that never wrote
-- a result). The two tables answer different questions: qualitative_values
-- answers "what is the current answer for this company/task", these tables
-- answer "did the batch run for this company/task, and what happened".

-- One row per batch invocation (e.g. "run E.1.1 across the whole universe").
-- universe_snapshot captures exactly which symbols this run targeted at the
-- moment it started, so a run's scope is auditable even if the companies
-- table changes later (rows added/removed) - the run stays reproducible
-- and its progress numbers stay meaningful.
create table if not exists qualitative_research_runs (
    run_id            bigint generated always as identity primary key,
    task_id           text not null,               -- e.g. "E.1.1", or "ALL"
    universe_snapshot jsonb not null,               -- list of symbols this run was created against
    universe_count    int not null,
    status            text not null default 'PENDING'
                      check (status in ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    started_at        timestamptz,
    completed_at      timestamptz,
    created_at        timestamptz not null default now()
);

-- One row per (run, company, task) triple - the unit of batch work. Deliberately
-- keyed by run_id (not just symbol+task_id) so re-running a task later creates
-- a fresh, independently-auditable set of job rows rather than overwriting the
-- history of a prior run; resuming a specific run's unfinished work means
-- querying WHERE run_id = X AND status NOT IN ('COMPLETED', 'INSUFFICIENT_DATA', 'NOT_APPLICABLE').
create table if not exists qualitative_research_jobs (
    run_id            bigint not null references qualitative_research_runs(run_id) on delete cascade,
    symbol            text not null references companies(symbol) on delete cascade,
    task_id           text not null,                -- e.g. "E.1.1"
    status            text not null default 'PENDING'
                      check (status in ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'INSUFFICIENT_DATA', 'NOT_APPLICABLE')),
    attempts          int not null default 0,
    last_error        text,
    started_at        timestamptz,
    completed_at      timestamptz,
    primary key (run_id, symbol, task_id)
);
create index if not exists idx_qual_research_jobs_status on qualitative_research_jobs(status);

-- Row Level Security: lock both tables down by default, matching every other
-- table in db/001_schema.sql. The backend talks to Supabase using the
-- service_role key, which bypasses RLS entirely - this only matters if the
-- anon/public key is ever used directly. Belt-and-braces.
alter table qualitative_research_runs enable row level security;
alter table qualitative_research_jobs enable row level security;
