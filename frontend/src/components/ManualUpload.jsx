import React, { useEffect, useRef, useState } from 'react';
import { authFetch, API_BASE } from '../lib/api.js';

const IconUpload = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v12M8 7l4-4 4 4M4 21h16" />
  </svg>
);
const IconCheck = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 6L9 17l-5-5" />
  </svg>
);
const IconX = () => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
);

// Every upload field accepts the same broad set of formats the backend
// ingestion pipeline (tools/manual_document_pipeline.py's _ALLOWED_FORMATS)
// can actually extract text/facts from - the document category (Annual
// Report, XBRL Filing, Shareholding Pattern, ...) is independent of the
// file's physical format, so no field restricts to a narrower subset.
const SUPPORTED_FILE_ACCEPT =
  '.pdf,.xml,.xbrl,.xlsx,.xls,.csv,.docx,.pptx,.txt,.html,.htm,application/pdf,text/xml,application/xml,' +
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,' +
  'text/csv,application/vnd.openxmlformats-officedocument.wordprocessingml.document,' +
  'application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain,text/html';

function FileSlot({ label, required, file, onChange, accept = SUPPORTED_FILE_ACCEPT }) {
  return (
    <div className="nv-card p-3.5">
      <div className="flex items-center justify-between mb-2 gap-2">
        <span className="text-[13px] font-semibold text-slate-200">{label}{required && <span className="text-slate-500 font-normal"> (required)</span>}</span>
        {file && <span className="text-emerald-400 flex-shrink-0"><IconCheck /></span>}
      </div>
      {file ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-slate-700 px-3 py-2.5">
          <span className="text-[12.5px] text-slate-300 truncate flex-1">{file.name}</span>
          <span className="text-[11px] text-slate-500 flex-shrink-0">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
          <button
            type="button"
            onClick={() => onChange(null)}
            title="Remove file"
            className="text-slate-500 hover:text-red-400 flex-shrink-0"
          >
            <IconX />
          </button>
        </div>
      ) : (
        <label className="flex items-center gap-2.5 rounded-xl border border-dashed border-slate-700 hover:border-blue-600/60 px-3 py-2.5 cursor-pointer transition-colors">
          <IconUpload />
          <span className="text-[12.5px] text-slate-300 truncate">Choose File...</span>
          <input type="file" accept={accept} className="hidden" onChange={(e) => onChange(e.target.files?.[0] || null)} />
        </label>
      )}
    </div>
  );
}

function MultiFileSlot({ label, files, onChange, accept = SUPPORTED_FILE_ACCEPT, description }) {
  const addFiles = (newFiles) => {
    // Multiple selections accumulate rather than replace, so choosing files
    // in two separate picks (or picking one at a time) still ends with all
    // of them attached.
    const merged = [...files];
    for (const f of newFiles) {
      if (!merged.some((existing) => existing.name === f.name && existing.size === f.size)) merged.push(f);
    }
    onChange(merged);
  };
  const removeFile = (idx) => onChange(files.filter((_, i) => i !== idx));

  return (
    <div className="nv-card p-3.5">
      <div className="flex items-center justify-between mb-1.5 gap-2">
        <span className="text-[13px] font-semibold text-slate-200">{label}</span>
        {files.length > 0 && <span className="text-emerald-400 flex-shrink-0"><IconCheck /></span>}
      </div>
      {description && <p className="text-[11px] text-slate-500 mb-2 leading-relaxed">{description}</p>}
      {files.length > 0 && (
        <div className="space-y-1 mb-2">
          {files.map((f, i) => (
            <div key={`${f.name}-${f.size}-${i}`} className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/50 px-2.5 py-1.5">
              <span className="text-emerald-400 flex-shrink-0"><IconCheck /></span>
              <span className="text-[12px] text-slate-300 truncate flex-1">{f.name}</span>
              <button type="button" onClick={() => removeFile(i)} title="Remove file" className="text-slate-500 hover:text-red-400 flex-shrink-0">
                <IconX />
              </button>
            </div>
          ))}
        </div>
      )}
      <label className="flex items-center gap-2.5 rounded-xl border border-dashed border-slate-700 hover:border-blue-600/60 px-3 py-2.5 cursor-pointer transition-colors">
        <IconUpload />
        <span className="text-[12.5px] text-slate-300 truncate">Choose File(s)...</span>
        <input type="file" multiple accept={accept} className="hidden" onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ''; }} />
      </label>
    </div>
  );
}

const PROGRESS_STEPS = [
  'Reading Annual Report',
  'Reading XBRL filing',
  'Identifying financial statements',
  'Identifying required Fundamental data',
  'Identifying required Qualitative evidence',
  'Calculating results',
];

function ProgressChecklist({ arDone, xbrlIncluded, stepIndex }) {
  return (
    <div className="mt-4 nv-card p-4 space-y-2">
      <div className="flex items-center gap-2 text-[12.5px]">
        <span className="text-emerald-400"><IconCheck /></span>
        <span className="text-slate-300">Annual Report uploaded</span>
      </div>
      {xbrlIncluded && (
        <div className="flex items-center gap-2 text-[12.5px]">
          <span className="text-emerald-400"><IconCheck /></span>
          <span className="text-slate-300">NSE/BSE XBRL uploaded</span>
        </div>
      )}
      {PROGRESS_STEPS.filter((_, i) => xbrlIncluded || i !== 1).map((step, i) => {
        const idx = xbrlIncluded ? i : (i >= 1 ? i + 1 : i);
        const done = idx < stepIndex;
        const active = idx === stepIndex;
        return (
          <div key={step} className="flex items-center gap-2 text-[12.5px]">
            {done ? <span className="text-emerald-400"><IconCheck /></span> : active ? <span className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" /> : <span className="w-3.5 h-3.5" />}
            <span className={done ? 'text-slate-300' : active ? 'text-slate-200 font-medium' : 'text-slate-600'}>{step}…</span>
          </div>
        );
      })}
    </div>
  );
}

// UPLOAD DOCUMENTS -> ANALYSE -> the NEW document-analysis workflow.
// Annual Report (required) + NSE/BSE XBRL (optional) are uploaded, then the
// NEW document-analysis engine (tools/document_analysis_engine.py) runs - 
// its own broad extraction for Fundamental, the existing A-U framework's
// own compute_fn's for Qualitative. Hands off to the separate
// DocumentAnalysis workspace, never the old ratio-fetching dashboard.
export default function ManualUpload({ symbol, onClose, onOpenDashboard }) {
  const [arFile, setArFile] = useState(null);
  const [xbrlFile, setXbrlFile] = useState(null);
  const [shareholdingFile, setShareholdingFile] = useState(null);
  const [insiderTradingFiles, setInsiderTradingFiles] = useState([]);
  const [corporateActionsFiles, setCorporateActionsFiles] = useState([]);
  const [governanceFile, setGovernanceFile] = useState(null);
  const [brsrFile, setBrsrFile] = useState(null);
  const [investorPresentationFile, setInvestorPresentationFile] = useState(null);
  const [earningsCallFile, setEarningsCallFile] = useState(null);
  const [creditRatingFile, setCreditRatingFile] = useState(null);
  const [otherDocsFiles, setOtherDocsFiles] = useState([]);
  const [phase, setPhase] = useState('idle'); // idle | analysing | error
  const [error, setError] = useState(null);
  const [stepIndex, setStepIndex] = useState(0);
  const stepTimer = useRef(null);

  useEffect(() => () => clearInterval(stepTimer.current), []);

  // Explicit state machine: idle (form) -> analysing (progress) -> either
  // back to idle's caller via onOpenDashboard+onClose on real success, or
  // error (its own dedicated screen, never the form again). The bug this
  // fixes: 'error' used to fall into the SAME render branch as 'idle'
  // (both matched `phase !== 'analysing'`), so a failed/expired request
  // re-rendered the entire 5-field upload form with only a small red line
  // appended below it - indistinguishable from "the upload modal reopened".

  // Reads the response ONCE as raw text (a body can only be consumed once),
  // then tries JSON.parse on that text - never res.json() directly, since
  // that swallows the actual body on a parse failure and leaves nothing to
  // show the user beyond a generic "invalid response" message. On failure,
  // the thrown error always carries the real HTTP status and either the
  // parsed error detail or the raw response text, never a guess.
  const parseResponse = async (res, label) => {
    const raw = await res.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch (e) {
      console.log(`[ANALYSIS] ${label} response was not valid JSON. status=${res.status} ${res.statusText}, body:`, raw.slice(0, 500));
    }
    console.log(`[ANALYSIS] ${label} response`, { status: res.status, statusText: res.statusText, url: res.url, body: data ?? raw });
    return { ok: res.ok, status: res.status, statusText: res.statusText, data, raw };
  };

  const analyse = async () => {
    if (!canAnalyse) return;
    console.log('[UPLOAD] analyse clicked, validation passed');
    setPhase('analysing');
    setError(null);
    setStepIndex(0);
    stepTimer.current = setInterval(() => setStepIndex((i) => Math.min(i + 1, 5)), 900);
    try {
      const form = new FormData();
      form.append('annual_report', arFile);
      if (xbrlFile) form.append('xbrl', xbrlFile);
      if (shareholdingFile) form.append('shareholding_pattern', shareholdingFile);
      // Each sent under its own field so the backend can tag the correct
      // document_type and actually extract their text (previously both
      // merged into one 'additional_filings' field the backend never
      // classified or processed at all - confirmed real: those uploads
      // sat unprocessed and invisible to both the Document Coverage panel
      // and the qualitative engine).
      for (const f of insiderTradingFiles) form.append('insider_trading_filings', f);
      for (const f of corporateActionsFiles) form.append('corporate_actions_filings', f);
      // Qualitative supporting documents - all optional, none gate Analyse.
      if (governanceFile) form.append('corporate_governance_report', governanceFile);
      if (brsrFile) form.append('brsr_esg_report', brsrFile);
      if (investorPresentationFile) form.append('investor_presentation', investorPresentationFile);
      if (earningsCallFile) form.append('earnings_call_transcript', earningsCallFile);
      if (creditRatingFile) form.append('credit_rating_report', creditRatingFile);
      for (const f of otherDocsFiles) form.append('other_supporting_documents', f);
      if (symbol) form.append('symbol', symbol);

      console.log('[ANALYSIS] upload request started: POST /api/v1/documents/analyse');
      const res = await authFetch('/api/v1/documents/analyse', { method: 'POST', body: form });
      const upload = await parseResponse(res, 'upload');
      const data = upload.data;
      if (!upload.ok || !data || !data.symbol) {
        const detail = (data && data.detail)
          || (upload.raw && upload.raw.trim() ? upload.raw.slice(0, 300) : null)
          || 'no response body';
        throw new Error(`Document upload failed: HTTP ${upload.status} ${upload.statusText || ''} - ${detail}`.trim());
      }
      // The optional qualitative supporting documents (Corporate Governance
      // Report, BRSR/ESG, Investor Presentation, Earnings Call Transcript,
      // Credit Rating Report, Other) never gate Analyse, but a per-document
      // failure here (e.g. an unextractable file) should still be visible
      // for diagnosis rather than silently discarded.
      if (data.qualitative_documents) {
        for (const [docType, docResult] of Object.entries(data.qualitative_documents)) {
          if (docResult && docResult.error) {
            console.warn(`[ANALYSIS] supporting document "${docType}" was not consumed:`, docResult.error);
          }
        }
      }

      console.log('[ANALYSIS] run request started: POST /api/v1/document-analysis/run for', data.symbol);
      const runRes = await authFetch('/api/v1/document-analysis/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: data.symbol, name: data.name }),
      });
      const run = await parseResponse(runRes, 'run');
      const runData = run.data;
      // HTTP 200 alone is never treated as success - the response body must
      // actually be a valid, complete Fundamental result (all 68 ratios
      // persisted) before this is called a success and the modal closes.
      if (!run.ok || !runData || !runData.symbol || !runData.fundamental
          || runData.fundamental.total !== 68) {
        const detail = (runData && runData.detail)
          || (run.raw && run.raw.trim() ? run.raw.slice(0, 300) : null)
          || 'no response body';
        throw new Error(`Analysis failed: HTTP ${run.status} ${run.statusText || ''} - ${detail}`.trim());
      }

      console.log('[ANALYSIS] success, fundamental total:', runData.fundamental.total);
      clearInterval(stepTimer.current);
      setStepIndex(6);
      console.log('[NAVIGATION] navigating to results for', data.symbol);
      onOpenDashboard?.(data.symbol, data.name);
      onClose();
    } catch (e) {
      console.log('[ANALYSIS] failure:', e.message);
      clearInterval(stepTimer.current);
      // A raw "Failed to fetch" means the browser never got an HTTP response
      // at all (backend down, crashed mid-request, or unreachable) - the
      // generic browser string alone gives no clue where to look, so name
      // the backend URL it was trying to reach, same treatment as the
      // login screen's connection-failure message.
      const message = (e && e.message === 'Failed to fetch')
        ? `Cannot reach the analysis server. Make sure the backend is running on ${API_BASE}.`
        : (e.message || 'Analysis failed.');
      setError(message);
      setPhase('error');
    }
  };

  const retry = () => { setError(null); analyse(); };
  const editDocuments = () => { setPhase('idle'); setError(null); };

  // Fundamental (68-ratio) requirement: Annual Report ONLY. Every ratio
  // that's calculable from Annual Report + market data must work without
  // XBRL/Shareholding Pattern - those are optional supplementary sources
  // (XBRL as a cross-check, Shareholding Pattern only for the handful of
  // ratios that genuinely need it, e.g. Promoter Pledge/Free Float). See
  // tools/document_analysis_engine.py/tools/manual_mode.py - the backend
  // already treats them as optional (`if xbrlFile`/`if shareholdingFile`
  // below), this gate must match. Corporate Announcements/Actions/Insider
  // Trading are unrelated optional documents and never gate Analyse either.
  const canAnalyse = !!arFile;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-8" onClick={phase === 'analysing' ? undefined : onClose}>
      <div
        className="nv-card nv-elev w-full max-w-md rounded-2xl p-5 max-h-full flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-1 flex-shrink-0">
          <h2 className="nv-h1 text-[16px] text-slate-100">Upload Documents{symbol ? ` - ${symbol}` : ''}</h2>
          {phase !== 'analysing' && <button onClick={onClose} className="nv-icon-btn w-7 h-7 !border-0 text-slate-500">✕</button>}
        </div>

        <div className="overflow-y-auto flex-1 min-h-0">
          {phase === 'idle' && (
            <>
              <p className="text-[12px] text-slate-500 mb-4">
                {symbol
                  ? `Navrist AI searches these for whatever the existing Fundamental and Qualitative (A-U) framework requires - no need to say where anything is.`
                  : `No company needs to be picked first - the Annual Report itself says who it's for. Navrist AI searches both documents for whatever the existing Fundamental and Qualitative (A-U) framework requires.`}
              </p>
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500 mb-2">Required Document</p>
              <div className="space-y-3">
                <FileSlot label="Annual Report" required file={arFile} onChange={(f) => { setArFile(f); setError(null); }} />
              </div>
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500 mb-2 mt-4">Supplementary Documents (Optional)</p>
              <div className="space-y-3">
                <FileSlot label="NSE/BSE Financial XBRL Filing" file={xbrlFile} onChange={(f) => { setXbrlFile(f); setError(null); }} />
                <FileSlot label="Shareholding Pattern Filing" file={shareholdingFile} onChange={(f) => { setShareholdingFile(f); setError(null); }} />
              </div>

              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500 mt-5 mb-2">Qualitative Supporting Documents (optional)</p>
              <div className="space-y-3">
                <FileSlot label="Corporate Governance Report" file={governanceFile} onChange={(f) => { setGovernanceFile(f); setError(null); }} />
                <FileSlot label="BRSR / ESG Report" file={brsrFile} onChange={(f) => { setBrsrFile(f); setError(null); }} />
                <FileSlot label="Investor Presentation" file={investorPresentationFile} onChange={(f) => { setInvestorPresentationFile(f); setError(null); }} />
                <FileSlot label="Earnings Call Transcript" file={earningsCallFile} onChange={(f) => { setEarningsCallFile(f); setError(null); }} />
                <FileSlot label="Credit Rating Report" file={creditRatingFile} onChange={(f) => { setCreditRatingFile(f); setError(null); }} />
                <MultiFileSlot
                  label="Insider Trading / Regulation 7(2) Filing"
                  files={insiderTradingFiles}
                  onChange={(files) => { setInsiderTradingFiles(files); setError(null); }}
                />
                <MultiFileSlot
                  label="Corporate Announcements / Corporate Actions"
                  files={corporateActionsFiles}
                  onChange={(files) => { setCorporateActionsFiles(files); setError(null); }}
                />
                <MultiFileSlot
                  label="Other Supporting Documents"
                  description="Upload additional official company or exchange documents such as Secretarial Compliance Reports, company policies, Regulation 30 disclosures, Related Party disclosures, Risk Management documents, Materiality documents and other relevant regulatory filings."
                  files={otherDocsFiles}
                  onChange={(files) => { setOtherDocsFiles(files); setError(null); }}
                />
              </div>
            </>
          )}

          {phase === 'analysing' && (
            <>
              <p className="text-[12px] text-slate-500 mb-1 uppercase tracking-wide font-semibold">Analysing Documents</p>
              <ProgressChecklist arDone xbrlIncluded={!!xbrlFile} stepIndex={stepIndex} />
            </>
          )}

          {phase === 'error' && (
            <div className="nv-card p-4 border-red-500/30 bg-red-500/5">
              <p className="text-[12px] text-red-400 font-semibold uppercase tracking-wide mb-1.5">Analysis Failed</p>
              <p className="text-[13px] text-slate-300 leading-relaxed">{error}</p>
              <p className="text-[11.5px] text-slate-500 mt-3">
                Your selected documents are still attached. You can retry the same analysis, or go back to change them.
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-5 flex-shrink-0">
          {phase === 'idle' && <button onClick={onClose} className="nv-btn nv-btn-ghost h-9 px-3.5 text-[13px]">Cancel</button>}
          {phase === 'idle' && (
            <button onClick={analyse} disabled={!canAnalyse} className="nv-btn nv-btn-primary h-9 px-5 text-[13px] disabled:opacity-50">
              Analyse
            </button>
          )}
          {phase === 'error' && <button onClick={onClose} className="nv-btn nv-btn-ghost h-9 px-3.5 text-[13px]">Cancel</button>}
          {phase === 'error' && <button onClick={editDocuments} className="nv-btn nv-btn-ghost h-9 px-3.5 text-[13px]">Edit Documents</button>}
          {phase === 'error' && (
            <button onClick={retry} className="nv-btn nv-btn-primary h-9 px-5 text-[13px]">
              Retry Analysis
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
