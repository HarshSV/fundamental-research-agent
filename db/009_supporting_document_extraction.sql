-- Additive-only migration. Tracks whether an uploaded qualitative
-- supporting document (Corporate Governance/BRSR-ESG/Investor Presentation/
-- Earnings Call/Credit Rating/Other, see db/008_qualitative_document_types.sql)
-- was actually opened and its text extracted, so the upload pipeline can be
-- audited (extracted_text_length is real and inspectable, not assumed).
-- Does not touch any other column, index, or table, and does not affect the
-- 68-ratio Fundamental engine or the Annual Report/XBRL/Shareholding upload
-- path in any way. Run once in Supabase's SQL Editor, after db/008. Safe to
-- re-run.

alter table uploaded_documents
    add column if not exists extracted_text_length integer,
    add column if not exists analysis_consumed boolean not null default false;
