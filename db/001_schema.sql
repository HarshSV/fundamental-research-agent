-- Navrist fundamentals + price database schema.
-- Run this ONCE in Supabase's SQL Editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
-- Safe to re-run: every statement is idempotent (IF NOT EXISTS).

create table if not exists companies (
    symbol           text primary key,
    name             text not null,
    bse_code         text,
    isin             text,
    industry         text,
    is_bank_nbfc     boolean not null default false,
    updated_at       timestamptz not null default now()
);

-- One row per (symbol, ratio, fiscal year, consolidated/standalone) combo.
-- This is what kills the "Reading audited filings..." 3-4 minute wait: the
-- precompute worker writes here once, the app reads from here in milliseconds.
create table if not exists ratio_values (
    symbol           text not null references companies(symbol) on delete cascade,
    ratio_no         smallint not null,       -- 1-29, per the spec sheet
    fiscal_year      smallint not null,
    consolidated     boolean not null default true,
    applicable       boolean not null,
    value            numeric,
    unit             text,
    confidence       numeric(3,2),
    estimated        boolean not null default false,
    period_label     text,
    numerator        jsonb,
    denominator      jsonb,
    sources          jsonb,
    reason           text,                    -- populated when applicable = false
    note             text,
    computed_at      timestamptz not null default now(),
    primary key (symbol, ratio_no, fiscal_year, consolidated)
);
create index if not exists idx_ratio_values_symbol on ratio_values(symbol);

-- End-of-day candles.
create table if not exists price_eod (
    symbol           text not null references companies(symbol) on delete cascade,
    date             date not null,
    open             numeric,
    high             numeric,
    low              numeric,
    close            numeric,
    volume           bigint,
    primary key (symbol, date)
);
create index if not exists idx_price_eod_symbol_date on price_eod(symbol, date desc);

-- Intraday candles (populated once an intraday data vendor is chosen).
create table if not exists price_intraday (
    symbol           text not null references companies(symbol) on delete cascade,
    ts               timestamptz not null,
    open             numeric,
    high             numeric,
    low              numeric,
    close            numeric,
    volume           bigint,
    primary key (symbol, ts)
);
create index if not exists idx_price_intraday_symbol_ts on price_intraday(symbol, ts desc);

-- Tracks the precompute worker's progress per (symbol, ratio) so a
-- full-registry run is resumable, not an all-or-nothing multi-hour job.
create table if not exists refresh_jobs (
    symbol           text not null references companies(symbol) on delete cascade,
    ratio_no        smallint not null,
    status           text not null default 'pending',  -- pending | running | done | error
    last_run_at      timestamptz,
    last_error       text,
    primary key (symbol, ratio_no)
);
create index if not exists idx_refresh_jobs_status on refresh_jobs(status);

-- Row Level Security: lock every table down by default. The backend talks
-- to Supabase using the service_role key, which bypasses RLS entirely — so
-- these policies only matter if the anon/public key is ever used directly
-- (e.g. accidentally shipped to the frontend). Belt-and-braces.
alter table companies enable row level security;
alter table ratio_values enable row level security;
alter table price_eod enable row level security;
alter table price_intraday enable row level security;
alter table refresh_jobs enable row level security;
