"use client";

import { ArrowLeft, ArrowDown, ArrowUp, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import { METRIC_FMT, type StockRow, type UniverseStatus } from "./screens";

/** Results list shared by sector pages and screen pages. Rows open the stock page. */
export function StockList({
  title, description, criteria, stocks, universe, loading, error, extraMetrics = [], onBack, onSelect,
}: {
  title: string;
  description?: string;
  criteria?: string[];
  stocks: StockRow[] | null;
  universe?: UniverseStatus;
  loading: boolean;
  error?: string;
  extraMetrics?: string[]; // metric keys beyond the default columns (e.g. what a screen matched on)
  onBack: () => void;
  onSelect: (s: CompanyHit) => void;
}) {
  const base = ["price", "market_cap_cr", "pe"];
  const cols = [...base, ...extraMetrics.filter((m) => !base.includes(m))];
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "market_cap_cr", dir: -1 });

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (stocks ?? []).filter((s) => !needle || s.name.toLowerCase().includes(needle) || s.symbol.toLowerCase().includes(needle));
    const val = (s: StockRow) => (sort.key === "name" ? null : (s[sort.key] as number | null | undefined) ?? (s.matched?.[sort.key] ?? null));
    return [...list].sort((a, b) => {
      if (sort.key === "name") return sort.dir * a.name.localeCompare(b.name);
      const x = val(a);
      const y = val(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1; // unknown values always sort last
      if (y == null) return -1;
      return sort.dir * (x - y);
    });
  }, [stocks, q, sort]);

  const th = (key: string, label: string, left = false) => (
    <th key={key} className={`px-4 py-3 font-semibold ${left ? "text-left" : "text-right"}`}>
      <button
        onClick={() => setSort((s) => (s.key === key ? { key, dir: (-s.dir) as 1 | -1 } : { key, dir: key === "name" ? 1 : -1 }))}
        className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-[var(--accent)]"
      >
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );

  const cell = (s: StockRow, key: string) => {
    const v = (s[key] as number | null | undefined) ?? s.matched?.[key] ?? null;
    const f = METRIC_FMT[key];
    return v == null || !f ? "—" : f.fmt(v);
  };

  const building = universe?.building;
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-5 flex items-center gap-2 text-sm hover:text-[var(--accent)]" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
      {description && <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>{description}</p>}
      {criteria && criteria.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span style={{ color: "var(--text-tertiary)" }}>Criteria:</span>
          {criteria.map((c) => (
            <span key={c} className="rounded-full border px-2.5 py-1" style={{ borderColor: "var(--accent-border)", background: "var(--accent-surface)", color: "var(--accent)" }}>{c}</span>
          ))}
        </div>
      )}
      {universe && (
        <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
          {building
            ? `Preparing screening data… ${universe.done}/${universe.total} companies. Results fill in as it progresses.`
            : `Screened universe: ${universe.have.toLocaleString("en-IN")} of ${universe.universe.toLocaleString("en-IN")} NSE-classified companies with data. A company is only listed when every metric a criterion needs is known.`}
        </p>
      )}

      <div className="relative mb-4 mt-5 max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: "var(--text-tertiary)" }} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by name or symbol"
          className="h-10 w-full rounded-lg border pl-9 pr-3 text-sm outline-none"
          style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}
        />
      </div>

      {error ? (
        <p className="text-sm" style={{ color: "#f5a9a9" }}>{error}</p>
      ) : loading || stocks === null ? (
        <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border py-16 text-center text-sm" style={{ borderColor: "var(--border-subtle)", color: "var(--text-tertiary)" }}>
          {building ? "No matches yet — the screening data is still being prepared." : "No companies match these criteria."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                {th("name", "Company", true)}
                {cols.map((c) => th(c, METRIC_FMT[c]?.label ?? c))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr
                  key={s.symbol}
                  onClick={() => onSelect({ symbol: s.symbol, name: s.name })}
                  className="cursor-pointer border-t transition-colors hover:bg-[var(--accent-surface)]"
                  style={{ borderColor: "var(--border-subtle)" }}
                >
                  <td className="px-4 py-3">
                    <div className="font-semibold">{s.name}</div>
                    <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{s.symbol}</div>
                  </td>
                  {cols.map((c) => (
                    <td key={c} className="nv-num px-4 py-3 text-right">{cell(s, c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>{rows.length} companies shown</p>
    </div>
  );
}
