-- Document Analysis engine - the NEW workflow triggered by
-- Upload Documents -> Analyse. Deliberately separate from ratio_values
-- (which the OLD per-ratio fetchers in tools/nse_xbrl.py /
-- tools/annual_report_financials.py write to): this table is populated by
-- tools/document_analysis_engine.py's own broader, alias-rich extraction
-- directly over the uploaded Annual Report + XBRL, not by re-running the
-- old narrow fetchers. Run once in Supabase's SQL Editor. Safe to re-run.

create table if not exists fundamental_analysis_results (
    id           bigint generated always as identity primary key,
    symbol       text not null references companies(symbol) on delete cascade,
    ratio_key    text not null,        -- e.g. 'current_ratio' - stable key, not a display label
    label        text not null,
    category     text not null,        -- Profitability | Liquidity | Leverage | Efficiency | Returns | Cash Flow | Tax
    value        numeric,
    unit         text,
    status       text not null check (status in ('verified', 'needs_review', 'not_disclosed')),
    formula      text,
    inputs       jsonb,                -- [{name, value, unit, source, page}, ...]
    computed_at  timestamptz not null default now(),
    unique (symbol, ratio_key)
);
create index if not exists idx_fundamental_analysis_results_symbol on fundamental_analysis_results(symbol);

alter table fundamental_analysis_results enable row level security;
