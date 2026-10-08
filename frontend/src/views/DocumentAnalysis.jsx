import React, { useEffect, useState } from 'react';
import { authFetch } from '../lib/api.js';
import { groupFundamentalRatios } from '../lib/ratioCategories.js';
import ManualUpload from '../components/ManualUpload.jsx';
import { QualChart } from '../components/QualCharts.jsx';
import navristLogo from '../assets/navrist-logo.svg';

const IconSearch = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
  </svg>
);

const IconArrowLeft = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 12H5M12 19l-7-7 7-7" />
  </svg>
);
const IconChevron = ({ open }) => (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>
    <path d="M9 18l6-6-6-6" />
  </svg>
);


function fmtRatioValue(r) {
  if (r.value == null) return '-';
  const v = Number(r.value);
  if (r.unit === '%') return `${v.toFixed(2)}%`;
  if (r.unit === 'x') return `${v.toFixed(2)}x`;
  if (r.unit === '₹ Cr') return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
  return v.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function FundamentalCard({ r, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  // `_metadata` is a marker entry (not a real financial input) carrying
  // calculation_type/derived_from - the backend nests it inside `inputs`
  // rather than as its own DB column (db/006_document_analysis.sql's
  // `fundamental_analysis_results` table has a fixed column set; adding
  // top-level keys broke the Supabase upsert). Split it out here so it
  // renders as its own labeled section instead of leaking through as a
  // garbage "_metadata: -" row in the plain inputs list below.
  const allInputs = r.inputs || [];
  const metaEntry = allInputs.find((inp) => inp.name === '_metadata');
  const visibleInputs = allInputs.filter((inp) => !inp.name?.startsWith('_'));
  const derivedFrom = metaEntry?.derived_from;
  const reason = metaEntry?.reason;

  return (
    <div className="nv-card overflow-hidden">
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center gap-2.5 px-3.5 py-3 text-left">
        <IconChevron open={open} />
        <span className="text-[12.5px] font-semibold text-slate-300 flex-1 truncate">{r.label}</span>
        <span className="text-[15px] font-bold text-slate-100 nv-num">{fmtRatioValue(r)}</span>
      </button>
      {open && (
        <div className="px-3.5 pb-3.5 pt-1 text-[12px] text-slate-400 space-y-1.5 border-t border-slate-800/60">
          <p className="pt-2.5"><span className="text-slate-500">Formula:</span> {r.formula}</p>
          {reason && r.value == null && (
            <p className="text-slate-500">
              {reason}
            </p>
          )}
          {visibleInputs.map((inp) => (
            <p key={inp.name}>
              <span className="text-slate-500">{inp.name.replace(/_/g, ' ')}:</span>{' '}
              {inp.value != null ? Number(inp.value).toLocaleString('en-IN') : '-'}
              {(inp.source_type || inp.source) && (
                <span className="text-slate-600">
                  {' '}- {inp.source_type || inp.source}
                  {inp.page && inp.page !== 'Not available' ? `, p.${inp.page}` : ''}
                </span>
              )}
              {inp.source_file && inp.source_file !== 'Not available' && (
                <span className="block text-slate-700 text-[11px] pl-2">↳ {inp.source_file}</span>
              )}
            </p>
          ))}
          {derivedFrom && derivedFrom.length > 0 && (
            <div className="pt-1.5 border-t border-slate-800/40 mt-1.5">
              <p className="text-slate-500 mb-1">Derived from:</p>
              {derivedFrom.map((d) => (
                <p key={d.ratio_key} className="pl-2">
                  <span className="text-slate-400">{d.ratio}</span>{' '}
                  <span className="text-slate-100 nv-num">{d.value != null ? Number(d.value).toLocaleString('en-IN') : '-'}{d.unit ? ` ${d.unit}` : ''}</span>
                  <span className="text-slate-600"> ({d.formula})</span>
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FundamentalTab({ symbol, query }) {
  const [results, setResults] = useState(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    authFetch(`/api/v1/document-analysis/${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setResults(d.fundamental || []); })
      .catch(() => setResults([]));
    return () => { cancelled = true; };
  }, [symbol]);

  if (results === null) return <p className="text-[13px] text-slate-600 text-center py-10">Loading...</p>;
  if (results.length === 0) return <p className="text-[13px] text-slate-600 text-center py-10">No Fundamental results yet.</p>;

  // "Not Disclosed" (this filer's Annual Report/XBRL genuinely never
  // states the underlying line item) is hidden by default, the same
  // rule already applied on the Qualitative tab - it varies filer to
  // filer, so it's noise rather than a finding. Not Applicable and
  // Insufficient Data stay visible: both are themselves meaningful
  // classifications (e.g. NPA ratios on a non-bank), not an absence of
  // data. Generic across every company - no ticker-specific logic.
  const HIDDEN_STATUSES = new Set(['not_disclosed']);
  const visibleResults = results.filter((r) => !HIDDEN_STATUSES.has(r.status));
  const hiddenCount = results.length - visibleResults.length;

  const q = (query || '').trim().toLowerCase();
  const filtered = q ? visibleResults.filter((r) => r.label.toLowerCase().includes(q)) : visibleResults;
  if (q && filtered.length === 0) {
    return <p className="text-[13px] text-slate-600 text-center py-10">No ratio matches "{query}".</p>;
  }

  const { priority, primary, more } = groupFundamentalRatios(filtered);
  // A search must be able to land on any ratio, so it opens the extra
  // categories on its own; otherwise they sit behind "Show More Ratios".
  const showMore = expanded || !!q;
  const moreCount = more.reduce((n, g) => n + g.items.length, 0);
  // the first 13 (backend `display_priority`) are plain cards of the same list - no heading of their own
  const renderPriority = () => (
    <div data-priority-ratios className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
      {priority.map((r) => <FundamentalCard key={r.ratio_key} r={r} defaultOpen={!!q} />)}
    </div>
  );
  const renderGroup = (g) => (
    <div key={g.category} data-category={g.category}>
      <div className="flex items-baseline gap-2 mb-2.5 pb-1.5 border-b border-slate-800">
        <h3 className="text-[13px] font-bold text-blue-300 uppercase tracking-wide border-l-4 border-blue-500 pl-2.5">{g.category}</h3>
        <span className="text-[11px] text-slate-500">{g.items.length} ratio{g.items.length === 1 ? '' : 's'}</span>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {g.items.map((r) => <FundamentalCard key={r.ratio_key} r={r} defaultOpen={!!q} />)}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {hiddenCount > 0 && (
        <p className="text-[11px] text-slate-600 -mt-2">
          {hiddenCount} ratio{hiddenCount === 1 ? '' : 's'} not disclosed for this company - hidden from view.
        </p>
      )}
      {priority.length > 0 && renderPriority()}
      {primary.map(renderGroup)}
      {moreCount > 0 && !q && (
        <button type="button" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}
          className="w-full sm:w-auto px-5 py-2.5 rounded-lg border border-blue-500/40 bg-blue-500/10 hover:bg-blue-500/20 text-blue-200 text-[13px] font-bold transition">
          {expanded ? 'Show Fewer Ratios' : `Show More Ratios (${moreCount})`}
        </button>
      )}
      {showMore && more.map(renderGroup)}
    </div>
  );
}

// Final, user-facing status vocabulary (mapped server-side from the
// engine's internal tags - see tools/qualitative_db.py's
// `to_user_facing_status` - so SEARCH_INCONCLUSIVE/NOT_FOUND/
// SINGLE_SOURCE/etc. never reach this component as raw debug strings).
const QUAL_STATUS_LABEL = {
  VERIFIED: 'Verified',
  NEEDS_REVIEW: 'Needs Review',
  NOT_DISCLOSED: 'Not Disclosed',
  DATA_MISSING: 'Data Missing',
  NOT_APPLICABLE: 'Not Applicable',
  INSUFFICIENT_DATA: 'Insufficient Data',
};
// Card ordering within a section: real fetched/verified data first, then
// items that need a document that wasn't uploaded (actionable), then items
// genuinely searched and found nothing, Not Applicable last (nothing to
// action, not even worth an upload prompt).
const TIER = {
  VERIFIED: 0,
  NEEDS_REVIEW: 0,
  DATA_MISSING: 1,
  NOT_DISCLOSED: 2,
  INSUFFICIENT_DATA: 2,
  NOT_APPLICABLE: 3,
};

const QUAL_STATUS_STYLE = {
  VERIFIED: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  NEEDS_REVIEW: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  NOT_DISCLOSED: 'text-slate-500 bg-slate-850 border-slate-800',
  DATA_MISSING: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
  NOT_APPLICABLE: 'text-slate-500 bg-slate-850 border-slate-800',
  INSUFFICIENT_DATA: 'text-slate-500 bg-slate-850 border-slate-800',
};

// `pathway_results` (when present) is the qualitative engine's own
// per-KPI evidence trail - [{pathway_id, source, result, note, page,
// source_file}, ...], one entry per extraction attempt (see
// tools/qualitative_engine.py's "never stop at the first pathway" rule).
// Only pathways that actually found/checked something are worth showing -
// a bare CHECKED-but-empty entry with no source/note adds nothing. This is
// the qualitative-tab equivalent of the fundamental tab's per-input
// source/page/file trail (FundamentalCard above) - previously dropped
// entirely here, the same "Metadata - -" class of bug already fixed on
// the fundamental card.
function _usefulPathways(pathwayResults) {
  if (!Array.isArray(pathwayResults)) return [];
  return pathwayResults.filter((p) => p && (p.source || p.note || p.page));
}

// Universal-engine-produced rows (tools/qualitative_task_engine.py's
// QualitativeResult.to_payload()) carry `_engine: "qualitative_task_engine"`
// plus a richer, structurally different provenance/score shape than the
// legacy compute_fn payloads (`pathway_results`, no `score`/`confidence_tier`/
// `provenance` list). Both shapes render through the SAME card - this flag
// only decides which additional sections to show; no score/status/confidence
// is ever computed here, only formatted for display.
function _isUniversalEngineRow(payload) {
  return payload && payload._engine === 'qualitative_task_engine';
}

const CONFIDENCE_TIER_STYLE = {
  HIGH: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  MEDIUM: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  LOW: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
  UNKNOWN: 'text-slate-500 bg-slate-850 border-slate-800',
};

function fmtScore(score, scale) {
  if (score == null) return null;
  if (scale === 'percent') return `${Number(score).toFixed(2)}%`;
  if (scale === 'score(1-5)') return `${score} / 5`;
  if (scale === 'categorical') return String(score);
  return String(score);
}

// Confidence is displayed as its OWN indicator, deliberately separate from
// the score/status badge above it - a weak/negative finding can carry HIGH
// confidence and an unknown finding carries LOW/UNKNOWN confidence; this
// component never infers one from the other, it only renders both fields
// exactly as the backend computed them.
function ConfidenceIndicator({ tier, reason }) {
  if (!tier) return null;
  return (
    <span
      title={reason || undefined}
      className={`text-[9.5px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5 border ${CONFIDENCE_TIER_STYLE[tier] || CONFIDENCE_TIER_STYLE.UNKNOWN}`}
    >
      Confidence: {tier}
    </span>
  );
}

// Evidence/provenance cards - one per QualitativeEvidence the backend
// collected, showing exactly what it found and where (source document
// type, page, excerpt, extraction method) so the user can answer "why did
// the system say this?" without re-running anything.
function EvidenceCard({ p }) {
  return (
    <div className="rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2 space-y-1">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[10px] font-semibold text-slate-400">
          {(p.source_document_type || 'source').replace(/_/g, ' ')}
        </span>
        {p.page_number != null && <span className="text-[10px] text-slate-600">p.{p.page_number}</span>}
        {p.extraction_method && <span className="text-[10px] text-slate-700">({p.extraction_method.replace(/_/g, ' ')})</span>}
      </div>
      {p.extracted_text && <p className="text-[11.5px] text-slate-400 italic">&ldquo;{p.extracted_text}&rdquo;</p>}
      {p.evidence_date && <p className="text-[10px] text-slate-600">As of {p.evidence_date}</p>}
    </div>
  );
}

function DataMissingUpload({ symbol, requiredDocument, onUploaded }) {
  const [state, setState] = useState('idle'); // idle | uploading | error
  const [errMsg, setErrMsg] = useState('');
  const inputRef = React.useRef(null);

  const handleFile = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    setState('uploading');
    setErrMsg('');
    try {
      const form = new FormData();
      form.append('required_document', requiredDocument || 'Other Supporting Document');
      form.append('file', file);
      const res = await authFetch(`/api/v1/documents/${encodeURIComponent(symbol)}/add-supporting`, {
        method: 'POST', body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed (HTTP ${res.status})`);
      }
      setState('idle');
      onUploaded && onUploaded();
    } catch (e) {
      setState('error');
      setErrMsg(e.message || 'Upload failed');
    }
  };

  return (
    <div className="pt-1" onClick={(e) => e.stopPropagation()}>
      <input ref={inputRef} type="file" className="hidden" onChange={handleFile} />
      <button
        type="button"
        disabled={state === 'uploading'}
        onClick={() => inputRef.current && inputRef.current.click()}
        className="text-[11px] font-semibold rounded px-2 py-1 border border-sky-500/40 text-sky-400 hover:bg-sky-500/10 disabled:opacity-50"
      >
        {state === 'uploading' ? 'Uploading & re-analysing...' : `Upload ${requiredDocument || 'document'}`}
      </button>
      {state === 'error' && <p className="text-[10.5px] text-red-400 pt-1">{errMsg}</p>}
    </div>
  );
}

function QualitativeCard({ row, meta, defaultOpen = false, symbol, onUploaded }) {
  const [open, setOpen] = useState(defaultOpen);
  const payload = row.payload || {};
  const text = payload.rationale || payload.description || payload.evidence || payload.recurring_description || '';
  const pathways = _usefulPathways(payload.pathway_results);
  const isUniversal = _isUniversalEngineRow(payload);
  const scoreLabel = isUniversal ? fmtScore(payload.score, payload.score_scale) : null;
  const evidenceCards = isUniversal && Array.isArray(payload.provenance) ? payload.provenance : [];

  return (
    <div className="nv-card overflow-hidden">
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center gap-3 p-3.5 text-left">
        <div className="flex-1 min-w-0 self-stretch flex flex-col justify-between">
          <div className="flex items-center gap-1.5">
            <IconChevron open={open} />
            <span className="text-[13px] font-semibold text-slate-300 truncate">{meta?.title || row.subpoint_id}</span>
          </div>
          <div className="flex items-center gap-1.5 pl-[19px] pt-0.5 flex-wrap">
            <span className={`text-[9.5px] font-semibold uppercase tracking-wide rounded px-1.5 py-0.5 border ${QUAL_STATUS_STYLE[row.confidence_tag] || QUAL_STATUS_STYLE.NOT_DISCLOSED}`}>
              {QUAL_STATUS_LABEL[row.confidence_tag] || row.confidence_tag}
            </span>
            {scoreLabel && (
              <span className="text-[9.5px] font-semibold rounded px-1.5 py-0.5 border text-slate-300 bg-slate-800/60 border-slate-700">
                Score: {scoreLabel}
              </span>
            )}
            {isUniversal && <ConfidenceIndicator tier={payload.confidence_tier} reason={payload.confidence_reason} />}
          </div>
        </div>
        <div className="flex-shrink-0 pl-2 border-l border-slate-800/60">
          <QualChart payload={payload} confidenceTag={row.confidence_tag} title={meta?.title} />
        </div>
      </button>
      {open && (
        <div className="px-3.5 pb-3.5 pt-0.5 text-[12px] text-slate-400 space-y-1.5 border-t border-slate-800/60">
          {['VERIFIED', 'INSUFFICIENT_DATA', 'NEEDS_REVIEW', 'SINGLE_SOURCE', 'MULTI_SOURCE'].includes(row.confidence_tag) && (
            <div className="pt-2.5 pb-1">
              <QualChart payload={payload} confidenceTag={row.confidence_tag} title={meta?.title} full />
            </div>
          )}
          {row.confidence_tag !== 'VERIFIED' && text && (
            <p className="pt-2.5 text-amber-300/90 bg-amber-500/5 border border-amber-500/15 rounded px-2 py-1.5">
              {text}
            </p>
          )}
          {row.confidence_tag === 'VERIFIED' && (
            <p className="pt-2.5">{text || 'No evidence text on this result.'}</p>
          )}
          {payload.required_document && (
            <div className="space-y-1">
              <p className="text-sky-400">Upload: {payload.required_document}</p>
              {symbol && (
                <DataMissingUpload symbol={symbol} requiredDocument={payload.required_document} onUploaded={onUploaded} />
              )}
            </div>
          )}
          {evidenceCards.length > 0 && (
            <div className="pt-1.5 border-t border-slate-800/40 mt-1.5 space-y-1.5">
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500">Evidence</p>
              {evidenceCards.map((p, i) => <EvidenceCard key={p.evidence_id || i} p={p} />)}
            </div>
          )}
          {pathways.length > 0 && (
            <div className="pt-1.5 border-t border-slate-800/40 mt-1.5 space-y-1.5">
              {pathways.map((p, i) => (
                <p key={p.pathway_id || i}>
                  {p.pathway_id && <span className="text-slate-500">{p.pathway_id}:</span>}{' '}
                  {p.result && <span className="text-slate-300">{p.result}</span>}
                  {p.note && <span> - {p.note}</span>}
                  {(p.source || p.page) && (
                    <span className="text-slate-600">
                      {' '}({p.source || 'Annual Report'}{p.page ? `, p.${p.page}` : ''})
                    </span>
                  )}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const QUAL_DOC_LABELS = {
  annual_report: 'Annual Report',
  corporate_governance_report: 'Corporate Governance Report',
  brsr_esg_report: 'BRSR / ESG Report',
  investor_presentation: 'Investor Presentation',
  earnings_call_transcript: 'Earnings Call Transcript',
  credit_rating_report: 'Credit Rating Report',
  corporate_actions: 'Corporate Actions History (BSE/NSE)',
  shareholding_pattern_filing: 'Shareholding Pattern Filing',
  insider_trading_disclosures: 'Insider Trading Disclosures',
  quarterly_corporate_governance_filing: 'Quarterly Corporate Governance Filing',
  other_supporting_document: 'Other Supporting Documents',
};

function DocumentCoverage({ symbol }) {
  const [coverage, setCoverage] = useState(null);
  useEffect(() => {
    let cancelled = false;
    authFetch(`/api/v1/documents/coverage/${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setCoverage(d.coverage || null); })
      .catch(() => setCoverage(null));
    return () => { cancelled = true; };
  }, [symbol]);

  if (!coverage) return null;

  return (
    <div className="nv-card p-3.5 mb-5">
      <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500 mb-2.5">Document Coverage</p>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(QUAL_DOC_LABELS).map(([key, label]) => {
          const uploaded = coverage[key]?.uploaded;
          return (
            <span
              key={key}
              className={`text-[10.5px] font-medium rounded px-2 py-1 border ${
                uploaded ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-slate-500 bg-slate-850 border-slate-800'
              }`}
            >
              {label}: {uploaded ? 'Uploaded' : 'Missing'}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function QualitativeTab({ symbol, query }) {
  const [rows, setRows] = useState(null);
  const [framework, setFramework] = useState({});
  const loadData = React.useCallback(() => {
    let cancelled = false;
    Promise.all([
      authFetch(`/api/v1/qualitative/${encodeURIComponent(symbol)}`).then((r) => r.json()),
      authFetch('/api/v1/qualitative-framework').then((r) => r.json()),
    ]).then(([q, fw]) => {
      if (cancelled) return;
      const computed = {};
      for (const row of (q.results || [])) computed[row.subpoint_id] = row;
      // Show the COMPLETE A-U framework, not just what's already computed -
      // an item this analysis hasn't run yet (not implemented, or a derived
      // rollup) still appears rather than disappearing. Uses the SAME
      // final six-state vocabulary as every computed row (never a separate
      // "NOT_COMPUTED" internal tag) - a genuinely un-persisted KPI is, from
      // the user's perspective, indistinguishable from one that was
      // searched and found nothing, so it gets the same honest label and
      // reason instead of a raw debug string leaking into the badge.
      const merged = Object.entries(fw || {}).map(([taskId, meta]) => (
        computed[taskId] || {
          subpoint_id: taskId, confidence_tag: 'NOT_DISCLOSED',
          payload: { rationale: 'This item has not been computed for this company yet.' },
        }
      ));
      setRows(merged);
      setFramework(fw || {});
    }).catch(() => setRows([]));
    return () => { cancelled = true; };
  }, [symbol]);
  useEffect(() => loadData(), [loadData]);

  if (rows === null) return <p className="text-[13px] text-slate-600 text-center py-10">Loading...</p>;
  if (rows.length === 0) return <p className="text-[13px] text-slate-600 text-center py-10">No Qualitative results yet.</p>;

  // "Not Disclosed" (this filer genuinely never states it, or the item
  // hasn't been computed at all) is hidden by default - it varies
  // company to company (one filer discloses tenure/competitors/covenant
  // status, another doesn't), so it's noise rather than a finding. Data
  // Missing stays visible since it's actionable (names a document to
  // upload); Not Applicable stays visible since it's itself a real,
  // meaningful classification (e.g. "network effects don't apply to
  // this business"), not an absence of data. Pure section-heading rows
  // (no visualization_rule, no data of their own) are never subject to
  // this filter - they'd otherwise vanish entirely, since an
  // un-computed heading row also defaults to the NOT_DISCLOSED fallback
  // above.
  const HIDDEN_STATUSES = new Set(['NOT_DISCLOSED', 'SEARCH_INCONCLUSIVE', 'NOT_FOUND', 'NOT_COMPUTED']);
  const visibleRows = rows.filter((row) => (
    !framework[row.subpoint_id]?.visualization_rule || !HIDDEN_STATUSES.has(row.confidence_tag)
  ));

  const q = (query || '').trim().toLowerCase();
  const filtered = q
    ? visibleRows.filter((row) => {
        const title = (framework[row.subpoint_id]?.title || '').toLowerCase();
        return title.includes(q) || row.subpoint_id.toLowerCase().includes(q);
      })
    : visibleRows;
  if (q && filtered.length === 0) {
    return <p className="text-[13px] text-slate-600 text-center py-10">No item matches "{query}".</p>;
  }

  const bySection = {};
  for (const row of filtered) {
    const section = row.subpoint_id.split('.')[0];
    (bySection[section] = bySection[section] || []).push(row);
  }
  const sections = Object.keys(bySection).sort();

  const hiddenCount = rows.filter((row) => (
    framework[row.subpoint_id]?.visualization_rule && HIDDEN_STATUSES.has(row.confidence_tag)
  )).length;

  return (
    <div>
      <DocumentCoverage symbol={symbol} />
      {hiddenCount > 0 && (
        <p className="text-[11px] text-slate-600 mb-4">
          {hiddenCount} item{hiddenCount === 1 ? '' : 's'} not disclosed in this company's Annual Report - hidden from view.
        </p>
      )}
      <div className="space-y-6">
        {sections.map((sec) => {
          const rows = bySection[sec];
          // Pure grouping headings (no visualization_rule) carry no data of
          // their own - just topic labels, not shown per the user's own
          // request to drop them from every section.
          // Real cards, reordered: items with actual fetched/verified data
          // first, then items that need an uploaded document, then items
          // genuinely searched-and-found-nothing, then Not Applicable last.
          const cards = rows
            .map((row, idx) => ({ row, idx }))
            .filter(({ row }) => framework[row.subpoint_id]?.visualization_rule)
            .sort((a, b) => (TIER[a.row.confidence_tag] ?? 2) - (TIER[b.row.confidence_tag] ?? 2) || a.idx - b.idx)
            .map(({ row }) => row);

          // With Not Disclosed hidden, an entire section can end up with
          // no real cards left (every sub-point in it happened to be
          // genuinely undisclosed) - a bare "Section X" heading over
          // nothing is worse than not showing the section at all.
          if (cards.length === 0) return null;

          return (
            <div key={sec}>
              <h3 className="text-[13px] font-bold text-slate-300 uppercase tracking-wide mb-2.5">Section {sec}</h3>
              <div className="grid sm:grid-cols-2 gap-2.5">
                {cards.map((row) => (
                  <QualitativeCard key={row.subpoint_id} row={row} meta={framework[row.subpoint_id]} defaultOpen={!!q} symbol={symbol} onUploaded={loadData} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// The NEW, separate document-analysis workspace - everything here is
// sourced from tools/document_analysis_engine.py's own broad extraction
// over the uploaded Annual Report + XBRL (Fundamental) and the existing
// A-U framework's own compute_fn's (Qualitative), NOT the old per-ratio
// fetching pipeline.
export default function DocumentAnalysis({ symbol, name, onBack, onLogout, onOpenDashboard }) {
  const [tab, setTab] = useState('fundamental');
  const [query, setQuery] = useState('');
  const [showUpload, setShowUpload] = useState(false);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="max-w-6xl w-full mx-auto px-6 h-16 flex items-center justify-between flex-shrink-0 gap-4">
        <div className="flex items-center gap-3 flex-shrink-0">
          <button onClick={onBack} className="nv-icon-btn w-8 h-8" title="Back to search"><IconArrowLeft /></button>
          <button onClick={onBack} className="flex items-center gap-2.5" title="Back to search">
            <img src={navristLogo} alt="Navrist" className="w-8 h-8 rounded-lg bg-white p-0.5" />
            <span className="font-heading font-bold text-slate-100 tracking-tight hidden sm:inline">Navrist<span className="text-blue-600"> AI</span></span>
          </button>
        </div>
        <div className="flex-1" />
        <button onClick={() => setShowUpload(true)} className="nv-btn nv-btn-primary h-9 px-4 text-[13px] flex-shrink-0">Upload New</button>
        {onLogout && <button onClick={onLogout} className="nv-btn nv-btn-ghost h-9 px-3 text-[13px] flex-shrink-0">Sign out</button>}
      </header>

      <main className="max-w-6xl w-full mx-auto px-6 pb-16 flex-1">
        <div className="nv-eyebrow text-blue-600 mt-2">Annual Report + XBRL Analysis</div>
        <div className="flex items-center gap-3 mt-1 mb-5">
          <h1 className="nv-h1 text-[22px] text-slate-100">{name || symbol}</h1>
          <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-md px-1.5 py-0.5">Analysis Complete</span>
        </div>

        <div className="flex items-center justify-between gap-4 mb-5 border-b border-slate-800/60">
          <div className="flex items-center gap-2">
            {[['fundamental', 'Quantitative Analysis'], ['qualitative', 'Qualitative Analysis']].map(([key, label]) => (
              <button
                key={key}
                onClick={() => { setTab(key); setQuery(''); }}
                className={`px-4 py-2.5 text-[13px] font-semibold border-b-2 -mb-px transition-colors ${tab === key ? 'text-blue-500 border-blue-500' : 'text-slate-500 border-transparent hover:text-slate-300'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="relative mb-2.5 w-52 flex-shrink-0">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600"><IconSearch /></span>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={tab === 'fundamental' ? 'Find a ratio...' : 'Find an item...'}
              className="w-full h-8 pl-8 pr-7 rounded-lg bg-slate-900 border border-slate-800 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-600/60"
            />
            {query && (
              <button onClick={() => setQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-300 text-[13px]">
                x
              </button>
            )}
          </div>
        </div>

        {tab === 'fundamental' ? <FundamentalTab symbol={symbol} query={query} /> : <QualitativeTab symbol={symbol} query={query} />}
      </main>

      {showUpload && (
        <ManualUpload
          symbol={null}
          onClose={() => setShowUpload(false)}
          onOpenDashboard={(sym, docName) => onOpenDashboard?.(sym, docName)}
        />
      )}
    </div>
  );
}
