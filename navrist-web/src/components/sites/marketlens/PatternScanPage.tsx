"use client";

import { SlidingTabs } from "./controls";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, LineChart, List, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import { BacktestPanel } from "./BacktestPanel";
import { STATUS_COLOR, STATUS_LABEL, type CatalogueEntry } from "./patterns";
import { RESISTANCE_ID, SCREENER_ID, describeFilters, isSpecial, searchScan, type ScanContext, type ScanFilters, type ScanOptions, type ScanResult, type ScanRow } from "./patternScan";
import { TvChart } from "./TvChart";
import { MULTI_ID, isListScanner, scannerName } from "./scanners";

const LIST_SIZE = 50;
const CHART_SIZE = 20;
const GAIN = "var(--gain)";
const LOSS = "var(--loss)";

const num = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const plain = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);

function StatusBadge({ row }: { row: ScanRow }) {
  const o = row.occurrence;
  if (!o) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={{ background: `${STATUS_COLOR[o.status]}22`, color: STATUS_COLOR[o.status] }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[o.status] }} />
      {STATUS_LABEL[o.status]}
      {o.direction && <span style={{ opacity: 0.8 }}>· {o.direction}</span>}
    </span>
  );
}

function ResistanceBadge({ row }: { row: ScanRow }) {
  const r = row.resistance;
  if (!r) return null;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium" style={{ background: "#ef444422", color: "#ef4444" }}>
      Resistance ₹{num(r.level)} ×{r.touches} · {r.state === "near" ? `${Math.abs(r.dist_pct).toFixed(1)}% below` : "breakout"}
    </span>
  );
}

type Col = { key: string; label: string; left?: boolean; cell: (r: ScanRow) => React.ReactNode };

/** The columns of the two list layouts (Technicals / Fundamentals) for this scanner. */
function columns(kind: "technicals" | "fundamentals", pattern: CatalogueEntry, withResistance: boolean, withPatterns = false): Col[] {
  const plain_special = isSpecial(pattern.id) && !withPatterns;
  const stock: Col = {
    key: "stock", label: "Stock", left: true,
    cell: (r) => (
      <>
        <div className="font-semibold">{r.name}</div>
        <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{r.symbol}</div>
        {r.markers && r.markers.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {r.markers.map((m) => (
              <span key={m.k} className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium" style={{ background: m.k === "asm" ? "#ef444422" : m.k === "results" ? "var(--accent-surface)" : "var(--overlay)", color: m.k === "asm" ? "#ef4444" : m.k === "results" ? "var(--accent)" : "var(--text-secondary)" }}>{m.label}</span>
            ))}
          </div>
        )}
      </>
    ),
  };
  const sector: Col = { key: "sector", label: "Sector", left: true, cell: (r) => (<><span className="text-xs" style={{ color: "var(--text-secondary)" }}>{r.sector}</span>{r.industry && <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{r.industry}</div>}</>) };
  const cap: Col = { key: "cap", label: "Market cap (₹ Cr)", cell: (r) => num(r.market_cap_cr, 0) };
  if (kind === "fundamentals") {
    return [
      stock, sector, cap,
      { key: "pe", label: "P/E", cell: (r) => num(r.pe) },
      { key: "epsg", label: "EPS growth", cell: (r) => <span style={{ color: tone(r.eps_growth) }}>{pct(r.eps_growth)}</span> },
      { key: "de", label: "Debt / Equity", cell: (r) => num(r.debt_equity) },
      { key: "prom", label: "Promoter", cell: (r) => plain(r.promoter) },
      { key: "dy", label: "Div. yield", cell: (r) => plain(r.div_yield, 2) },
      { key: "np", label: "Net profit (₹ Cr)", cell: (r) => num(r.net_profit_cr, 0) },
    ];
  }
  const state: Col = isListScanner(pattern.id)
    ? {
        key: "state", label: "Signal", left: true,
        cell: (r) => (<><div className="font-medium">{r.signal?.text ?? "—"}</div><div className="max-w-[260px] text-[11px] leading-snug" style={{ color: "var(--text-tertiary)" }}>{r.signal?.note}</div></>),
      }
    : pattern.id === MULTI_ID
    ? {
        key: "state", label: "In scanners", left: true,
        cell: (r) => (<div className="flex flex-wrap gap-1">{(r.matched ?? []).map((m) => (<span key={m} className="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]" style={{ background: "var(--accent-surface)", color: "var(--accent)" }}>{scannerName(m)}</span>))}</div>),
      }
    : pattern.id === RESISTANCE_ID
    ? { key: "state", label: "Resistance", left: true, cell: (r) => <ResistanceBadge row={r} /> }
    : plain_special
      ? {
          key: "state", label: withResistance ? "Resistance" : "Sector rotation", left: true,
          cell: (r) => (withResistance ? <ResistanceBadge row={r} /> : <span className="text-xs capitalize" style={{ color: "var(--text-secondary)" }}>{r.quadrant ?? "—"}</span>),
        }
      : { key: "state", label: "Status", left: true, cell: (r) => (<div className="flex flex-col items-start gap-1">{pattern.id === SCREENER_ID && r.occurrence && <span className="text-xs font-medium capitalize" style={{ color: "var(--text-primary)" }}>{r.occurrence.pattern.replace(/-and-/g, " & ").replace(/-/g, " ")}</span>}<StatusBadge row={r} />{r.resistance && <ResistanceBadge row={r} />}</div>) };
  return [
    stock,
    { key: "rs", label: "RS", cell: (r) => <span className="font-semibold">{r.rs ?? "—"}</span> },
    sector, cap,
    { key: "price", label: "Price", cell: (r) => `₹${num(r.price)}` },
    state,
    ...(plain_special ? [] : [{ key: "brk", label: "Breakout", cell: (r: ScanRow) => (r.occurrence?.breakout == null ? "—" : `₹${num(r.occurrence.breakout)}`) }]),
    { key: "r1", label: "1M", cell: (r) => <span style={{ color: tone(r.ret_1m) }}>{pct(r.ret_1m)}</span> },
    { key: "r3", label: "3M", cell: (r) => <span style={{ color: tone(r.ret_3m) }}>{pct(r.ret_3m)}</span> },
    { key: "hi", label: "From 52W high", cell: (r) => plain(r.pct_from_52w_high) },
    { key: "adr", label: "ADR (5d)", cell: (r) => plain(r.adr5, 2) },
  ];
}

const csvCell = (v: unknown) => {
  const t = v == null ? "" : String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};

/** Every stock the current scan and filters match (all pages) as a CSV file. */
async function downloadCsv(pattern: CatalogueEntry, filters: ScanFilters, q: string, sort: string) {
  const head = ["Symbol", "Name", "Sector", "Index", "Market cap (Cr)", "Price", "RS", "1M %", "3M %", "1Y %", "% from 52W high", "% from 52W low",
    "% from ATH", "ADR 5d %", "P/E", "EPS growth %", "Debt/Equity", "Promoter %", "Div yield %", "Net profit (Cr)", "Free float %",
    "Pattern status", "Direction", "Breakout level", "Resistance level", "Resistance touches", "Resistance state", "Sector rotation"];
  const lines = [head.join(",")];
  for (let page = 1; page <= 20; page++) {
    const res = await searchScan(pattern.id, filters, { q, page, page_size: 100, sort }, false);
    for (const r of res.rows) {
      lines.push([r.symbol, r.name, r.sector, r.index, r.market_cap_cr, r.price, r.rs, r.ret_1m, r.ret_3m, r.ret_1y, r.pct_from_52w_high,
        r.pct_from_52w_low, r.pct_from_ath, r.adr5, r.pe, r.eps_growth, r.debt_equity, r.promoter, r.div_yield, r.net_profit_cr, r.free_float,
        r.occurrence?.status, r.occurrence?.direction, r.occurrence?.breakout, r.resistance?.level, r.resistance?.touches, r.resistance?.state,
        r.quadrant].map(csvCell).join(","));
    }
    if (page * 100 >= res.total) break;
  }
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${pattern.id}-scan-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const SORTS: [string, string][] = [
  ["status", "Closest to breakout"], ["market_cap", "Market cap"], ["rs", "RS rating"], ["ret_1m", "1M return"],
  ["ret_3m", "3M return"], ["pct_52w_high", "Nearest 52W high"], ["turnover", "Traded value"], ["pe", "Lowest P/E"], ["name", "Name"],
];

/**
 * Stocks currently showing one scanner's setup (a chart pattern, Horizontal Resistance, or the plain screener) after the
 * filters picked in the popup, with a Backtest tab for real patterns. List shows Technicals or Fundamentals columns; Charts
 * draws each stock's daily candles with TradingView's Lightweight Charts, the pattern's lines and, where there is one, its
 * horizontal resistance. A click on any row or card opens that stock.
 */
export function PatternScanPage({
  pattern, filters, options, onBack, onEdit, onOpenStock,
}: {
  pattern: CatalogueEntry;
  filters: ScanFilters;
  options: ScanOptions | null;
  onBack: () => void;
  onEdit: () => void;
  onOpenStock: (s: CompanyHit, scan?: ScanContext) => void;
}) {
  const special = isSpecial(pattern.id);
  // the Create Screener limited to chart patterns behaves like a pattern scan: status/breakout columns, status sort, backtest
  const patternMode = !special || (pattern.id === SCREENER_ID && filters.patterns.values.length > 0);
  const [mode, setMode] = useState<"scan" | "backtest">("scan");
  const [view, setView] = useState<"list" | "charts">("list");
  const [colset, setColset] = useState<"technicals" | "fundamentals">("technicals");
  const [perRow, setPerRow] = useState<1 | 2>(2);
  const [exporting, setExporting] = useState(false);
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [sort, setSort] = useState(isListScanner(pattern.id) ? "signal" : patternMode ? "status" : "market_cap");
  const [page, setPage] = useState(1);
  const [res, setRes] = useState<{ key: string; data?: ScanResult; error?: string } | null>(null);

  // debounce the search box; a new search starts again from page 1
  useEffect(() => {
    const t = setTimeout(() => {
      setDq(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const size = view === "charts" ? CHART_SIZE : LIST_SIZE;
  const key = useMemo(() => JSON.stringify([pattern.id, filters, dq, sort, page, view]), [pattern.id, filters, dq, sort, page, view]);

  useEffect(() => {
    if (mode !== "scan") return;
    let alive = true;
    searchScan(pattern.id, filters, { q: dq, page, page_size: size, sort }, view === "charts")
      .then((data) => alive && setRes({ key, data }))
      .catch((e: Error) => alive && setRes({ key, error: e.message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` already captures every input below
  }, [key, mode]);

  // a running scan fills results in over time: refresh while it works
  const scanning = res?.data?.scan.building;
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!scanning) return;
    const t = setInterval(() => setTick((n) => n + 1), 15000);
    return () => clearInterval(t);
  }, [scanning]);
  useEffect(() => {
    if (!tick || mode !== "scan") return;
    let alive = true;
    searchScan(pattern.id, filters, { q: dq, page, page_size: size, sort }, view === "charts")
      .then((data) => alive && setRes({ key, data }))
      .catch(() => {});
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the timer drives this refresh
  }, [tick]);

  const loading = !res || res.key !== key;
  const data = res?.data;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));
  const first = total ? (page - 1) * size + 1 : 0;
  const last = Math.min(total, page * size);
  const chips = describeFilters(filters, options);
  const drawResistance = filters.resistance.on || pattern.id === RESISTANCE_ID;
  // the stock page opens with this scan's marking on its chart (pattern lines and levels, horizontal resistance)
  const open = (r: ScanRow) =>
    onOpenStock({ symbol: r.symbol, name: r.name }, { pattern: special ? (r.occurrence?.pattern ?? null) : pattern.id, occurrence: r.occurrence, resistance: r.resistance, showResistance: drawResistance });
  const cols = useMemo(() => columns(colset, pattern, drawResistance, patternMode && special), [colset, pattern, drawResistance, patternMode, special]);
  const sorts: [string, string][] = [...(isListScanner(pattern.id) ? [["signal", "Strongest signal"] as [string, string]] : []), ...SORTS.filter(([k]) => !(!patternMode && k === "status"))];


  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{pattern.name}</h1>
          <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            {pattern.id === RESISTANCE_ID
              ? "Stocks pressing on a horizontal resistance on the daily chart: a price level at least three separate highs have touched, with the price up to 5% under it or just through it."
              : pattern.id === MULTI_ID
                ? "Stocks that appear in every one of the scanners you chose."
                : isListScanner(pattern.id)
                  ? pattern.definition
                  : special
                ? (patternMode ? "Every scanned stock that currently shows one of the chosen chart patterns and passes your other filters." : "Every scanned stock that passes your filters.")
                : "Stocks showing this pattern on the daily chart right now: forming, awaiting breakout, or confirmed in the last 10 sessions. It describes how the shape has formed, not a forecast."}
          </p>
        </div>
        <button
          onClick={onEdit}
          className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[var(--btn-primary-hover)]"
          style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
        >
          <SlidersHorizontal className="h-4 w-4" /> Filters{chips.length ? ` (${chips.length})` : ""}
        </button>
      </div>

      {chips.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {chips.map((c) => (
            <span key={c} className="rounded-full border px-2.5 py-1" style={{ borderColor: "var(--accent-border)", background: "var(--accent-surface)", color: "var(--accent)" }}>{c}</span>
          ))}
        </div>
      )}

      {patternMode && (
        <div className="mt-5">
          <SlidingTabs ariaLabel="Mode" size="lg" value={mode} onChange={setMode} options={[{ id: "scan", label: "Scan results" }, { id: "backtest", label: "Backtest" }]} />
        </div>
      )}

      {mode === "backtest" && patternMode ? (
        <BacktestPanel pattern={pattern} filters={filters} onOpenStock={onOpenStock} />
      ) : (
        <>
          {data && (
            <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
              {data.scan.building
                ? `Scanning the market… ${data.scan.done}/${data.scan.total} stocks analysed. Results fill in as it progresses.`
                : `Scanned ${data.scan.have.toLocaleString("en-IN")} of ${data.scan.universe.toLocaleString("en-IN")} stocks (Nifty Total Market) on their daily charts. Prices are the close of ${new Date((data.scan.prices_as_of ?? 0) * 1000 + 19800000).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" })}.`}
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <SlidingTabs
                ariaLabel="View"
                size="lg"
                value={view}
                onChange={(id) => { setView(id); setPage(1); }}
                options={[
                  { id: "list", label: <span className="flex items-center gap-2"><List className="h-4 w-4" /> List</span> },
                  { id: "charts", label: <span className="flex items-center gap-2"><LineChart className="h-4 w-4" /> Charts</span> },
                ]}
              />
              {view === "charts" && (
                <SlidingTabs ariaLabel="Charts per row" size="lg" value={String(perRow)} onChange={(id) => setPerRow(Number(id) as 1 | 2)} options={[{ id: "1", label: "1 per row" }, { id: "2", label: "2 per row" }]} />
              )}
              {view === "list" && (
                <SlidingTabs ariaLabel="Columns" size="lg" value={colset} onChange={setColset} options={[{ id: "technicals", label: "Technicals" }, { id: "fundamentals", label: "Fundamentals" }]} />
              )}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={sort}
                onChange={(e) => { setSort(e.target.value); setPage(1); }}
                aria-label="Sort by"
                className="h-10 rounded-lg border px-3 text-sm outline-none"
                style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
              >
                {sorts.map(([k, l]) => <option key={k} value={k}>Sort: {l}</option>)}
              </select>
              <button
                onClick={async () => {
                  setExporting(true);
                  try {
                    await downloadCsv(pattern, filters, dq, sort);
                  } finally {
                    setExporting(false);
                  }
                }}
                disabled={exporting || !total}
                title="Download every matching stock as a CSV file"
                aria-label="Download CSV"
                className="flex h-10 items-center gap-2 rounded-lg border px-3 text-sm disabled:opacity-40"
                style={{ borderColor: "var(--accent-border)", color: "var(--accent)" }}
              >
                <Download className="h-4 w-4" /> {exporting ? "Preparing…" : "CSV"}
              </button>
              <div className="relative w-64 max-w-full">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: "var(--text-tertiary)" }} />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search name or ticker"
                  aria-label="Search name or ticker"
                  className="h-10 w-full rounded-lg border pl-9 pr-3 text-sm outline-none"
                  style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}
                />
              </div>
            </div>
          </div>

          <div className="mt-4">
            {res?.error && res.key === key ? (
              <p className="text-sm" style={{ color: "#f5a9a9" }}>{res.error}</p>
            ) : loading && !data ? (
              <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading…</div>
            ) : !data || data.rows.length === 0 ? (
              <div className="rounded-xl border py-16 text-center text-sm" style={{ borderColor: "var(--border-subtle)", color: "var(--text-tertiary)" }}>
                {data?.scan.building
                  ? "No matches yet: the market scan is still running."
                  : data && data.scan.have === 0
                    ? "The market has not been scanned yet."
                    : "No stocks match this scan and these filters right now."}
              </div>
            ) : view === "list" ? (
              <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)", opacity: loading ? 0.6 : 1 }}>
                <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                      {cols.map((c) => <th key={c.key} className={`px-4 py-3 font-semibold ${c.left ? "text-left" : "text-right"}`}>{c.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr
                        key={r.symbol}
                        onClick={() => open(r)}
                        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(r)}
                        tabIndex={0}
                        role="link"
                        aria-label={`Open ${r.name}`}
                        className="cursor-pointer border-t transition-colors hover:bg-[var(--accent-surface)]"
                        style={{ borderColor: "var(--border-subtle)" }}
                      >
                        {cols.map((c) => <td key={c.key} className={`px-4 py-3 ${c.left ? "text-left" : "nv-num text-right"}`}>{c.cell(r)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className={`grid grid-cols-1 gap-4 ${perRow === 2 ? "lg:grid-cols-2" : ""}`} style={{ opacity: loading ? 0.6 : 1 }}>
                {data.rows.map((r) => (
                  <div
                    key={r.symbol}
                    onClick={() => open(r)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(r)}
                    tabIndex={0}
                    role="link"
                    aria-label={`Open ${r.name}`}
                    className="cursor-pointer rounded-xl border p-4 transition-colors hover:border-[var(--accent-border)]"
                    style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}
                  >
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-semibold">{r.name}</div>
                        <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                          {r.symbol} · {r.sector} · ₹{num(r.market_cap_cr, 0)} Cr{r.rs != null ? ` · RS ${r.rs}` : ""}
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="nv-num text-sm font-semibold">₹{num(r.price)}</div>
                        <div className="nv-num text-xs" style={{ color: tone(r.ret_1m) }}>{pct(r.ret_1m)} 1M</div>
                      </div>
                    </div>
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      <StatusBadge row={r} />
                      {(drawResistance || pattern.id === RESISTANCE_ID) && <ResistanceBadge row={r} />}
                    </div>
                    {r.candles && r.candles.length ? (
                      <TvChart bars={r.candles} occurrence={r.occurrence} resistance={drawResistance ? r.resistance : null} height={perRow === 1 ? 420 : 280} />
                    ) : (
                      <div className="py-20 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>{r.candles === undefined ? "Loading chart…" : "Chart data is unavailable for this stock."}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
            <span>{total ? `Showing ${first.toLocaleString("en-IN")} - ${last.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")}` : ""}</span>
            {pages > 1 && (
              <div className="flex items-center gap-2">
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="flex min-h-[40px] items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40 sm:min-h-0" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  <ChevronLeft className="h-3.5 w-3.5" /> Previous
                </button>
                <span className="rounded-lg px-3 py-2 sm:py-1.5" style={{ background: "var(--btn-primary-bg)", color: "#fff" }}>{page} / {pages}</span>
                <button onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages} className="flex min-h-[40px] items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40 sm:min-h-0" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  Next <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
