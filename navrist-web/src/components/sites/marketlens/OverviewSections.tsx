"use client";

import { useRef, useState } from "react";

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
  return_bases?: Record<string, { price: number; date: string }>;
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

function Unavailable({ what }: { what: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
      {what} is unavailable for this company.
    </div>
  );
}

const BAR_COLORS = { income: "#14b8a6", pbt: "#f59e0b", net: "#3b82f6" };

// Indian short format used on the axis: 80K, 1.6L, 2.4L (negatives keep the sign)
function axisLabel(v: number) {
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  const trim = (n: number) => String(Math.round(n * 10) / 10);
  if (a >= 1e5) return `${sign}${trim(a / 1e5)}L`;
  if (a >= 1e3) return `${sign}${trim(a / 1e3)}K`;
  return `${sign}${trim(a)}`;
}

// 4-5 "nice" gridline values covering [min, max]
function niceTicks(min: number, max: number) {
  const span = max - min || 1;
  const raw = span / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.abs(t) < step / 1e6 ? 0 : t);
  return ticks;
}

// "2026-06-30" -> "30 Jun 2026"
function dayLabel(p: string) {
  const [y, m, d] = p.split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

export type FinTab = "results" | "eps";

/** Last four reported quarters, newest first (as on the exchange's page). Amounts in ₹ Lakhs; hover a quarter for
 *  its exact figures. A quarter whose value is unavailable draws no bar and reads "—" in the tooltip. */
export function QuarterlyResults({ quarters, tab, onTab }: { quarters: Quarter[]; tab: FinTab; onTab: (t: FinTab) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const last = quarters.slice(-4).reverse();
  // ₹ Crore -> ₹ Lakhs
  const L = (v: number | null) => (v == null ? null : v * 100);
  const series = tab === "results"
    ? [
        { key: "Total Income", color: BAR_COLORS.income, get: (q: Quarter) => L(q.total_income_cr) },
        { key: "Profit Before Tax", color: BAR_COLORS.pbt, get: (q: Quarter) => L(q.pbt_cr) },
        { key: "Net Profit/Loss", color: BAR_COLORS.net, get: (q: Quarter) => L(q.net_profit_cr) },
      ]
    : [{ key: "EPS", color: BAR_COLORS.income, get: (q: Quarter) => q.eps }];
  const vals = last.flatMap((q) => series.map((s) => s.get(q))).filter((v): v is number => v != null);
  const ticks = niceTicks(Math.min(...vals, 0), Math.max(...vals, 0));
  const top = ticks[ticks.length - 1];
  const bottom = ticks[0];
  const span = top - bottom || 1;
  const H = 220;
  const y = (v: number) => ((top - v) / span) * H;
  const money = (v: number | null) =>
    v == null ? "—" : tab === "eps" ? `₹${num(v, 2)}` : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  const barW = tab === "eps" ? 36 : 16;

  return (
    <div>
      <div className="mb-4 flex gap-1 rounded-lg p-1" style={{ background: "var(--overlay-weak)" }}>
        {(["results", "eps"] as const).map((t) => (
          <button
            key={t}
            onClick={() => onTab(t)}
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
            {s.key === "EPS" ? "Earnings Per Share" : s.key}
          </span>
        ))}
      </div>
      <div className="flex" onMouseLeave={() => setHover(null)}>
        <div className="relative w-10 shrink-0 text-right text-[11px]" style={{ height: H, color: "var(--text-tertiary)" }}>
          {ticks.map((t) => (
            <span key={t} className="absolute right-1.5 -translate-y-1/2" style={{ top: y(t) }}>{axisLabel(t)}</span>
          ))}
        </div>
        <div className="relative flex-1" style={{ height: H + 22 }}>
          <div className="absolute inset-x-0 top-0" style={{ height: H }}>
            {ticks.map((t) => (
              <div key={t} className="absolute inset-x-0 border-t" style={{ top: y(t), borderColor: "var(--grid)" }} />
            ))}
          </div>
          <div className="absolute inset-x-0 top-0 flex" style={{ height: H + 22 }}>
            {last.map((q, qi) => (
              <div key={q.period} className="relative flex-1" onMouseEnter={() => setHover(qi)} onMouseMove={() => setHover(qi)}>
                {hover === qi && <div className="absolute inset-x-1 top-0 rounded-sm" style={{ height: H + 22, background: "var(--overlay-weak)" }} />}
                <div className="absolute inset-x-0 top-0 flex items-start justify-center gap-1" style={{ height: H }}>
                  {series.map((s) => {
                    const v = s.get(q);
                    if (v == null) return <div key={s.key} style={{ width: barW }} />;
                    const h = Math.max(Math.abs(y(v) - y(0)), 2);
                    return (
                      <div key={s.key} className="relative" style={{ width: barW, height: H }}>
                        <div className="absolute w-full rounded-sm" style={{ background: s.color, height: h, top: v >= 0 ? y(0) - h : y(0) }} />
                      </div>
                    );
                  })}
                </div>
                <div className="absolute inset-x-0 text-center text-[11px]" style={{ top: H + 6, color: "var(--text-tertiary)" }}>{dayLabel(q.period)}</div>
                {hover === qi && (
                  <div
                    className="pointer-events-none absolute z-10 w-max rounded-lg px-3 py-2 text-xs shadow-lg"
                    style={{
                      top: 24,
                      [qi >= last.length - 2 ? "right" : "left"]: "calc(50% + 8px)",
                      background: "var(--surface-2, #0f0f14)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div className="mb-1 font-medium" style={{ color: "var(--text-primary)" }}>{dayLabel(q.period)}</div>
                    {series.map((s) => (
                      <div key={s.key} style={{ color: s.color }}>{s.key} : {money(s.get(q))}</div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        Consolidated results (parent plus subsidiaries), latest four quarters, newest first. Source: Screener.in.
      </p>
    </div>
  );
}

const SH_COLORS: Record<string, string> = { promoter: "#14b8a6", fii: "#ec4899", dii: "#3b82f6", public: "#f97316" };
const SH_LABELS: Record<string, string> = { promoter: "Promoter & Promoter Group", fii: "FII", dii: "DII", public: "Public" };

export function ShareholdingPattern({ data }: { data: Shareholding }) {
  const idxs = data.quarters.map((_, i) => i).slice(-5).reverse();
  const [sel, setSel] = useState(idxs[0]);
  const [tip, setTip] = useState<{ k: string; x: number; y: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
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
        <div ref={wrapRef} className="relative" onMouseLeave={() => setTip(null)}>
          <svg width="220" height="220" viewBox="0 0 220 220">
            <g transform="translate(110 110) rotate(-90)">
              {known.map((p) => {
                const len = (p.v / total) * C;
                const on = tip?.k === p.k;
                const el = (
                  <circle
                    key={p.k}
                    r={R}
                    fill="none"
                    stroke={SH_COLORS[p.k]}
                    strokeWidth="28"
                    strokeDasharray={`${len} ${C - len}`}
                    strokeDashoffset={-acc}
                    style={{ opacity: tip && !on ? 0.4 : 1, transition: "opacity 150ms ease", cursor: "pointer" }}
                    onMouseMove={(e) => {
                      const r = wrapRef.current?.getBoundingClientRect();
                      if (r) setTip({ k: p.k, x: e.clientX - r.left, y: e.clientY - r.top });
                    }}
                  />
                );
                acc += len;
                return el;
              })}
            </g>
          </svg>
          {tip && (
            <div
              className="pointer-events-none absolute z-10 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs shadow-lg"
              style={{ left: tip.x + 14, top: tip.y - 44, background: "#ffffff", color: "#1f2937", boxShadow: "0 6px 20px rgba(0,0,0,0.35)" }}
            >
              <div className="flex items-center gap-1.5 text-[11px]" style={{ color: "#6b7280" }}>
                <span className="h-2 w-2 rounded-full" style={{ background: SH_COLORS[tip.k] }} />
                {SH_LABELS[tip.k]}
              </div>
              <div className="text-sm font-semibold">{num(data[tip.k as (typeof keys)[number]][sel])}%</div>
            </div>
          )}
        </div>
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

export interface Profile {
  paragraphs: string[];
  headquarters: string | null;
  incorporation_year: number | null;
  leader: { name: string; title: string } | null;
  website: string | null;
  annual_report: { year: number | null; url: string } | null;
}

/** Company description (all paragraphs, collapsed behind "Read more" like the exchange's page) followed by the fact
 *  blocks: Headquarters, Year of Incorporation, MD / CEO, Website and the latest Annual Report link. A fact no source
 *  provides reads "—". */
export function About({ profile, fallbackText }: { profile: Profile | null; fallbackText?: string | null }) {
  const [open, setOpen] = useState(false);
  const paragraphs = profile?.paragraphs?.length ? profile.paragraphs : fallbackText ? [fallbackText] : [];
  const href = (w: string) => (/^https?:\/\//i.test(w) ? w : `https://${w}`);
  const ar = profile?.annual_report ?? null;
  const facts: { label: string; node: React.ReactNode }[] = [
    { label: "Headquarters", node: profile?.headquarters ?? null },
    { label: "Year of Incorporation", node: profile?.incorporation_year ?? null },
    { label: "MD / CEO", node: profile?.leader?.name ?? null },
    {
      label: "Website",
      node: profile?.website ? (
        <a href={href(profile.website)} target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:underline" style={{ color: "var(--accent-text, #b7b4e7)" }}>
          {profile.website}
        </a>
      ) : null,
    },
    {
      label: "Annual Report",
      node: ar ? (
        <a href={ar.url} target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:underline" style={{ color: "var(--accent-text, #b7b4e7)" }}>
          {ar.year ? `FY${ar.year} Annual Report` : "Latest Annual Report"} ↗
        </a>
      ) : null,
    },
  ];
  return (
    <div>
      <div className="max-w-5xl space-y-3 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        {(open ? paragraphs : paragraphs.slice(0, 1)).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        {paragraphs.length > 1 && (
          <button onClick={() => setOpen((v) => !v)} className="text-xs font-medium" style={{ color: "var(--accent-text, #b7b4e7)" }}>
            {open ? "Show less" : "Read more"}
          </button>
        )}
        {paragraphs.length === 0 && <p style={{ color: "var(--text-tertiary)" }}>Company description is unavailable for this company.</p>}
      </div>
      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {facts.map((f) => (
          <div key={f.label} className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{f.label}</div>
            <div className="mt-1 break-words text-sm font-semibold">{f.node ?? "—"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PeerTable({ peers, current, onSelect }: { peers: Peer[]; current: string; onSelect?: (p: Peer) => void }) {
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
              <tr
                key={p.symbol}
                className={`border-t ${onSelect && !isSelf ? "cursor-pointer hover:bg-[var(--overlay-weak)]" : ""}`}
                style={{ borderColor: "var(--border-subtle)", background: isSelf ? "var(--accent-surface)" : undefined }}
                // a peer opens that company's own page (the current company's row is just highlighted)
                onClick={onSelect && !isSelf ? () => onSelect(p) : undefined}
                onKeyDown={onSelect && !isSelf ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(p); } } : undefined}
                tabIndex={onSelect && !isSelf ? 0 : undefined}
                role={onSelect && !isSelf ? "link" : undefined}
                aria-label={onSelect && !isSelf ? `Open ${p.name}` : undefined}
              >
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
