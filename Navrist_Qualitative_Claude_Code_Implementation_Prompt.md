# Claude Code Implementation Prompt: Make Navrist AI Qualitative Analysis Company-Universal

You are working inside the Navrist AI equity-research project.

## Objective

Fix the qualitative-analysis architecture so that the A-U framework
works across the **entire NSE stock universe produced by the project's
existing NSE scraper**, not only the company currently open in the
frontend.

The current failure mode is:

1.  User opens a company such as Hindustan Unilever.
2.  User asks for a qualitative task such as E1.
3.  The frontend correctly displays the E1 sub-task.
4.  The backend/research layer fetches evidence only for Hindustan
    Unilever.
5.  The system therefore behaves as if the qualitative engine is a
    single-company feature.

This is an architectural problem, not a frontend-only problem.

The desired system must treat the NSE scraper's stock universe as the
source of truth and must be capable of fetching, processing, storing,
and serving qualitative research for **every company in that universe**.

## Important context files

The project folder will contain:

-   `Navrist_Qualitative_Framework.md`
    -   Converted from the authoritative Excel workbook.
    -   Contains all A-U qualitative tasks, sub-tasks, source paths,
        formulas/matrices, and chart rules.
-   This implementation prompt.

Read the entire framework file before changing the qualitative-analysis
code.

Do not reduce the framework to only the example E1 task. E1 is a test
case for the architecture.

------------------------------------------------------------------------

# 1. First inspect the existing project

Before editing anything:

-   Identify the current NSE scraper.
-   Identify where the complete NSE stock universe is stored/generated.
-   Identify the company/symbol model used by the frontend.
-   Identify the current qualitative-analysis endpoint(s).
-   Identify the current task/sub-task definitions.
-   Identify the source-fetching/research functions.
-   Identify where research results are cached or persisted.
-   Identify whether the current implementation uses the selected
    frontend company as the only input to the scraper/research layer.
-   Identify all places where a company symbol/name is hard-coded or
    implicitly taken from frontend state.
-   Identify whether the application currently has a database table for
    companies, tasks, evidence, research runs, or qualitative results.

Do not start by rewriting the application.

First understand the existing flow.

------------------------------------------------------------------------

# 2. Correct architecture

Implement the following logical pipeline:

NSE Universe ↓ Company Registry ↓ Qualitative Task Registry ↓ Source
Retrieval Layer ↓ Company × Task Research Jobs ↓ Evidence Store ↓
Scoring / Classification Layer ↓ Qualitative Result Store ↓ API ↓
Frontend

The currently selected company is only a VIEW/FILTER parameter.

It must not determine which companies are researched.

------------------------------------------------------------------------

# 3. NSE universe must be the source of truth

Use the existing NSE scraper already present in the project.

Do not create a second fake list of stocks.

The system must dynamically use the companies returned by the scraper.

Create or reuse a normalized company registry with fields equivalent to:

-   company_id
-   symbol
-   company_name
-   isin, if available
-   exchange
-   active/listed status
-   sector, if available
-   industry, if available
-   source
-   last_seen_at
-   last_researched_at

The exact schema can follow the existing project's database conventions.

Important:

-   Symbols must be unique.
-   Company names must not be used as the primary identifier when a
    symbol/ISIN is available.
-   Handle renamed companies and duplicate names safely.
-   Do not assume that the universe will permanently contain exactly
    2409 companies. The number must come from the scraper.

------------------------------------------------------------------------

# 4. Create a qualitative task registry

The A-U workbook contains parent tasks and sub-tasks.

Represent them as data, not frontend-only hard-coded UI.

At minimum, each task should have:

-   task_id
-   parent_id
-   title
-   primary_source
-   source_path/instructions
-   formula_or_matrix
-   visualization_rule
-   applicability_rule, if applicable
-   enabled
-   version

Examples:

E1 E1.1 E1.2 E1.3

The exact tasks must come from `Navrist_Qualitative_Framework.md`.

Do not manually recreate only E1.

The whole framework must be represented.

------------------------------------------------------------------------

# 5. Separate retrieval from analysis

This is critical.

Do NOT implement:

frontend company → Claude → search web → return answer

as the primary architecture.

Instead implement:

company → source retrieval → evidence normalization → evidence storage →
task analysis → result storage

The LLM should analyze retrieved evidence.

It should not be responsible for inventing the entire data-acquisition
pipeline.

------------------------------------------------------------------------

# 6. Evidence model

Every piece of evidence should be tied to:

-   company_id
-   symbol
-   task_id
-   source_type
-   source_url
-   source_document
-   document_date
-   reporting_period
-   retrieved_at
-   evidence_text or structured_data
-   confidence
-   extraction_status

Where possible, retain:

-   exact source URL
-   document/filing title
-   page/section
-   short supporting excerpt
-   numeric values separately from prose

Never store an answer without provenance.

Example conceptual record:

{ "company_id": "...", "symbol": "HINDUNILVR", "task_id": "E1.1",
"source_type": "NSE_ANNUAL_REPORT", "source_url": "...",
"document_date": "...", "reporting_period": "FY2025-26", "evidence":
"...", "confidence": 0.91, "status": "FOUND" }

------------------------------------------------------------------------

# 7. Do not fetch every source independently for every task

This is one of the most important performance requirements.

Many qualitative tasks use the same underlying documents.

For each company, retrieve/cache documents such as:

-   latest annual report
-   relevant prior annual reports where historical comparison is
    required
-   corporate announcements
-   shareholding-related filings
-   related-party disclosures
-   auditor report
-   board/governance disclosures
-   investor presentations
-   earnings-call/investor-meet material where available
-   other source documents required by the framework

Then extract reusable evidence from those documents.

Do NOT make 2409 × hundreds of independent web searches unless
absolutely necessary.

Prefer:

company → document collection → cached document corpus → many task
analyses

This reduces load, latency, rate-limit problems, and duplicate work.

------------------------------------------------------------------------

# 8. Build a research-job system

The application needs batch processing.

Conceptually:

ResearchRun - run_id - universe_snapshot_id - started_at -
completed_at - status

ResearchJob - job_id - run_id - company_id - task_id - priority -
status - attempts - started_at - completed_at - error

Statuses should include at least:

PENDING RUNNING COMPLETED FAILED INSUFFICIENT_DATA NOT_APPLICABLE

The architecture must support:

-   one company
-   one task
-   all tasks for one company
-   one task for all companies
-   all tasks for all companies

This is essential for testing E1 across the complete universe.

------------------------------------------------------------------------

# 9. Batch mode must exist independently of the frontend

Add a backend/service mechanism to run:

"Research E1 for all active NSE companies"

and:

"Research all applicable qualitative tasks for all active NSE companies"

The UI should not have to remain open while this happens.

If the project already has a queue system, use it.

If not, implement a simple reliable worker architecture appropriate for
the current stack.

Do not introduce a massive infrastructure stack unnecessarily.

------------------------------------------------------------------------

# 10. Incremental processing

Do not repeatedly research everything from scratch.

Each company/task result should have:

-   last_researched_at
-   source_version/document hash where practical
-   result_version
-   status

If the underlying source documents have not changed, reuse the existing
evidence/result.

Allow forced refresh.

Support:

-   refresh one company
-   refresh one task
-   refresh one company/task
-   refresh all stale companies
-   full rebuild

------------------------------------------------------------------------

# 11. Sector applicability

The framework contains sector-specific tasks under section S.

Do not force:

-   bank tasks onto FMCG companies
-   pharma tasks onto banks
-   auto tasks onto IT companies

Use the company's sector/industry classification from the existing data
where possible.

For non-applicable tasks return:

status = NOT_APPLICABLE

with a reason.

Do not convert N/A to a negative score.

------------------------------------------------------------------------

# 12. E1 implementation as the first end-to-end test

After the architecture is in place, implement E1 completely.

E1: Unexpected related-party payments to opaque vendors or consultants.

At minimum implement:

-   E1.1 Related-party payment frequency
-   E1.2 \[use the exact task definition from the framework\]
-   E1.3 Payment rationale / arm's-length basis

Do not invent missing definitions. Read the framework file.

For each company:

1.  Find the latest relevant annual report.
2.  Locate related-party disclosures.
3.  Identify relevant related-party vendors/consultants/payments.
4.  Extract amounts, counterparties, relationship, nature of
    transaction, and rationale where disclosed.
5.  Assess whether the disclosure supports an arm's-length conclusion.
6.  Apply the workbook's scoring matrix.
7.  Store evidence and provenance.
8.  Store the final structured result.
9.  Expose it through the API.
10. Render it in the frontend.

The frontend should show E1 for the selected company by querying the
stored company-specific result.

------------------------------------------------------------------------

# 13. Frontend behaviour

The frontend flow should become:

User selects HINDUNILVR → API requests qualitative results where
company_id = HINDUNILVR → results are returned from the research/result
store.

If the user selects another company:

User selects TCS → same API → company_id = TCS

The backend must never rely on a global "current stock" variable.

Also add a way to display research status:

-   Research available
-   Research in progress
-   Last researched
-   Insufficient data
-   Not applicable
-   Failed, retry available

For batch research, expose progress such as:

1,240 / 2,409 companies completed

and task-specific progress where useful.

------------------------------------------------------------------------

# 14. API design

Use clean APIs similar to:

GET /companies GET /companies/{symbol}

GET /qualitative/tasks GET /qualitative/tasks/{task_id}

GET /qualitative/{symbol} GET /qualitative/{symbol}/{task_id}

POST /qualitative/research POST /qualitative/research/{symbol} POST
/qualitative/research/task/{task_id} POST /qualitative/research/all

GET /qualitative/research/{run_id}/status

Adapt paths to the existing project conventions instead of blindly
creating duplicates.

Important batch endpoint example:

POST /qualitative/research/task/E1

This must enqueue E1 for every active company returned by the NSE
universe.

Not just the company currently selected in the UI.

------------------------------------------------------------------------

# 15. Source retrieval rules

Respect the source hierarchy in the framework.

For every task:

1.  Try the specified primary source.
2.  Use the stated fallback/cross-check sources when the framework
    permits them.
3.  Record which source actually supplied the evidence.
4.  Never claim a source was checked when it was not.
5.  If the source is unavailable, record the failure and use an allowed
    fallback.
6.  If no usable evidence exists, return INSUFFICIENT_DATA.

Do not fabricate missing data.

------------------------------------------------------------------------

# 16. LLM usage

The LLM should receive structured context like:

Company: Hindustan Unilever Limited Symbol: HINDUNILVR

Task: E1.3 Payment rationale / arm's-length basis

Evidence: \[retrieved excerpts + source metadata\]

Scoring rule: \[exact workbook rule\]

Required output: structured JSON

Example:

{ "task_id": "E1.3", "status": "FOUND", "score": 4, "classification":
"POSITIVE", "summary": "...", "evidence": \[ { "claim": "...",
"source_url": "...", "document": "...", "date": "...", "excerpt": "..."
} \], "confidence": 0.86 }

The LLM must not be allowed to silently invent evidence.

------------------------------------------------------------------------

# 17. Structured output contract

Use Pydantic or the project's existing validation layer.

Every qualitative result should have a predictable schema.

Suggested fields:

-   company_id
-   symbol
-   task_id
-   status
-   score
-   classification
-   summary
-   evidence\[\]
-   source_count
-   confidence
-   researched_at
-   model
-   framework_version

Validate every LLM response.

Reject malformed output.

------------------------------------------------------------------------

# 18. Caching and deduplication

A major objective is to avoid repeatedly downloading identical source
documents.

Implement caching at the document level.

Possible key:

source_url + document_date + company_id

Better if available:

document_hash

The same annual report should be usable by many tasks.

The same evidence should be reusable by multiple related tasks where
appropriate.

------------------------------------------------------------------------

# 19. Concurrency and rate limits

The universe may contain around 2,409 stocks, but this number can
change.

Do not launch 2,409 uncontrolled browser sessions or HTTP requests
simultaneously.

Implement bounded concurrency.

Respect:

-   NSE rate limits
-   website terms/robots restrictions where applicable
-   source availability
-   retry/backoff

Use exponential backoff for temporary failures.

Add logging.

------------------------------------------------------------------------

# 20. Reliability requirements

The system must survive:

-   one company's annual report being unavailable
-   one company returning malformed data
-   source timeout
-   rate limit
-   PDF parsing failure
-   LLM timeout
-   one failed job

One failed company must NOT stop the entire batch.

Failed jobs must be retryable.

------------------------------------------------------------------------

# 21. Testing strategy

Before declaring the implementation complete:

### Test A: one company / one task

HINDUNILVR + E1

### Test B: two companies / one task

HINDUNILVR + another NSE company + E1

### Test C: 10 companies / one task

E1 across 10 companies.

### Test D: full universe / one task

E1 across every company returned by the NSE scraper.

### Test E: one company / multiple tasks

HINDUNILVR + E1, E2, E3, etc.

### Test F: sector applicability

Test a bank, pharma company, auto company, IT company, and consumer
company.

### Test G: missing evidence

Confirm that missing evidence becomes INSUFFICIENT_DATA.

### Test H: rerun

Run the same task again and verify cached documents/results are reused
where valid.

### Test I: frontend switching

Open HINDUNILVR, then TCS, then another company. Verify that each
company displays its own stored results.

------------------------------------------------------------------------

# 22. Important distinction: universe data vs research data

Do not confuse:

A. NSE stock universe with B. qualitative evidence

The scraper tells the application:

"These are the companies that exist in our research universe."

It does NOT automatically provide the qualitative information needed for
E1-U6.

The research pipeline must use the universe as the input set and then
collect evidence from the sources defined in the framework.

------------------------------------------------------------------------

# 23. Do not make the Markdown file the runtime database

`Navrist_Qualitative_Framework.md` is for:

-   developer context
-   task definitions
-   implementation reference
-   LLM/Claude Code context

It is NOT the place to store:

-   2,409 companies' results
-   research evidence
-   live source data

Those belong in the application's database/object storage/cache.

------------------------------------------------------------------------

# 24. Deliverables

Implement the architecture in the existing project without unnecessarily
rewriting unrelated features.

Provide:

1.  Changed files.
2.  Database/schema changes.
3.  New/updated research services.
4.  Batch worker/job mechanism.
5.  API changes.
6.  Frontend changes.
7.  E1 end-to-end implementation.
8.  Tests.
9.  Exact commands needed to run the migration/worker/research batch.
10. A short explanation of how to run:

-   E1 for one company
-   E1 for all companies
-   all applicable qualitative tasks for all companies

Do not claim success without actually testing.

------------------------------------------------------------------------

# 25. Final acceptance criteria

The implementation is successful only if all of the following are true:

-   The NSE scraper provides the company universe.
-   The qualitative engine can iterate over that universe.
-   The selected frontend company is only a filter/view.
-   E1 can be run for all companies in the universe.
-   Results are stored per company and per task.
-   Evidence has source provenance.
-   The same source documents are reused across tasks.
-   Batch failures do not stop the entire run.
-   Jobs can be retried.
-   Sector-specific tasks can be marked N/A.
-   Missing evidence is not converted into Neutral.
-   Frontend company switching returns the correct company's results.
-   The system can handle a changing universe size without hard-coded
    `2409`.
-   The application can show batch progress.
-   Re-running a batch does not unnecessarily re-fetch unchanged
    documents.
-   No fabricated evidence is accepted.

## Very important instruction

Do not simply "add the Excel content to the prompt" and assume the
problem is solved.

The real fix is architectural:

**Universe → company registry → document/evidence retrieval → task
processing → persisted results → API → frontend.**

The Markdown file provides context. The database and batch research
pipeline provide the actual multi-company capability.

Start by inspecting the current project and then implement the smallest
complete version of this architecture, beginning with E1 and making it
work for the full NSE universe.
