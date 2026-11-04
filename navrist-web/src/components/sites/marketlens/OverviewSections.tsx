"use client";

import { useId, useRef, useState } from "react";

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
  peers_source?: "screener" | "sector";
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
  const [openKey, setOpenKey] = useState<ShKey | null>(null);
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
                    onClick={() => setOpenKey((cur) => (cur === p.k ? null : p.k))}
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
          <button key={p.k} onClick={() => setOpenKey((cur) => (cur === p.k ? null : p.k))} className="text-left">
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{SH_LABELS[p.k]}</div>
            <div className="font-semibold">{p.v == null ? "—" : `${num(p.v)}%`}</div>
          </button>
        ))}
      </div>
      {openKey && <ShareholdingDetail data={data} k={openKey} sel={sel} onClose={() => setOpenKey(null)} />}
    </div>
  );
}

type ShKey = "promoter" | "fii" | "dii" | "public";
const SH_KEYS: ShKey[] = ["promoter", "fii", "dii", "public"];

/** Opens when a slice is tapped: that holder's share now, the change since the last quarter and a year earlier,
 *  and its path over every reported quarter. "All groups" overlays the four lines. A quarter with no figure stays
 *  blank (gap in the line, "—" in the text), never zero. */
function ShareholdingDetail({ data, k, sel, onClose }: { data: Shareholding; k: ShKey; sel: number; onClose: () => void }) {
  const [all, setAll] = useState(false);
  const [hov, setHov] = useState<number | null>(null);
  const clipId = useId().replace(/:/g, "");
  const vals = data[k];
  const now = vals[sel];
  const delta = (back: number) => {
    const prev = vals[sel - back];
    return now != null && prev != null ? now - prev : null;
  };
  const q1 = delta(1);
  const y1 = delta(4);
  const tone = (d: number | null) => (d == null || Math.abs(d) < 0.005 ? "var(--text-primary)" : d > 0 ? "#10b981" : "#ef4444");
  const fmt = (d: number | null) => (d == null ? "—" : `${d > 0 ? "+" : ""}${d.toFixed(2)} pts`);
  const sentence = (() => {
    if (q1 == null) return null;
    if (Math.abs(q1) < 0.005) return `${SH_LABELS[k]} holding is unchanged from ${data.quarters[sel - 1]}.`;
    return `${SH_LABELS[k]} holding ${q1 > 0 ? "rose" : "fell"} ${Math.abs(q1).toFixed(2)} points from ${data.quarters[sel - 1]} to ${data.quarters[sel]}.`;
  })();

  const shown = all ? SH_KEYS : [k];
  const nums = shown.flatMap((s) => data[s].filter((v): v is number => v != null));
  const W = 560, H = 160, PX = 34, PY = 14;
  const n = data.quarters.length;
  const lo = nums.length ? Math.min(...nums) : 0;
  const hi = nums.length ? Math.max(...nums) : 1;
  const pad = (hi - lo) * 0.15 || 1;
  const yMin = Math.max(0, lo - pad), yMax = hi + pad;
  const X = (i: number) => PX + (n > 1 ? (i / (n - 1)) * (W - PX * 2) : 0);
  const Y = (v: number) => PY + (1 - (v - yMin) / (yMax - yMin)) * (H - PY * 2);
  const path = (s: ShKey) => {
    let d = "";
    let pen = false;
    data[s].forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)} `;
      pen = true;
    });
    return d;
  };

  /** Value of a holder's line at a fractional quarter position; blank when either neighbouring quarter has no figure. */
  const at = (s: ShKey, f: number) => {
    const i0 = Math.floor(f), i1 = Math.min(n - 1, i0 + 1);
    const a0 = data[s][i0], a1 = data[s][i1];
    if (a0 == null || a1 == null) return null;
    return a0 + (a1 - a0) * (f - i0);
  };
  const XF = (f: number) => PX + (n > 1 ? (f / (n - 1)) * (W - PX * 2) : 0);
  const hovLabel = (f: number) => {
    const r = Math.round(f);
    if (Math.abs(f - r) < 0.08) return data.quarters[r];
    return `${data.quarters[Math.floor(f)]} to ${data.quarters[Math.ceil(f)]}`;
  };

  return (
    <div className="mt-4 rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--overlay-weak)" }}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: SH_COLORS[k] }} />
          {SH_LABELS[k]}
        </div>
        <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-secondary)" }}>
          <label className="flex cursor-pointer items-center gap-2">
            All groups
            <button
              role="switch"
              aria-checked={all}
              onClick={() => setAll((v) => !v)}
              className="relative h-4 w-7 rounded-full transition-colors"
              style={{ background: all ? "#10b981" : "var(--border-subtle)" }}
            >
              <span className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all" style={{ left: all ? 14 : 2 }} />
            </button>
          </label>
          <button onClick={onClose} aria-label="Close" className="px-1 text-base leading-none" style={{ color: "var(--text-tertiary)" }}>×</button>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{data.quarters[sel]}</div>
          <div className="font-semibold">{now == null ? "—" : `${num(now)}%`}</div>
        </div>
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>vs last quarter</div>
          <div className="font-semibold" style={{ color: tone(q1) }}>{fmt(q1)}</div>
        </div>
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>vs a year ago</div>
          <div className="font-semibold" style={{ color: tone(y1) }}>{fmt(y1)}</div>
        </div>
      </div>

      <style>{`@keyframes shReveal{from{transform:scaleX(0)}to{transform:scaleX(1)}}.sh-reveal{transform-box:fill-box;transform-origin:0 50%;animation:shReveal 900ms cubic-bezier(.22,.61,.36,1) both}@media (prefers-reduced-motion:reduce){.sh-reveal{animation:none}}`}</style>
      {nums.length >= 2 ? (
        <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label="Holding over time"
          onMouseMove={(e) => {
            const b = e.currentTarget.getBoundingClientRect();
            const x = ((e.clientX - b.left) / b.width) * W;
            setHov(Math.max(0, Math.min(n - 1, ((x - PX) / (W - PX * 2)) * (n - 1))));
          }}
          onMouseLeave={() => setHov(null)}
        >
          {[yMin, (yMin + yMax) / 2, yMax].map((g, i) => (
            <g key={i}>
              <line x1={PX} x2={W - PX} y1={Y(g)} y2={Y(g)} stroke="var(--border-subtle)" strokeWidth="1" />
              <text x={PX - 6} y={Y(g) + 3} textAnchor="end" fontSize="9" fill="var(--text-tertiary)">{g.toFixed(0)}%</text>
            </g>
          ))}
          {data.quarters.map((q, i) =>
            i % Math.ceil(n / 6) === 0 || i === n - 1 ? (
              <text key={q + i} x={X(i)} y={H - 1} textAnchor="middle" fontSize="9" fill="var(--text-tertiary)">{q}</text>
            ) : null,
          )}
          <defs>
            <clipPath id={clipId}>
              <rect key={`${k}-${all}-${sel}`} className="sh-reveal" x="0" y="0" width={W} height={H} />
            </clipPath>
          </defs>
          <g clipPath={`url(#${clipId})`}>
            {shown.map((s) => (
              <path key={s} d={path(s)} fill="none" stroke={SH_COLORS[s]} strokeWidth={s === k ? 2.2 : 1.5} strokeLinejoin="round" />
            ))}
            {data[k].map((v, i) => (v == null ? null : <circle key={i} cx={X(i)} cy={Y(v)} r={i === sel ? 2.5 : 0} fill={SH_COLORS[k]} />))}
          </g>
          {hov != null && (
            <g pointerEvents="none">
              <line x1={XF(hov)} x2={XF(hov)} y1={PY} y2={H - PY} stroke="var(--text-tertiary)" strokeWidth="1" strokeDasharray="2 3" opacity="0.6" />
              {shown.map((s) => {
                const v = at(s, hov);
                return v == null ? null : <circle key={s} cx={XF(hov)} cy={Y(v)} r="2.5" fill={SH_COLORS[s]} />;
              })}
            </g>
          )}
        </svg>
        {hov != null && (
          <div
            className="pointer-events-none absolute top-0 z-10 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs"
            style={{
              left: `${(XF(hov) / W) * 100}%`,
              transition: "left 90ms ease-out",
              transform: hov > (n - 1) / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
              background: "#ffffff",
              color: "#1f2937",
              boxShadow: "0 6px 20px rgba(0,0,0,0.35)",
            }}
          >
            <div className="mb-0.5 text-[11px]" style={{ color: "#6b7280" }}>{hovLabel(hov)}</div>
            {shown.map((s) => (
              <div key={s} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: SH_COLORS[s] }} />
                <span style={{ color: "#6b7280" }}>{all ? SH_LABELS[s] : "Holding"}</span>
                <span className="ml-2 font-semibold">{at(s, hov) == null ? "—" : `${num(at(s, hov))}%`}</span>
              </div>
            ))}
          </div>
        )}
        </div>
      ) : (
        <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Not enough quarters reported to draw a trend.</div>
      )}
      {all && (
        <div className="mt-2 flex flex-wrap gap-3 text-[11px]" style={{ color: "var(--text-secondary)" }}>
          {SH_KEYS.map((s) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: SH_COLORS[s] }} />
              {SH_LABELS[s]}
            </span>
          ))}
        </div>
      )}
      {sentence && <p className="mt-3 text-xs" style={{ color: "var(--text-secondary)" }}>{sentence}</p>}
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
                {/* ROCE: 15% or more green, under 8% red (a business earning less than its cost of money) */}
                <td className="px-5 py-3.5 text-right" style={{ color: m.returnOnCapitalEmployed?.value == null ? undefined : m.returnOnCapitalEmployed.value >= 15 ? "var(--gain)" : m.returnOnCapitalEmployed.value < 8 ? "var(--loss)" : undefined }}>{num(m.returnOnCapitalEmployed?.value ?? null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export { Unavailable };
