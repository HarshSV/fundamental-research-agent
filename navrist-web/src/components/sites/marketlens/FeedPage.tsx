"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/api";
import { SlidingTabs } from "./controls";
import type { FeedName } from "./scanners";

type Row = Record<string, string | number | boolean | null | undefined>;
interface Feed { rows: Row[]; as_of?: string; note?: string | null; quarter?: string; year?: number; years?: number[]; from?: string; to?: string }
interface Col { key: string; label: string; right?: boolean; sort?: boolean; cell?: (r: Row) => React.ReactNode }

const num = (v: unknown, d = 2) => (typeof v === "number" ? v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—");
const pct = (v: unknown, d = 1) => (typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const pp = (v: unknown) => (typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(1)} pp` : "—");
const tone = (v: unknown) => (typeof v !== "number" || v === 0 ? "var(--text-primary)" : v > 0 ? "var(--gain)" : "var(--loss)");
const colored = (f: (v: unknown) => string) => (key: string) => (r: Row) => <span className="nv-num" style={{ color: tone(r[key]) }}>{f(r[key])}</span>;
const cap = (r: Row) => num(r.market_cap_cr, 0);

function stockCell(open: (s: { symbol: string; name: string }) => void) {
  return (r: Row) => (
    <button type="button" onClick={() => open({ symbol: String(r.symbol), name: String(r.name ?? r.symbol) })} className="text-left hover:text-[var(--accent)]">
      <div className="font-semibold">{String(r.name ?? r.symbol)}</div>
      <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{String(r.symbol)}</div>
    </button>
  );
}

const TITLES: Record<FeedName, { title: string; blurb: string }> = {
  "results-calendar": { title: "Results Calendar", blurb: "Companies that filed quarterly results lately or have announced a board meeting for them. Growth columns appear for the stocks Navrist reads quarterly figures for." },
  "circuit-revisions": { title: "Circuit Revision List", blurb: "Stocks whose daily price band changed, newest first." },
  "order-wins": { title: "Order Wins", blurb: "Order and contract announcements filed with NSE in the last two weeks." },
  deals: { title: "Deals", blurb: "Large trades reported by the exchange." },
  asm: { title: "ASM List", blurb: "Stocks under NSE's additional surveillance measure, long term and short term." },
  "sector-indices": { title: "Sector Indices", blurb: "How each NSE index is doing today." },
  "recent-ipos": { title: "Recent IPOs", blurb: "Everything listed on NSE in the last year." },
  "past-winners": { title: "Past Winners", blurb: "The best performers of a year among the stocks Navrist scans." },
};

function columns(name: FeedName, open: (s: { symbol: string; name: string }) => void): Col[] {
  const stock: Col = { key: "name", label: "Stock", sort: true, cell: stockCell(open) };
  switch (name) {
    case "results-calendar":
      return [stock, { key: "date", label: "Date", sort: true, cell: (r) => `${r.date}${r.time ? " " + r.time : ""}` },
        { key: "status", label: "Status", sort: true, cell: (r) => <span className="rounded-full px-2.5 py-0.5 text-[11px] font-medium" style={{ background: r.status === "Announced" ? "var(--accent-surface)" : "var(--overlay)", color: r.status === "Announced" ? "var(--accent)" : "var(--text-secondary)" }}>{String(r.status)}</span> },
        { key: "eps_qoq", label: "EPS QoQ", right: true, sort: true, cell: colored(pct)("eps_qoq") }, { key: "eps_yoy", label: "EPS YoY", right: true, sort: true, cell: colored(pct)("eps_yoy") },
        { key: "sales_qoq", label: "Sales QoQ", right: true, sort: true, cell: colored(pct)("sales_qoq") }, { key: "sales_yoy", label: "Sales YoY", right: true, sort: true, cell: colored(pct)("sales_yoy") },
        { key: "opm_qoq_pp", label: "OPM QoQ", right: true, sort: true, cell: colored(pp)("opm_qoq_pp") }, { key: "opm_yoy_pp", label: "OPM YoY", right: true, sort: true, cell: colored(pp)("opm_yoy_pp") }];
    case "circuit-revisions":
      return [{ key: "date", label: "Effective", sort: true }, stock, { key: "from", label: "From band", right: true, cell: (r) => `${r.from}%` }, { key: "to", label: "To band", right: true, cell: (r) => <b>{String(r.to)}%</b> },
        { key: "industry", label: "Industry", sort: true }, { key: "market_cap_cr", label: "Market cap (₹ Cr)", right: true, sort: true, cell: cap }];
    case "order-wins":
      return [{ key: "time", label: "Filed", sort: true }, stock, { key: "subject", label: "Subject" },
        { key: "text", label: "Details", cell: (r) => <div className="max-w-[420px] text-xs leading-snug" style={{ color: "var(--text-secondary)" }}>{String(r.text ?? "")}</div> },
        { key: "file", label: "Filing", cell: (r) => (r.file ? <a href={String(r.file)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs underline" style={{ color: "var(--accent)" }}>Open <ExternalLink className="h-3 w-3" /></a> : "—") }];
    case "deals":
      return [{ key: "date", label: "Date", sort: true }, stock, { key: "client", label: "Client", sort: true }, { key: "side", label: "Side", sort: true, cell: (r) => <b style={{ color: r.side === "BUY" ? "var(--gain)" : "var(--loss)" }}>{String(r.side)}</b> },
        { key: "qty", label: "Quantity", right: true, sort: true, cell: (r) => num(r.qty, 0) }, { key: "price", label: "Price (₹)", right: true, sort: true, cell: (r) => num(r.price) },
        { key: "value_cr", label: "Value (₹ Cr)", right: true, sort: true, cell: (r) => num(typeof r.qty === "number" && typeof r.price === "number" ? (r.qty * r.price) / 1e7 : null) }];
    case "asm":
      return [stock, { key: "kind", label: "Type", sort: true, cell: (r) => (r.kind === "LT" ? "Long term" : "Short term") }, { key: "stage", label: "Stage", sort: true }, { key: "code", label: "Code" },
        { key: "date", label: "Since" }, { key: "market_cap_cr", label: "Market cap (₹ Cr)", right: true, sort: true, cell: cap }];
    case "sector-indices":
      return [{ key: "index", label: "Index", sort: true, cell: (r) => <b>{String(r.index)}</b> }, { key: "key", label: "Group" }, { key: "last", label: "Last", right: true, sort: true, cell: (r) => num(r.last) },
        { key: "variation", label: "Change", right: true, sort: true, cell: colored((v) => (typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}` : "—"))("variation") },
        { key: "percentChange", label: "Change %", right: true, sort: true, cell: colored((v) => pct(v, 2))("percentChange") }, { key: "yearHigh", label: "52W high", right: true, sort: true, cell: (r) => num(r.yearHigh) },
        { key: "yearLow", label: "52W low", right: true, sort: true, cell: (r) => num(r.yearLow) }, { key: "perChange30d", label: "30 days", right: true, sort: true, cell: colored(pct)("perChange30d") },
        { key: "perChange365d", label: "1 year", right: true, sort: true, cell: colored(pct)("perChange365d") }, { key: "pe", label: "P/E", right: true, sort: true, cell: (r) => num(r.pe) }];
    case "recent-ipos":
      return [stock, { key: "listed", label: "Listed", sort: true }, { key: "face_value", label: "Face value", right: true }, { key: "price", label: "Price (₹)", right: true, sort: true, cell: (r) => num(r.price) },
        { key: "ret_1m", label: "1 month", right: true, sort: true, cell: colored(pct)("ret_1m") }, { key: "market_cap_cr", label: "Market cap (₹ Cr)", right: true, sort: true, cell: cap }];
    case "past-winners":
      return [{ key: "rank", label: "#", right: true, cell: (r) => String(r.rank) }, stock, { key: "sector", label: "Sector", sort: true }, { key: "industry", label: "Industry", sort: true },
        { key: "return_pct", label: "Return", right: true, sort: true, cell: colored(pct)("return_pct") }, { key: "market_cap_cr", label: "Market cap (₹ Cr)", right: true, sort: true, cell: cap }];
  }
}

export function FeedPage({ name, kind, onBack, onOpenStock }: { name: FeedName; kind?: "bulk" | "block"; onBack: () => void; onOpenStock: (s: { symbol: string; name: string }) => void }) {
  const [deal, setDeal] = useState<"bulk" | "block">(kind ?? "bulk");
  const [year, setYear] = useState<number | null>(null);
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [data, setData] = useState<Feed | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [status, setStatus] = useState<string>("all");
  const [group, setGroup] = useState<string>("SECTORAL INDICES");

  const url = useMemo(() => {
    const p = new URLSearchParams();
    if (name === "deals") p.set("kind", deal);
    if (name === "past-winners" && year) p.set("year", String(year));
    if (name === "results-calendar" && range) {
      p.set("start", range.from);
      p.set("end", range.to);
    }
    return `/api/v1/market/feed/${name}${p.toString() ? "?" + p.toString() : ""}`;
  }, [name, deal, year, range]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setError("");
    const load = (tries: number) =>
      fetchJson<Feed>(url)
        .then((d) => {
          if (!alive) return;
          setData(d);
          // the exchange files are read in the background the first time: look again shortly
          if (d.rows.length === 0 && d.note && /not been read/.test(d.note) && tries < 8) timer = setTimeout(() => load(tries + 1), 6000);
        })
        .catch((e: Error) => alive && setError(e.message));
    load(0);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [url]);

  const cols = useMemo(() => columns(name, onOpenStock), [name, onOpenStock]);
  const rows = useMemo(() => {
    let r: Row[] = (data?.rows ?? []).map((x, i) => ({ ...x, rank: i + 1 }));
    const t = q.trim().toLowerCase();
    if (t) r = r.filter((x) => Object.values(x).some((v) => typeof v === "string" && v.toLowerCase().includes(t)));
    if (name === "results-calendar" && status !== "all") r = r.filter((x) => x.status === status);
    if (name === "sector-indices" && group !== "all") r = r.filter((x) => x.key === group);
    if (sort) r = [...r].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return typeof x === "number" && typeof y === "number" ? sort.dir * (x - y) : sort.dir * String(x).localeCompare(String(y));
    });
    return r;
  }, [data, q, sort, status, name, group]);

  const [page, setPage] = useState(1);
  const SIZE = 50;
  useEffect(() => setPage(1), [q, sort, status, url, group]);
  const pages = Math.max(1, Math.ceil(rows.length / SIZE));
  const shown = rows.slice((page - 1) * SIZE, page * SIZE);
  const meta = TITLES[name];

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <h1 className="text-3xl font-bold tracking-tight">{name === "deals" ? (deal === "bulk" ? "Bulk Deals" : "Block Deals") : meta.title}{data?.quarter && name === "results-calendar" ? ` · ${data.quarter} quarter` : ""}</h1>
      <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>{meta.blurb}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {name === "deals" && <SlidingTabs ariaLabel="Deal type" value={deal} onChange={setDeal} options={[{ id: "bulk", label: "Bulk" }, { id: "block", label: "Block" }]} />}
        {name === "past-winners" && data?.years && <SlidingTabs ariaLabel="Year" value={String(year ?? data.year ?? "")} onChange={(v) => setYear(Number(v))} options={data.years.map((y) => ({ id: String(y), label: String(y) }))} />}
        {name === "sector-indices" && data && (
          <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Index group" className="min-h-[44px] rounded-xl border bg-transparent px-3 text-sm sm:min-h-[40px]" style={{ borderColor: "var(--border-default)", background: "var(--surface-1)", color: "var(--text-primary)" }}>
            <option value="all">All indices</option>
            {[...new Set(data.rows.map((r) => String(r.key ?? "")).filter(Boolean))].map((k) => <option key={k} value={k}>{k.charAt(0) + k.slice(1).toLowerCase()}</option>)}
          </select>
        )}
        {name === "results-calendar" && (
          <>
            <SlidingTabs ariaLabel="Status" value={status} onChange={setStatus} options={[{ id: "all", label: "All" }, { id: "Announced", label: "Announced" }, { id: "Upcoming", label: "Upcoming" }]} />
            <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>From
              <input type="date" value={range?.from ?? data?.from ?? ""} onChange={(e) => setRange({ from: e.target.value, to: range?.to ?? data?.to ?? e.target.value })} className="min-h-[40px] rounded-lg border bg-transparent px-2 sm:min-h-0 sm:py-1" style={{ borderColor: "var(--border-default)" }} />
            </label>
            <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>To
              <input type="date" value={range?.to ?? data?.to ?? ""} onChange={(e) => setRange({ from: range?.from ?? data?.from ?? e.target.value, to: e.target.value })} className="min-h-[40px] rounded-lg border bg-transparent px-2 sm:min-h-0 sm:py-1" style={{ borderColor: "var(--border-default)" }} />
            </label>
          </>
        )}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search this list" aria-label="Search this list" className="min-h-[44px] w-full max-w-xs rounded-xl border px-3 text-sm outline-none sm:min-h-[40px]" style={{ borderColor: "var(--border-default)", background: "var(--surface-1)" }} />
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{data ? `${rows.length} row${rows.length === 1 ? "" : "s"}${data.as_of ? ` · as of ${data.as_of}` : ""}` : ""}</span>
      </div>
      {error && <p className="mt-4 text-sm" style={{ color: "#f5a9a9" }}>Could not load this list: {error}</p>}
      {!data && !error && <p className="mt-10 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading…</p>}
      {data && (
        <>
          <div className="mt-4 overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
            <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                  {cols.map((c) => (
                    <th key={c.key} className={`whitespace-nowrap px-3 py-3 font-semibold sm:px-4 ${c.right ? "text-right" : "text-left"}`}>
                      {c.sort ? (
                        <button type="button" className="inline-flex min-h-[32px] items-center gap-1" onClick={() => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: c.right ? -1 : 1 }))}>
                          {c.label}{sort?.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                        </button>
                      ) : c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={i} className="border-t align-top" style={{ borderColor: "var(--border-subtle)" }}>
                    {cols.map((c) => (
                      <td key={c.key} className={`px-3 py-3 sm:px-4 ${c.right ? "nv-num text-right" : ""}`}>{c.cell ? c.cell(r) : r[c.key] == null || r[c.key] === "" ? "—" : String(r[c.key])}</td>
                    ))}
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr><td colSpan={cols.length} className="px-4 py-10 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>{data.note && /not been read/.test(data.note) ? "Reading the exchange files for the first time, this takes about a minute…" : "Nothing to show."}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div className="mt-3 flex items-center justify-end gap-2 text-sm">
              <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="min-h-[40px] rounded-lg border px-3 disabled:opacity-40 sm:min-h-0 sm:py-1.5" style={{ borderColor: "var(--border-default)" }}>Previous</button>
              <span className="rounded-lg px-3 py-2 text-white sm:py-1.5" style={{ background: "var(--btn-primary-bg)" }}>{page} / {pages}</span>
              <button type="button" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="min-h-[40px] rounded-lg border px-3 disabled:opacity-40 sm:min-h-0 sm:py-1.5" style={{ borderColor: "var(--border-default)" }}>Next</button>
            </div>
          )}
          {data.note && <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>{data.note}</p>}
        </>
      )}
    </div>
  );
}
