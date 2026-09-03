-- Additive-only migration for the Qualitative document upload architecture
-- (tools/manual_document_pipeline.py). Adds a document_type column to the
-- existing uploaded_documents table (created in 005_manual_documents.sql)
-- so a symbol's uploaded Corporate Governance Report, BRSR/ESG Report,
-- Investor Presentation, Earnings Call Transcript, Credit Rating Report,
-- and Other Supporting Documents can be told apart from the Annual Report
-- rows (which remain untyped, NULL, for backward compatibility with the
-- existing Fundamental document-analysis workflow). Does not touch any
-- other column, index, or table, and does not affect the 68-ratio
-- Fundamental engine, its schema, or its extraction logic in any way.
-- Run once in Supabase's SQL Editor. Safe to re-run.

alter table uploaded_documents
    add column if not exists document_type text;

create index if not exists idx_uploaded_documents_symbol_type
    on uploaded_documents(symbol, document_type);
