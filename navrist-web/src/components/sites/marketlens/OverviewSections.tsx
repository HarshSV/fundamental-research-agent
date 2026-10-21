"use client";

import { useState } from "react";

export interface Quarter {
  period: string;
  total_income_cr: number | null;
  pbt_cr: number | null;
  net_profit_cr: number | null;
  eps: number | null;
}

export interface Shareholding {
  quarters: string[];
  promoter: (number | null)[];
  fii: (number | null)[];
  dii: (number | null)[];
  public: (number | null)[];
}

export interface Peer {
  name: string;
  symbol: string;
  metrics: Record<string, { value: number | null } | undefined>;
}

export interface Overview {
  source: string;
  market_cap_cr?: number | null;
  face_value?: number | null;
  eps_ttm?: number | null;
  all_time_high?: { price: number; time: number } | null;
  all_time_low?: { price: number; time: number } | null;
  debt_to_equity?: number | null;
  pe?: number | null;
  about?: string | null;
  quarterly?: Quarter[];
  shareholding?: Shareholding | null;
  peers?: Peer[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const num = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

// "2026-06-31" (period-end marker from the backend) -> "Jun 2026"
function periodLabel(p: string) {
  const [y, m] = p.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

function Unavailable({ what }: { what: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
      {what} is unavailable for this company.
    </div>
  );
}

const BAR_COLORS = { income: "#14b8a6", pbt: "#f59e0b", net: "#3b82f6" };

export function QuarterlyResults({ quarters }: { quarters: Quarter[] }) {
  const [tab, setTab] = useState<"results" | "eps">("results");
  const last = quarters.slice(-4);
  // ₹ Crore -> ₹ Lakhs
  const L = (v: number | null) => (v == null ? null : v * 100);
  const series = tab === "results"
    ? [
        { key: "Total Income", color: BAR_COLORS.income, get: (q: Quarter) => L(q.total_income_cr) },
        { key: "Profit Before Tax", color: BAR_COLORS.pbt, get: (q: Quarter) => L(q.pbt_cr) },
        { key: "Net Profit/Loss", color: BAR_COLORS.net, get: (q: Quarter) => L(q.net_profit_cr) },
      ]
    : [{ key: "EPS (₹)", color: BAR_COLORS.income, get: (q: Quarter) => q.eps }];
  const vals = last.flatMap((q) => series.map((s) => s.get(q))).filter((v): v is number => v != null);
  const max = Math.max(...vals, 0);
  const min = Math.min(...vals, 0);
  const span = max - min || 1;
  const H = 220;
  const zeroY = (max / span) * H;

  return (
    <div>
      <div className="mb-4 flex gap-1 rounded-lg p-1" style={{ background: "var(--overlay-weak)" }}>
        {(["results", "eps"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ background: tab === t ? "#b7b4e7" : "transparent", color: tab === t ? "var(--on-accent)" : "var(--text-secondary)" }}
          >
            {t === "results" ? "Results" : "Earnings Per Share"}
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
            {s.key}
          </span>
        ))}
      </div>
      <div className="relative flex items-stretch gap-3" style={{ height: H + 28 }}>
        {last.map((q) => (
          <div key={q.period} className="flex flex-1 flex-col">
            <div className="relative flex flex-1 items-start justify-center gap-1.5" style={{ height: H }}>
              <div className="absolute inset-x-0 border-t" style={{ top: zeroY, borderColor: "var(--grid)" }} />
              {series.map((s) => {
                const v = s.get(q);
                if (v == null) return <div key={s.key} className="w-5" title="Unavailable" />;
                const barH = (Math.abs(v) / span) * H;
                return (
                  <div
                    key={s.key}
                    title={`${s.key}: ${num(v, tab === "eps" ? 2 : 0)}`}
                    className="absolute w-5 rounded-sm"
                    style={{
                      background: s.color,
                      height: Math.max(barH, 2),
                      top: v >= 0 ? zeroY - barH : zeroY,
                      left: `calc(50% + ${(series.indexOf(s) - (series.length - 1) / 2) * 26 - 10}px)`,
                    }}
                  />
                );
              })}
            </div>
            <div className="mt-2 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>{periodLabel(q.period)}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        Hover a bar for its value. Source: Screener.in.
      </p>
    </div>
  );
}

const SH_COLORS: Record<string, string> = { promoter: "#14b8a6", fii: "#8b5cf6", dii: "#3b82f6", public: "#ea580c" };
const SH_LABELS: Record<string, string> = { promoter: "Promoter & Promoter Group", fii: "FII", dii: "DII", public: "Public" };

export function ShareholdingPattern({ data }: { data: Shareholding }) {
  const idxs = data.quarters.map((_, i) => i).slice(-5).reverse();
  const [sel, setSel] = useState(idxs[0]);
  const keys = ["promoter", "fii", "dii", "public"] as const;
  const parts = keys.map((k) => ({ k, v: data[k][sel] }));
  const known = parts.filter((p): p is { k: (typeof keys)[number]; v: number } => p.v != null && p.v > 0);
  const total = known.reduce((a, p) => a + p.v, 0) || 1;
  const R = 70;
  const C = 2 * Math.PI * R;
  let acc = 0;

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-1 rounded-lg p-1" style={{ background: "var(--overlay-weak)" }}>
        {idxs.map((i) => (
          <button
            key={i}
            onClick={() => setSel(i)}
            className="rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ background: sel === i ? "#b7b4e7" : "transparent", color: sel === i ? "var(--on-accent)" : "var(--text-secondary)" }}
          >
            {data.quarters[i]}
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
        {keys.map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: SH_COLORS[k] }} />
            {SH_LABELS[k]}
          </span>
        ))}
      </div>
      <div className="flex justify-center py-4">
        <svg width="220" height="220" viewBox="0 0 220 220">
          <g transform="translate(110 110) rotate(-90)">
            {known.map((p) => {
              const len = (p.v / total) * C;
              const el = (
                <circle key={p.k} r={R} fill="none" stroke={SH_COLORS[p.k]} strokeWidth="28" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-acc}>
                  <title>{`${SH_LABELS[p.k]}: ${num(p.v)}%`}</title>
                </circle>
              );
              acc += len;
              return el;
            })}
          </g>
        </svg>
      </div>
      <div className="grid grid-cols-2 gap-4 border-t pt-4 text-sm md:grid-cols-4" style={{ borderColor: "var(--border-subtle)" }}>
        {parts.map((p) => (
          <div key={p.k}>
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{SH_LABELS[p.k]}</div>
            <div className="font-semibold">{p.v == null ? "—" : `${num(p.v)}%`}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function About({ text }: { text: string }) {
  return <p className="max-w-5xl text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{text}</p>;
}

export function PeerTable({ peers, current }: { peers: Peer[]; current: string }) {
  const head = ["Company", "Price", "Market Cap", "P/E Ratio", "ROCE %"];
  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
            {head.map((h, i) => (
              <th key={h} className={`px-5 py-3 font-semibold ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {peers.map((p) => {
            const m = p.metrics;
            const isSelf = p.symbol === current.toUpperCase();
            return (
              <tr key={p.symbol} className="border-t" style={{ borderColor: "var(--border-subtle)", background: isSelf ? "var(--accent-surface)" : undefined }}>
                <td className="px-5 py-3.5">
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{p.symbol}</div>
                </td>
                <td className="px-5 py-3.5 text-right font-semibold">{m.currentPrice?.value == null ? "—" : `₹${num(m.currentPrice.value)}`}</td>
                <td className="px-5 py-3.5 text-right">{m.marketCapitalization?.value == null ? "—" : `₹${num(m.marketCapitalization.value)} Cr`}</td>
                <td className="px-5 py-3.5 text-right">{num(m.priceToEarning?.value ?? null)}</td>
                <td className="px-5 py-3.5 text-right">{num(m.returnOnCapitalEmployed?.value ?? null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export { Unavailable };
