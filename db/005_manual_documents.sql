-- Manual Document Upload - lets a user supply their own Annual Report PDF
-- as an alternative to the automatic BSE/NSE fetch. Run once in Supabase's
-- SQL Editor, same as 001-004. Safe to re-run (IF NOT EXISTS everywhere).
--
-- Design: a manually uploaded Annual Report is parsed into the SAME on-disk
-- caches (cache/ar_pdfs/, cache/ar_text/) that tools/ar_document_cache.py
-- already serves to every ratio endpoint and every qualitative sub-point in
-- tools/qualitative_engine.py. Once processed, the existing engines pick it
-- up unchanged - these two tables exist only to track the upload and give
-- the user a status readout + evidence trail; they don't replace anything.

create table if not exists uploaded_documents (
    id               bigint generated always as identity primary key,
    symbol           text not null references companies(symbol) on delete cascade,
    filename         text not null,
    file_size_bytes  bigint not null,
    file_format      text not null,       -- 'pdf' | 'xlsx' | 'xls' | 'docx'
    storage_path     text not null,
    fiscal_year      smallint,            -- resolved once processed (drives the ar_pdfs/ar_text cache key)
    status           text not null default 'uploaded'
                     check (status in ('uploaded', 'processing', 'processed', 'error')),
    pages_processed  int,
    error_message    text,
    uploaded_at      timestamptz not null default now(),
    processed_at     timestamptz
);
create index if not exists idx_uploaded_documents_symbol on uploaded_documents(symbol);

-- One row per requirement found while searching the document, with its
-- evidence. status='not_found' rows are kept (not omitted) so counts are
-- always real, never invented. requirement_key = ratio_no (fundamental) or
-- task_id (qualitative, e.g. 'F.4.1') from the EXISTING frameworks.
create table if not exists extracted_values (
    id               bigint generated always as identity primary key,
    document_id      bigint not null references uploaded_documents(id) on delete cascade,
    symbol           text not null references companies(symbol) on delete cascade,
    requirement_type text not null check (requirement_type in ('fundamental', 'qualitative')),
    requirement_key  text not null,
    requirement_label text not null,
    value            text,
    unit             text,
    page             int,
    evidence_text    text,
    confidence       numeric(4,3),
    status           text not null check (status in ('verified', 'needs_validation', 'not_found')),
    created_at       timestamptz not null default now()
);
create index if not exists idx_extracted_values_document on extracted_values(document_id);

alter table uploaded_documents enable row level security;
alter table extracted_values enable row level security;
