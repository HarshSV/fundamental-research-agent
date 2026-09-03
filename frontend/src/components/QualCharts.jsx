import React from 'react';
import { authFetch } from '../lib/api';
import { QUAL_CHART_MAPPING, normalizeMetricTitle } from './QualChartMapping';

// Semantic visualization engine for the Qualitative Analysis tab.
//
// RULE (do not violate): the chart type is NEVER chosen from the backend's
// declared `visualization_rule`/chartType string. It is chosen by
// inspecting the actual SHAPE of the real payload a compute_fn persisted
// (tools/qualitative_engine.py) - an array of {label,pct} is a breakdown,
// two named _count/_pct fields are a comparison, a _score field 0-5 is a
// rating, etc. If the payload genuinely carries no usable shape, this
// renders an evidence/status card - never a fabricated chart.
//
// Decision order (mirrors the product spec's "UNIVERSAL FRONTEND DECISION
// TREE"): status gate -> time series -> part-of-whole -> category
// comparison -> two-value comparison -> percentage progress -> 1-5 score
// -> boolean -> sentiment -> timeline -> single number -> evidence card.

const COLOR = {
  green: '#16A34A',
  blue: '#2563EB',
  amber: '#D97706',
  red: '#DC2626',
  grey: '#64748B',
  sky: '#0EA5E9',
};

// Final, user-facing status vocabulary (tools/qualitative_db.py's
// `to_user_facing_status`). Old internal engine tags are kept too so a
// stale/uncached response still renders safely.
const STATUS_ALIAS = {
  NOT_APPLICABLE: 'NOT_APPLICABLE',
  DATA_MISSING: 'DATA_MISSING',
  EXTERNAL_DATA_REQUIRED: 'DATA_MISSING',
  NOT_DISCLOSED: 'NOT_DISCLOSED',
  SEARCH_INCONCLUSIVE: 'NOT_DISCLOSED',
  NOT_FOUND: 'NOT_DISCLOSED',
  NOT_COMPUTED: 'NOT_DISCLOSED',
  INSUFFICIENT_DATA: 'INSUFFICIENT_DATA',
  NEEDS_REVIEW: 'NEEDS_REVIEW',
  VERIFIED: 'VERIFIED',
  SINGLE_SOURCE: 'VERIFIED',
  MULTI_SOURCE: 'VERIFIED',
};

function normalizedStatus(confidenceTag) {
  return STATUS_ALIAS[confidenceTag] || 'NOT_DISCLOSED';
}

// Bookkeeping/provenance fields - never a KPI's own value, must never be
// picked up by any shape detector below.
const INTERNAL_FIELD_NAMES = new Set([
  'title', 'rationale', 'subpoint_id', 'available', 'pathway_results',
  'segment_fiscal_year', 'evidence_quote', 'children', 'sector',
  'schema_version', '_logic_version', 'confidence_tag', 'retrieved_at',
  'pdf_url', 'pl_page', 'bs_page', 'fiscal_year', 'source_pdf_url',
  'required_document', 'status', 'grounded', 'footer_readline',
  'pattern_sources', 'weighted_pattern_score', 'weighted_pattern_label',
  'description', 'recurring_description', 'generic_disclosure',
  'as_of_quarter', 'source', 'period_type', 'basis_used',
]);

function prettyLabel(fieldName) {
  return String(fieldName)
    .replace(/_(pct|count|cr|score|years?)$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function fmtNum(v) {
  if (v == null || Number.isNaN(Number(v))) return '-';
  const n = Number(v);
  return Math.abs(n - Math.round(n)) < 1e-9 ? String(Math.round(n)) : n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

// ---------------------------------------------------------------------
// 1. Status gate - Not Applicable / Data Missing / Not Disclosed /
//    Insufficient Data. NEVER a graph, per rule.
// ---------------------------------------------------------------------

function StatusPanel({ tone, icon, label, sublabel }) {
  const toneColor = { grey: COLOR.grey, sky: COLOR.sky, amber: COLOR.amber, green: COLOR.green, red: COLOR.red, blue: COLOR.blue }[tone] || COLOR.grey;
  return (
    <div className="flex flex-col items-center justify-center gap-1 min-w-[104px] max-w-[150px]">
      <span
        className="text-[10.5px] font-bold uppercase tracking-wide rounded-full px-3 py-1 border flex items-center gap-1"
        style={{ color: toneColor, borderColor: toneColor, backgroundColor: `${toneColor}1a` }}
      >
        {icon} {label}
      </span>
      {sublabel && <span className="text-[9.5px] text-slate-500 text-center leading-snug">{sublabel}</span>}
    </div>
  );
}

function NotApplicablePanel() {
  return <StatusPanel tone="grey" icon="—" label="Not Applicable" />;
}
function DataMissingPanel({ requiredDocument }) {
  return <StatusPanel tone="sky" icon="⇪" label="Data Missing" sublabel={requiredDocument ? `Upload: ${requiredDocument}` : undefined} />;
}
function NotDisclosedPanel() {
  return <StatusPanel tone="grey" icon="○" label="Not Disclosed" />;
}
function InsufficientDataPanel() {
  return <StatusPanel tone="grey" icon="△" label="Insufficient Data" />;
}

// ---------------------------------------------------------------------
// Shape detectors - each returns null when the payload doesn't genuinely
// carry that shape. Never invents a value.
// ---------------------------------------------------------------------

// Any array of {label|period|date|year, <one numeric field>} with 2+
// points and a label key that reads as a point in time -> a real
// historical series (e.g. E.5.1's `trend: [{period, inventory_cr}]`).
const TIME_KEY_RE = /^(period|label|date|year|fy|quarter|month)$/i;
function findTimeSeries(payload) {
  if (!payload) return null;
  for (const [fieldName, v] of Object.entries(payload)) {
    if (!Array.isArray(v) || v.length < 2 || INTERNAL_FIELD_NAMES.has(fieldName)) continue;
    if (!v.every((p) => p && typeof p === 'object')) continue;
    const keys = Object.keys(v[0]);
    const timeKey = keys.find((k) => TIME_KEY_RE.test(k));
    if (!timeKey) continue;
    const numKey = keys.find((k) => k !== timeKey && typeof v[0][k] === 'number');
    if (!numKey) continue;
    if (!v.every((p) => typeof p[timeKey] !== 'undefined' && typeof p[numKey] === 'number')) continue;
    return { points: v.map((p) => ({ label: String(p[timeKey]), value: Number(p[numKey]) })), field: numKey };
  }
  return null;
}

// A genuine array of plain-string category names with NO accompanying
// numeric weight (e.g. F.1.1's `competitor_names`, G.1.1's
// `channels_identified`, F.2.1's `barrier_dimensions`, B.1.3's
// `strategic_priorities`/`matched_areas`, D.2.3's `repeat_buyers`). The
// manual-upload compute_fn's genuinely extract these as named lists with
// no percentage/count per item - never invent a share to force a
// composition/ranked-bar chart; show them as what they are, a list of
// named items the document actually disclosed.
function findNamedList(payload) {
  if (!payload) return null;
  for (const [fieldName, v] of Object.entries(payload)) {
    if (!Array.isArray(v) || !v.length || INTERNAL_FIELD_NAMES.has(fieldName)) continue;
    if (!v.every((p) => typeof p === 'string' && p.trim())) continue;
    return { items: v.map((s) => s.trim()), field: fieldName };
  }
  return null;
}

// A genuine parts-of-one-whole array: [{label, pct|share_pct}, ...]
// summing to ~100.
function findWholeBreakdown(payload) {
  if (!payload) return null;
  for (const [fieldName, v] of Object.entries(payload)) {
    if (!Array.isArray(v) || v.length < 2 || INTERNAL_FIELD_NAMES.has(fieldName)) continue;
    if (!v.every((p) => p && typeof p === 'object' && 'label' in p && (typeof p.pct === 'number' || typeof p.share_pct === 'number'))) continue;
    const slices = v.map((p) => ({ label: String(p.label), pct: Number(p.pct ?? p.share_pct) || 0 }));
    return { slices, field: fieldName };
  }
  return null;
}

// Two (or more) *_pct fields that together sum close to 100 - a genuine
// composition (e.g. promoter_pct/public_pct, vested_pct/unvested_pct).
function findPctPair(payload) {
  if (!payload) return null;
  const pairs = [];
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (/_pct$/.test(k) && typeof v === 'number' && v >= 0 && v <= 100) pairs.push({ key: k, value: v });
  }
  if (pairs.length < 2 || pairs.length > 4) return null;
  const sum = pairs.reduce((s, p) => s + p.value, 0);
  if (sum < 96 || sum > 104) return null;
  return { pairs, isOwnership: pairs.some((p) => /promoter|public|holding|ownership/i.test(p.key)) };
}

// Paired *_count fields whose names read as opposite outcomes of the
// same tally (successful/failed, strong/weak, delivered/stated,
// vested/unvested, planned/actual...). Generic: any 2-3 sibling
// `_count` fields not already consumed by a pct-pair/breakdown.
function findCountComparison(payload) {
  if (!payload) return null;
  const counts = [];
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (/_count$/.test(k) && typeof v === 'number') counts.push({ key: k, value: v });
  }
  if (counts.length < 2 || counts.length > 4) return null;
  if (counts.every((c) => c.value === 0)) return null;
  return { counts };
}

// Named two-value "A vs B" numeric comparisons that are NOT percentages
// of one whole (e.g. price-realisation vs input-cost change, revenue
// growth vs inventory growth, planned vs actual capex). Detected as any
// two sibling numeric fields (not score/pct-pair/count) whose names both
// end in a shared suffix or both look like independent quantities.
function findValueComparison(payload) {
  if (!payload) return null;
  const nums = [];
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (/_score$/.test(k) || k === 'score') continue;
    if (typeof v === 'number') nums.push({ key: k, value: v });
  }
  if (nums.length !== 2) return null;
  return { a: nums[0], b: nums[1] };
}

// A single _score (or bare `score`) field, 0-5.
function find5PointScore(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if ((/_score$/.test(k) || k === 'score') && typeof v === 'number' && v >= 0 && v <= 5) return { value: v, field: k };
  }
  return null;
}

// A yearly-breakdown array where each entry carries a nested `*_pct` dict
// (e.g. C.7.mix's capital_allocation_mix: [{fiscal_year, mix_pct: {M&A:
// 39.3, Dividends: 60.7, Capex: null}}]) - a real part-of-whole breakdown,
// just shaped as an array-of-years-of-dicts instead of the flat
// [{label,pct}] findWholeBreakdown expects. Uses the most recent year's
// entry; only the categories with a real (non-null) value are charted -
// never fabricates the missing ones.
function findNestedYearlyMix(payload) {
  if (!payload) return null;
  for (const [fieldName, v] of Object.entries(payload)) {
    if (!Array.isArray(v) || !v.length || INTERNAL_FIELD_NAMES.has(fieldName)) continue;
    if (!v.every((p) => p && typeof p === 'object' && 'fiscal_year' in p)) continue;
    const pctKey = Object.keys(v[0]).find((k) => /_pct$/.test(k) && v[0][k] && typeof v[0][k] === 'object');
    if (!pctKey) continue;
    const latest = v.reduce((a, b) => (b.fiscal_year > a.fiscal_year ? b : a));
    const slices = Object.entries(latest[pctKey] || {})
      .filter(([, val]) => typeof val === 'number')
      .map(([label, val]) => ({ label, pct: val }));
    if (!slices.length) continue;
    return { slices, year: latest.fiscal_year, field: fieldName };
  }
  return null;
}

// A single *_pct field (0-100), not part of a pair/breakdown already
// consumed above - a genuine "percentage against a total/threshold".
function findSinglePct(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (/_pct$/.test(k) && typeof v === 'number') return { value: v, field: k };
  }
  return null;
}

function findBoolean(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (typeof v === 'boolean') return { value: v, field: k };
  }
  return null;
}

const DIRECTION_WORDS = /\b(buying|selling|increasing|decreasing|stable|accumulat|divest)\w*\b/i;
function findDirectional(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (typeof v === 'string' && DIRECTION_WORDS.test(v)) return { value: v.match(DIRECTION_WORDS)[0].toLowerCase(), field: k };
  }
  return null;
}

// A.4-style lifecycle payload: a `segments` array whose entries carry a
// `stage` field drawn from growth/maturity/commoditisation/decline.
const LIFECYCLE_STAGES = ['growth', 'maturity', 'commoditisation', 'decline'];
function findLifecycle(payload) {
  const segs = payload && Array.isArray(payload.segments) ? payload.segments : null;
  if (!segs || !segs.length) return null;
  if (!segs.some((s) => s && typeof s.stage === 'string' && LIFECYCLE_STAGES.includes(s.stage))) return null;
  return segs;
}

function findSingleNumber(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (typeof v === 'number') return { value: v, field: k };
  }
  return null;
}

// Field-naming conventions across tools/qualitative_engine.py's compute_fn's
// that carry the ACTUAL classification/verdict, as opposed to an
// incidental descriptive string (e.g. B.1.B's `blend_note` is commentary,
// while its sibling `classification` field is the real answer) - checked
// in this priority order before falling back to the first string found.
const PRIORITY_STRING_FIELDS = [
  'classification', 'control_level', 'stage_label', 'audit_opinion_status',
  'transaction_type', 'observation_classification', 'covenant_status',
  'direction', 'recipient_class', 'audit_status',
];
function findCategoryString(payload) {
  if (!payload) return null;
  for (const key of PRIORITY_STRING_FIELDS) {
    const v = payload[key];
    if (typeof v === 'string' && v.trim()) return { value: v, field: key };
  }
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if (typeof v === 'string' && v.trim()) return { value: v, field: k };
  }
  return null;
}

// ---------------------------------------------------------------------
// Visual primitives
// ---------------------------------------------------------------------

function polarToXY(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}
function wedgePath(cx, cy, r, startAngle, endAngle) {
  const [x1, y1] = polarToXY(cx, cy, r, startAngle);
  const [x2, y2] = polarToXY(cx, cy, r, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
}
const PALETTE = ['#2563EB', '#F59E0B', '#16A34A', '#0D9488', '#7C3AED', '#DC2626', '#EAB308', '#164E63'];

// A genuine part-to-whole donut - only ever called for a real breakdown.
export function PieChart({ slices, size = 152 }) {
  const cx = size / 2, cy = size / 2, r = size / 2 - 4;
  let angle = 0;
  const total = slices.reduce((s, x) => s + (x.pct || 0), 0) || 1;
  const paths = slices.map((s, i) => {
    const sweep = (s.pct / total) * 360;
    const start = angle, end = angle + sweep;
    angle = end;
    const mid = (start + end) / 2;
    const [lx, ly] = polarToXY(cx, cy, r * 0.62, mid);
    return { key: i, d: wedgePath(cx, cy, r, start, end), color: s.color, label: s.label, pct: s.pct, lx, ly, sweep };
  });
  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {paths.map((p) => <path key={p.key} d={p.d} fill={p.color} stroke="#0f172a" strokeWidth="1.5" />)}
        {paths.filter((p) => p.sweep > 18).map((p) => (
          <text key={`t${p.key}`} x={p.lx} y={p.ly} textAnchor="middle" dominantBaseline="middle" fontSize="10.5" fontWeight="700" fill="#fff">
            <tspan x={p.lx} dy="-6">{p.label}</tspan>
            <tspan x={p.lx} dy="13">{Math.round(p.pct)}%</tspan>
          </text>
        ))}
      </svg>
      <div className="flex flex-wrap justify-center gap-x-2.5 gap-y-1 max-w-[190px]">
        {slices.map((s, i) => (
          <span key={i} className="flex items-center gap-1 text-[9.5px] text-slate-400">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: s.color }} />
            {s.label} {Math.round(s.pct)}%
          </span>
        ))}
      </div>
    </div>
  );
}

// 100%-stacked horizontal bar - the default "parts of one whole" view
// (recurring/cyclical, vested/unvested, fixed/variable, channel mix...).
export function StackedBar({ segments, width = 168, full = false }) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0) || 1;
  return (
    <div className="flex flex-col gap-1.5" style={full ? { width: '100%' } : { width }}>
      <div className="w-full h-3.5 rounded-full overflow-hidden flex bg-slate-800">
        {segments.map((s, i) => (
          <div key={i} style={{ width: `${(Math.max(0, s.value) / total) * 100}%`, backgroundColor: PALETTE[i % PALETTE.length] }} title={`${s.label} ${s.value}%`} />
        ))}
      </div>
      <div className="flex flex-col gap-0.5">
        {segments.map((s, i) => (
          <div key={i} className="flex items-center justify-between gap-2 text-[9.5px]">
            <span className={`flex items-center gap-1 text-slate-400 ${full ? 'break-words' : 'truncate'}`}>
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: PALETTE[i % PALETTE.length] }} />
              {s.label}
            </span>
            <span className="font-semibold nv-num flex-shrink-0" style={{ color: PALETTE[i % PALETTE.length] }}>{fmtNum(s.value)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Horizontal comparison bars - category-vs-category or A-vs-B counts
// that are NOT shares of one whole (successful/failed, strong/weak,
// per-executive tenure, per-competitor share...).
export function ComparisonBars({ items, width = 168, unit = '', full = false }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1);
  return (
    <div className="flex flex-col gap-1.5" style={full ? { width: '100%' } : { width }}>
      {items.map((it, i) => (
        <div key={i} className="flex flex-col gap-0.5">
          <div className="flex items-center justify-between gap-2 text-[9.5px]">
            <span className={`text-slate-400 ${full ? 'break-words' : 'truncate'}`}>{it.label}</span>
            <span className="font-bold nv-num flex-shrink-0" style={{ color: it.color || PALETTE[i % PALETTE.length] }}>{fmtNum(it.value)}{unit}</span>
          </div>
          <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width: `${it.value === 0 ? 3 : (Math.abs(it.value) / max) * 100}%`,
                backgroundColor: it.color || PALETTE[i % PALETTE.length],
                opacity: it.value === 0 ? 0.45 : 1,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// Semantic 1-5 scale label sets - every deterministic sub-point in this
// framework bands its raw fact so 5 is always the better outcome for the
// company, but "5/5" alone never says WHAT 5 means for a given metric.
// Matched by keyword against the metric's own title so this generalizes
// across the whole A-U framework instead of one label set per subpoint_id.
// Mirrors the identical rule set in frontend/src/main.jsx's
// scaleSetForTitle - keep both in sync if this changes.
const SCALE_SETS = {
  risk: ['Very High Risk', 'High Risk', 'Moderate Risk', 'Low Risk', 'Very Low Risk'],
  barrier: ['Low', 'Moderate', 'Elevated', 'High', 'Very High'],
  strength: ['Very Weak', 'Weak', 'Moderate', 'Strong', 'Very Strong'],
  quality: ['Poor', 'Fair', 'Good', 'Very Good', 'Excellent'],
  maturity: ['Nascent', 'Developing', 'Established', 'Advanced', 'Mature'],
  default: ['Very Poor', 'Poor', 'Moderate', 'Good', 'Excellent'],
};
const SCALE_SET_RULES = [
  [/risk|dependency|dependence|concentration|exposure|vulnerab|obsolescence|constraint|sensitivity/i, 'risk'],
  [/barrier/i, 'barrier'],
  [/strength|switching cost|network effect|moat|pricing power|bargaining/i, 'strength'],
  [/maturity|lifecycle|pipeline depth/i, 'maturity'],
  [/quality|disclosure|transparency|clarity|orientation|openness|alignment|rating|depth|control\b/i, 'quality'],
];
function scaleSetForTitle(title) {
  const t = title || '';
  for (const [re, key] of SCALE_SET_RULES) if (re.test(t)) return SCALE_SETS[key];
  return SCALE_SETS.default;
}

// 1-5 rating bar - five discrete segments, filled up to the score, PLUS the
// semantic word for the score's position (Moderate/Weak/High Risk/...) so a
// bare number never has to be guessed at - never just "3/5".
export function RatingBar5({ value, width = 128, full = false, title }) {
  const color = value >= 4 ? COLOR.green : value <= 2 ? COLOR.red : COLOR.amber;
  const idx = Math.max(1, Math.min(5, Math.round(value))) - 1;
  const labels = scaleSetForTitle(title);
  const word = labels[idx];
  return (
    <div className="flex flex-col items-center gap-1.5" style={full ? { width: '100%', maxWidth: 260 } : { width }}>
      <span className="text-[20px] font-extrabold leading-none nv-num" style={{ color }}>
        {fmtNum(value)}<span className="text-[12px] font-semibold opacity-70">/5</span>
      </span>
      <span className="text-[10.5px] font-bold uppercase tracking-wide" style={{ color }}>{word}</span>
      <div className="flex gap-1 w-full mt-0.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <div key={n} className="flex-1 h-2 rounded-sm" style={{ backgroundColor: n <= Math.round(value) ? color : '#1e293b' }} />
        ))}
      </div>
      {full && (
        <div className="flex gap-1 w-full">
          {labels.map((lbl, i) => (
            <span key={i} className={`flex-1 text-[8px] text-center leading-tight ${i === idx ? 'font-bold' : 'text-slate-600'}`} style={i === idx ? { color } : undefined}>
              {lbl}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Single-value progress bar - a percentage against an implicit 100%
// total/threshold (hedge coverage, subsidy dependence, floating-rate
// debt share...).
export function ProgressBar({ value, width = 128, color = COLOR.blue, label, full = false }) {
  const pct = Math.max(0, Math.min(100, value));
  // A real, genuine 0% fill renders as a visually-empty bar - indistinguishable
  // from a chart that failed to populate at all. A thin marker at the left
  // edge keeps a true zero honestly visible instead of looking broken.
  const fillPct = pct === 0 ? 3 : pct;
  return (
    <div className="flex flex-col items-center gap-1.5" style={full ? { width: '100%', maxWidth: 260 } : { width }}>
      <span className="text-[20px] font-extrabold leading-none nv-num" style={{ color }}>{fmtNum(value)}%</span>
      <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${fillPct}%`, backgroundColor: color, opacity: pct === 0 ? 0.45 : 1 }} />
      </div>
      {label && <span className="text-[9.5px] font-semibold uppercase tracking-wide text-slate-500 text-center leading-snug">{label}</span>}
    </div>
  );
}

export function BinaryStatus({ value }) {
  const color = value ? COLOR.green : COLOR.grey;
  return <StatusPanel tone={value ? 'green' : 'grey'} icon={value ? '✓' : '✕'} label={value ? 'Yes' : 'No'} />;
}

// A short classification word/phrase (e.g. "Single Product", "Cyclical",
// "Unmodified") with no numeric anchor - shown as a badge instead of a
// prose paragraph. Only used for genuinely short (<=28 char) values so a
// full sentence never gets crammed into a pill.
export function CategoryBadge({ value }) {
  return <StatusPanel tone="sky" icon="⧉" label={value} />;
}

// A named list with no per-item numeric weight (competitor names, channel
// types, barrier dimensions...) - rendered as chips, never coerced into a
// bar/composition chart that would fabricate a share/count that was never
// disclosed. Compact mode caps visible chips so the collapsed row stays
// scannable; full mode (expanded card) always shows every item.
export function TagList({ items, full = false }) {
  const shown = full ? items : items.slice(0, 5);
  return (
    <div className={`flex flex-wrap gap-1 ${full ? 'w-full' : 'max-w-[168px]'}`}>
      {shown.map((it, i) => (
        <span key={i} className="text-[9.5px] font-medium text-slate-300 bg-slate-800 border border-slate-700/60 rounded px-1.5 py-0.5 break-words">
          {it}
        </span>
      ))}
      {!full && items.length > 5 && <span className="text-[9.5px] text-slate-500 italic">+ {items.length - 5} more</span>}
    </div>
  );
}

// A metric whose payload names a *_pct/*_score field the compute_fn
// genuinely tried to fill but couldn't quantify from the source text
// (value is explicitly null, not merely absent) - the topic was discussed
// qualitatively, just never numerically anchored. Never invents the
// number; shows an honest "discussed, not quantified" status instead of a
// full paragraph.
function findDisclosedNoNumber(payload) {
  if (!payload) return null;
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_FIELD_NAMES.has(k)) continue;
    if ((/_pct$/.test(k) || /_score$/.test(k)) && v === null) return { field: k };
  }
  return null;
}

export function DisclosedNoNumberPanel() {
  return <StatusPanel tone="sky" icon="⧉" label="Disclosed" sublabel="No figure quantified in source" />;
}

const DIRECTION_ICON = { buying: '↑', accumulating: '↑', increasing: '↑', selling: '↓', divesting: '↓', decreasing: '↓', stable: '→' };
export function DirectionalIndicator({ word }) {
  const key = Object.keys(DIRECTION_ICON).find((w) => word.includes(w)) || 'stable';
  const color = key === 'selling' || key === 'divesting' || key === 'decreasing' ? COLOR.red
    : key === 'stable' ? COLOR.grey : COLOR.green;
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[26px] font-black leading-none" style={{ color }}>{DIRECTION_ICON[key]}</span>
      <span className="text-[9.5px] font-semibold uppercase tracking-wide" style={{ color }}>{key}</span>
    </div>
  );
}

export function LifecycleIndicator({ segments }) {
  const dominant = segments.reduce((a, b) => ((a?.share_pct || 0) >= (b?.share_pct || 0) ? a : b), segments[0]);
  const stage = dominant?.stage;
  return (
    <div className="flex flex-col items-center gap-1 max-w-[168px]">
      <div className="flex items-center gap-0.5">
        {LIFECYCLE_STAGES.map((s, i) => (
          <React.Fragment key={s}>
            <span
              className="text-[8.5px] font-bold uppercase tracking-wide rounded-full px-1.5 py-0.5"
              style={{
                color: s === stage ? '#fff' : COLOR.grey,
                backgroundColor: s === stage ? COLOR.blue : '#1e293b',
              }}
            >
              {s.slice(0, 4)}
            </span>
            {i < LIFECYCLE_STAGES.length - 1 && <span className="text-slate-700 text-[9px]">→</span>}
          </React.Fragment>
        ))}
      </div>
      <span className="text-[9.5px] font-semibold text-slate-400">{stage ? dominant.stage_label || prettyLabel(stage) : 'Unclassified'}</span>
    </div>
  );
}

export function KPICard({ value, label, color = COLOR.blue, suffix = '' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 flex-shrink-0 min-w-[76px]">
      <span className="text-[24px] font-extrabold leading-none nv-num" style={{ color }}>
        {fmtNum(value)}<span className="text-[13px] font-semibold opacity-70">{suffix}</span>
      </span>
      {label && <span className="text-[9.5px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>}
    </div>
  );
}

export function LineChartMini({ points, width = 132, height = 54, full = false }) {
  const values = points.map((p) => p.value);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const pad = 8;
  const h = full ? Math.max(height, 90) : height;
  // More data points need more horizontal room to stay readable - the
  // viewBox coordinate space grows with point count, then the <svg> is
  // rendered at 100% CSS width so it fills whatever room the card gives it.
  const svgWidth = full ? Math.max(width, points.length * 46) : width;
  const stepX = values.length > 1 ? (svgWidth - pad * 2) / (values.length - 1) : 0;
  const coords = values.map((v, i) => [pad + i * stepX, h - pad - ((v - min) / range) * (h - pad * 2)]);
  const rising = values[values.length - 1] >= values[0];
  const color = rising ? COLOR.green : COLOR.red;
  return (
    <div className={`flex flex-col items-center justify-center gap-1 ${full ? 'w-full' : 'flex-shrink-0'}`}>
      <svg width={full ? '100%' : svgWidth} height={h} viewBox={`0 0 ${svgWidth} ${h}`} preserveAspectRatio={full ? 'xMidYMid meet' : undefined}>
        <polyline points={coords.map((c) => c.join(',')).join(' ')} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        {coords.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="2.4" fill={color} />)}
      </svg>
      {full && (
        <div className="flex justify-between w-full px-1">
          {points.map((p, i) => (
            <span key={i} className="text-[8.5px] text-slate-600 truncate">{p.label}</span>
          ))}
        </div>
      )}
      <span className="text-[9.5px] font-semibold uppercase tracking-wide" style={{ color }}>
        {fmtNum(values[values.length - 1])} · {rising ? 'Rising' : 'Declining'}
      </span>
    </div>
  );
}

// Shape-only cascade for metrics outside the 221-item Excel spec. Same
// detectors the Excel-mapped branches use, run in the product spec's
// decision-tree order, so nothing chartable ever falls back to text just
// because it has no Excel row.
function AutoChart({ payload: p, full = false, title }) {
  const series = findTimeSeries(p);
  if (series && series.points.length >= 2) return <LineChartMini points={series.points} full={full} />;

  const nestedMix = findNestedYearlyMix(p);
  if (nestedMix) return <StackedBar segments={nestedMix.slices.map((s) => ({ label: s.label, value: s.pct }))} full={full} />;

  const breakdown = findWholeBreakdown(p);
  if (breakdown) {
    const slices = breakdown.slices.map((b, i) => ({ ...b, color: PALETTE[i % PALETTE.length] }));
    return <StackedBar segments={slices.map((s) => ({ label: s.label, value: s.pct }))} full={full} />;
  }

  const pctPair = findPctPair(p);
  if (pctPair) {
    const segs = pctPair.pairs.map((pp) => ({ label: prettyLabel(pp.key), value: pp.value }));
    return <StackedBar segments={segs} full={full} />;
  }

  const lc = findLifecycle(p);
  if (lc) return <LifecycleIndicator segments={lc} />;

  const score = find5PointScore(p);
  const namedList = findNamedList(p);
  if (score && namedList && full) {
    // The score answers the metric's question at a glance; the named
    // dimensions/entities behind it (barrier_dimensions, competitor_names,
    // channels_identified...) are real disclosed evidence, not decoration -
    // the expanded card must not hide them just because the score already
    // rendered.
    return (
      <div className="flex flex-col gap-3 w-full">
        <RatingBar5 value={score.value} full title={title} />
        <TagList items={namedList.items} full />
      </div>
    );
  }
  if (score) return <RatingBar5 value={score.value} full={full} title={title} />;
  if (namedList) return <TagList items={namedList.items} full={full} />;

  const countCmp = findCountComparison(p);
  if (countCmp) return <ComparisonBars items={countCmp.counts.map((c) => ({ label: prettyLabel(c.key), value: c.value }))} full={full} />;

  const valCmp = findValueComparison(p);
  if (valCmp) return <ComparisonBars items={[
    { label: prettyLabel(valCmp.a.key), value: valCmp.a.value, color: PALETTE[0] },
    { label: prettyLabel(valCmp.b.key), value: valCmp.b.value, color: PALETTE[1] },
  ]} unit={/_pct$/.test(valCmp.a.key) ? '%' : ''} full={full} />;

  const pct = findSinglePct(p);
  if (pct) return <ProgressBar value={pct.value} label={prettyLabel(pct.field)} color={COLOR.blue} full={full} />;

  const dir = findDirectional(p);
  if (dir) return <DirectionalIndicator word={dir.value} />;

  const bool = findBoolean(p);
  if (bool) return <BinaryStatus value={bool.value} />;

  const num = findSingleNumber(p);
  if (num) return <KPICard value={num.value} label={prettyLabel(num.field)} />;

  const cat = findCategoryString(p);
  if (cat && cat.value.length <= 28) return <CategoryBadge value={cat.value} />;

  const noNum = findDisclosedNoNumber(p);
  if (noNum) return <DisclosedNoNumberPanel />;

  return <EvidenceCard text={p.rationale} full={full} />;
}

export function EvidenceCard({ text, full = false }) {
  return (
    <div className={full ? 'w-full' : 'max-w-[168px]'}>
      <p className={`text-[10.5px] text-slate-500 leading-snug ${full ? '' : 'line-clamp-4'}`}>{text || 'Evidence recorded, no standalone metric.'}</p>
    </div>
  );
}

// ---------------------------------------------------------------------
// Top-level selector - the ONLY entry point views should use. Never
// takes a vizKind/chartType from the backend; decides purely from the
// confidence_tag (status gate) and the real payload shape.
// ---------------------------------------------------------------------


export function VerticalBarChart({ points, width = 140, height = 64, full = false }) {
  if (!points || !points.length) return null;
  const values = points.map(p => p.value);
  const max = Math.max(...values, 1);
  const pad = 4;
  const h = full ? Math.max(height, 90) : height;

  return (
    <div className={`flex flex-col items-center justify-center gap-1.5 ${full ? 'w-full' : 'flex-shrink-0'}`}>
      <div className="flex items-end gap-[2px]" style={full ? { width: '100%', height: h, padding: `0 ${pad}px` } : { width, height: h, padding: `0 ${pad}px` }}>
        {points.map((p, i) => {
          const barH = (p.value / max) * h;
          return (
            <div key={i} className="flex flex-col items-center justify-end h-full flex-1" title={`${p.label}: ${p.value}`}>
              <div className="bg-blue-500 rounded-t-sm w-full max-w-[16px]" style={{ height: `${barH}px` }} />
            </div>
          );
        })}
      </div>
      {full ? (
        <div className="flex w-full gap-[2px]" style={{ padding: `0 ${pad}px` }}>
          {points.map((p, i) => (
            <span key={i} className="text-[8.5px] text-slate-500 flex-1 text-center truncate">{p.label}</span>
          ))}
        </div>
      ) : (
        <span className="text-[9.5px] font-semibold text-slate-400 truncate max-w-full">
          {points[0].label} - {points[points.length - 1].label}
        </span>
      )}
    </div>
  );
}

export function Timeline({ events, full = false }) {
  if (!events || !events.length) return null;
  const shown = full ? events : events.slice(0, 4);
  return (
    <div className={`flex flex-col gap-2 w-full ${full ? '' : 'max-w-[180px]'}`}>
      {shown.map((ev, i) => (
        <div key={i} className="flex items-start gap-2 text-[10px]">
          <div className="mt-1 w-1.5 h-1.5 rounded-full bg-blue-500 flex-shrink-0" />
          <div className="flex flex-col min-w-0">
            <span className="font-semibold text-slate-300 break-words">{ev.label}</span>
            {ev.value && <span className="text-slate-500 break-words">{ev.value}</span>}
          </div>
        </div>
      ))}
      {!full && events.length > 4 && <span className="text-[9.5px] text-slate-500 italic pl-3.5">+ {events.length - 4} more</span>}
    </div>
  );
}

export function QualChart({ payload, confidenceTag, title, full = false }) {

  const status = normalizedStatus(confidenceTag);

  // 1) Status gate
  if (status === 'NOT_APPLICABLE') return <NotApplicablePanel />;
  if (status === 'DATA_MISSING') return <DataMissingPanel requiredDocument={payload?.required_document} />;
  if (status === 'NOT_DISCLOSED') return <NotDisclosedPanel />;
  if (status === 'INSUFFICIENT_DATA') return <InsufficientDataPanel />;

  const p = payload || {};
  const vizId = QUAL_CHART_MAPPING[normalizeMetricTitle(title)];

  // This metric isn't one of the 221 Excel-specified ones (e.g. business-
  // model classification leaves like "Brand"/"Transactional" outside the
  // A-U scored spec). Still try to chart it from its real payload shape -
  // same cascade the Excel-mapped branches use below - before ever
  // falling back to a text card.
  if (!vizId) {
    console.warn(`Unmapped qualitative metric (not in Excel spec): ${title}`);
    return <AutoChart payload={p} full={full} title={title} />;
  }

  // Normalizers using existing find* logic where possible
  // If the payload doesn't fit the expected structure, we fall back to EvidenceCard
  // to avoid rendering empty charts.

  if (vizId === 'evidence_bar') return <EvidenceCard text={p.rationale} full={full} />;

  if (vizId === 'rating_5' || vizId === 'risk_rating_5') {
    const score = find5PointScore(p) || findSingleNumber(p);
    if (score) return <RatingBar5 value={score.value} full={full} title={title} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'progress' || vizId === 'risk_progress') {
    const pct = findSinglePct(p) || findSingleNumber(p);
    const color = vizId === 'risk_progress' ? COLOR.amber : COLOR.blue;
    if (pct) return <ProgressBar value={pct.value} label={prettyLabel(pct.field)} color={color} full={full} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'binary' || vizId === 'binary_applicable' || vizId === 'binary_audit' || vizId === 'binary_risk') {
    const bool = findBoolean(p) || findCategoryString(p);
    if (bool) {
       let val = bool.value;
       if (typeof val === 'string') {
          val = !/no|fail|false|none|adverse|qualified/i.test(val);
       }
       return <BinaryStatus value={val} />;
    }
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'line') {
    const series = findTimeSeries(p);
    if (series && series.points.length >= 2) return <LineChartMini points={series.points} full={full} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'bar_monthly' || vizId === 'bar_time') {
    const series = findTimeSeries(p);
    if (series && series.points.length >= 1) return <VerticalBarChart points={series.points} full={full} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'donut' || vizId === 'stacked_100') {
    const breakdown = findWholeBreakdown(p);
    if (breakdown) {
      const slices = breakdown.slices.map((b, i) => ({ ...b, color: PALETTE[i % PALETTE.length] }));
      return vizId === 'donut' ? <PieChart slices={slices} /> : <StackedBar segments={slices.map(s => ({ label: s.label, value: s.pct }))} full={full} />;
    }
    const pctPair = findPctPair(p);
    if (pctPair) {
      const segs = pctPair.pairs.map(pp => ({ label: prettyLabel(pp.key), value: pp.value }));
      return vizId === 'donut'
        ? <PieChart slices={segs.map((s, i) => ({ ...s, pct: s.value, color: PALETTE[i % PALETTE.length] }))} />
        : <StackedBar segments={segs} full={full} />;
    }
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'comparison_bar' || vizId === 'horizontal_bar' || vizId === 'ranked_bar' || vizId === 'diverging_bar' || vizId === 'risk_bar') {
    const countCmp = findCountComparison(p);
    if (countCmp) return <ComparisonBars items={countCmp.counts.map(c => ({ label: prettyLabel(c.key), value: c.value }))} full={full} />;

    const valCmp = findValueComparison(p);
    if (valCmp) return <ComparisonBars items={[
      { label: prettyLabel(valCmp.a.key), value: valCmp.a.value, color: PALETTE[0] },
      { label: prettyLabel(valCmp.b.key), value: valCmp.b.value, color: PALETTE[1] }
    ]} unit={/_pct$/.test(valCmp.a.key) ? '%' : ''} full={full} />;

    // Sometimes it's a breakdown but we want to show it as bars
    const breakdown = findWholeBreakdown(p);
    if (breakdown) return <ComparisonBars items={breakdown.slices.map((s, i) => ({ label: s.label, value: s.pct, color: PALETTE[i % PALETTE.length] }))} unit="%" full={full} />;

    // Or just any numerical fields
    const nums = [];
    for (const [k, v] of Object.entries(p)) {
       if (typeof v === 'number' && k !== 'score' && !k.endsWith('_score')) {
          nums.push({ label: prettyLabel(k), value: v });
       }
    }
    if (nums.length > 0) {
       if (vizId === 'ranked_bar') nums.sort((a, b) => b.value - a.value);
       return <ComparisonBars items={nums.map((n, i) => ({ ...n, color: PALETTE[i % PALETTE.length] }))} full={full} />;
    }

    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'diverging_directional') {
    const d = findDirectional(p) || findCategoryString(p);
    if (d) return <DirectionalIndicator word={d.value} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'timeline') {
    // try to extract events
    let events = [];
    if (p.events && Array.isArray(p.events)) events = p.events;
    else if (p.history && Array.isArray(p.history)) events = p.history;
    else if (p.timeline && Array.isArray(p.timeline)) events = p.timeline;
    else {
       const series = findTimeSeries(p);
       if (series) events = series.points;
    }

    if (events.length > 0) return <Timeline events={events} full={full} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'single_value') {
    const num = findSingleNumber(p);
    if (num) return <KPICard value={num.value} label={prettyLabel(num.field)} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  if (vizId === 'lifecycle' || vizId === 'pipeline') {
    const lc = findLifecycle(p);
    if (lc) return <LifecycleIndicator segments={lc} />;
    // fallback to category string if not array
    const cat = findCategoryString(p);
    if (cat) return <StatusPanel tone="sky" icon="⧉" label={cat.value} />;
    return <AutoChart payload={p} full={full} title={title} />;
  }

  return <AutoChart payload={p} full={full} title={title} />;
}

