"use client";

import { ArrowLeft, ChevronLeft, ChevronRight, LineChart, List, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import { STATUS_COLOR, STATUS_LABEL, type CatalogueEntry } from "./patterns";
import { describeFilters, searchScan, type ScanFilters, type ScanOptions, type ScanResult, type ScanRow } from "./patternScan";
import { TvChart } from "./TvChart";

const LIST_SIZE = 50;
const CHART_SIZE = 20;
const GAIN = "var(--gain)";
const LOSS = "var(--loss)";

const inr = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);

function StatusBadge({ row }: { row: ScanRow }) {
  const s = row.occurrence.status;
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={{ background: `${STATUS_COLOR[s]}22`, color: STATUS_COLOR[s] }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[s] }} />
      {STATUS_LABEL[s]}
      {row.occurrence.direction && <span style={{ opacity: 0.8 }}>· {row.occurrence.direction}</span>}
    </span>
  );
}

/**
 * Stocks currently showing one chart pattern, after the filters picked in the popup. A List / Charts switch (the chart
 * view draws each stock's daily candles with TradingView's Lightweight Charts, the pattern's lines and its breakout and
 * invalidation levels), a name / ticker search, pages, and a click on any row or card opens that stock.
 */
export function PatternScanPage({
  pattern, filters, options, onBack, onEdit, onOpenStock,
}: {
  pattern: CatalogueEntry;
  filters: ScanFilters;
  options: ScanOptions | null;
  onBack: () => void;
  onEdit: () => void;
  onOpenStock: (s: CompanyHit) => void;
}) {
  const [view, setView] = useState<"list" | "charts">("list");
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [sort, setSort] = useState("status");
  const [page, setPage] = useState(1);
  const [res, setRes] = useState<{ key: string; data?: ScanResult; error?: string } | null>(null);

  // debounce the search box; any change of search / sort / view / filters starts again from page 1
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
    let alive = true;
    searchScan(pattern.id, filters, { q: dq, page, page_size: size, sort }, view === "charts")
      .then((data) => alive && setRes({ key, data }))
      .catch((e: Error) => alive && setRes({ key, error: e.message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` already captures every input below
  }, [key]);

  // a running scan fills results in over time: refresh while it works
  const scanning = res?.data?.scan.building;
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!scanning) return;
    const t = setInterval(() => setTick((n) => n + 1), 15000);
    return () => clearInterval(t);
  }, [scanning]);
  useEffect(() => {
    if (!tick) return;
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
  const open = (r: ScanRow) => onOpenStock({ symbol: r.symbol, name: r.name });

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-5 flex items-center gap-2 text-sm hover:text-[var(--accent)]" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{pattern.name}</h1>
          <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Stocks showing this pattern on the daily chart right now: forming, awaiting breakout, or confirmed in the last 10 sessions. It describes how the
            shape has formed, not a forecast.
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

      {data && (
        <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
          {data.scan.building
            ? `Scanning the market… ${data.scan.done}/${data.scan.total} stocks analysed. Results fill in as it progresses.`
            : `Scanned ${data.scan.have.toLocaleString("en-IN")} of ${data.scan.universe.toLocaleString("en-IN")} stocks (Nifty Total Market) on their daily charts.`}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-xl border p-1" style={{ borderColor: "var(--accent-border)" }}>
          {([["list", "List", List], ["charts", "Charts", LineChart]] as const).map(([id, label, Icon]) => (
            <button
              key={id}
              onClick={() => {
                setView(id);
                setPage(1);
              }}
              className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              style={{ background: view === id ? "var(--btn-primary-bg)" : "transparent", color: view === id ? "#fff" : "var(--text-secondary)" }}
            >
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(1);
            }}
            aria-label="Sort by"
            className="h-10 rounded-lg border px-3 text-sm outline-none"
            style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          >
            <option value="status">Sort: closest to breakout</option>
            <option value="market_cap">Sort: market cap</option>
            <option value="name">Sort: name</option>
          </select>
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
        ) : loading ? (
          <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading…</div>
        ) : !data || data.rows.length === 0 ? (
          <div className="rounded-xl border py-16 text-center text-sm" style={{ borderColor: "var(--border-subtle)", color: "var(--text-tertiary)" }}>
            {data?.scan.building
              ? "No matches yet: the market scan is still running."
              : data && data.scan.have === 0
                ? "The market has not been scanned yet."
                : "No stocks match this pattern and these filters right now."}
          </div>
        ) : view === "list" ? (
          <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                  <th className="px-4 py-3 text-left font-semibold">Stock</th>
                  <th className="px-4 py-3 text-left font-semibold">Sector</th>
                  <th className="px-4 py-3 text-right font-semibold">Market cap (₹ Cr)</th>
                  <th className="px-4 py-3 text-right font-semibold">Price</th>
                  <th className="px-4 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-right font-semibold">Breakout</th>
                  <th className="px-4 py-3 text-right font-semibold">1M</th>
                  <th className="px-4 py-3 text-right font-semibold">3M</th>
                  <th className="px-4 py-3 text-right font-semibold">From 52W high</th>
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
                    <td className="px-4 py-3">
                      <div className="font-semibold">{r.name}</div>
                      <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{r.symbol}</div>
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-secondary)" }}>{r.sector}</td>
                    <td className="nv-num px-4 py-3 text-right">{inr(r.market_cap_cr, 0)}</td>
                    <td className="nv-num px-4 py-3 text-right">₹{inr(r.price)}</td>
                    <td className="px-4 py-3"><StatusBadge row={r} /></td>
                    <td className="nv-num px-4 py-3 text-right">{r.occurrence.breakout == null ? "—" : `₹${inr(r.occurrence.breakout)}`}</td>
                    <td className="nv-num px-4 py-3 text-right" style={{ color: tone(r.ret_1m) }}>{pct(r.ret_1m)}</td>
                    <td className="nv-num px-4 py-3 text-right" style={{ color: tone(r.ret_3m) }}>{pct(r.ret_3m)}</td>
                    <td className="nv-num px-4 py-3 text-right">{r.pct_from_52w_high == null ? "—" : `${r.pct_from_52w_high.toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
                      {r.symbol} · {r.sector} · ₹{inr(r.market_cap_cr, 0)} Cr
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="nv-num text-sm font-semibold">₹{inr(r.price)}</div>
                    <div className="nv-num text-xs" style={{ color: tone(r.ret_1m) }}>{pct(r.ret_1m)} 1M</div>
                  </div>
                </div>
                <div className="mb-2"><StatusBadge row={r} /></div>
                {r.candles && r.candles.length ? (
                  <TvChart bars={r.candles} occurrence={r.occurrence} height={280} />
                ) : (
                  <div className="py-20 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>Chart data is unavailable for this stock.</div>
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
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="flex items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40"
              style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Previous
            </button>
            <span className="rounded-lg px-3 py-1.5" style={{ background: "var(--btn-primary-bg)", color: "#fff" }}>{page} / {pages}</span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="flex items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40"
              style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            >
              Next <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
