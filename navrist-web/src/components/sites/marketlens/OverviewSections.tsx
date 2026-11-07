"use client";

import { useEffect, useId, useRef, useState } from "react";
import { fetchJson } from "@/lib/api";
import { SlidingTabs, Switch } from "./controls";

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

/** One ratio on the two bases: last four quarters (ttm) and the last full financial year (annual); null = not computable. */
export interface Basis2 {
  ttm: number | null;
  annual: number | null;
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
  basis?: "consolidated" | "standalone";
  is_financial?: boolean;
  ratios?: {
    annual_label: string | null;
    roe: Basis2;
    net_margin: Basis2;
    revenue_growth: Basis2;
    interest_coverage: Basis2 | null;
    book_value: number | null;
    dividend_yield: number | null;
    promoter: number | null;
  } | null;
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

// One vivid colour per measure, the same in Results and in that measure's own tab (PAT is the net profit, so it shares its blue).
const BAR_COLORS = { income: "#10d9a8", pbt: "#ffae1a", net: "#4d8dff", fcf: "#b65cff", eps: "#ff5fa8" };
const glow = (c: string) => `0 0 12px ${c}80, 0 0 3px ${c}`;

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

export type FinTab = "results" | "pat" | "eps" | "fcf";

interface FcfData { available: boolean; basis?: string; rows: { period: string; fcf_cr: number | null; cfo_cr: number | null }[] }

// one bar group: a reported quarter, or (Free Cash Flow tab) a financial year
interface Col { id: string; label: string; q: Quarter | null; fcf: number | null; cfo: number | null }

/** Last four reported quarters, newest first (as on the exchange's page). Amounts in ₹ Lakhs; hover a quarter for
 *  its exact figures. A quarter whose value is unavailable draws no bar and reads "—" in the tooltip. */
export function QuarterlyResults({ quarters, tab, onTab, standalone = false, symbol }: { quarters: Quarter[]; tab: FinTab; onTab: (t: FinTab) => void; standalone?: boolean; symbol?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  // the tapped block: its figures open in a panel under the chart (a tab or symbol change closes it)
  const [pin, setPin] = useState<{ key: string; i: number } | null>(null);
  const pinKey = `${symbol ?? ""}|${tab}`;
  const pinned = pin && pin.key === pinKey ? pin.i : null;
  // Free cash flow is read only when its tab is first opened; it is yearly, so it has its own read.
  const [fcf, setFcf] = useState<{ sym: string; data: FcfData | null; failed: boolean } | null>(null);
  useEffect(() => {
    if ((tab !== "fcf" && tab !== "results") || !symbol || fcf?.sym === symbol) return;
    let alive = true;
    fetchJson<FcfData>(`/api/v1/stock-fcf/${symbol}`, { retries: 1 })
      .then((d) => alive && setFcf({ sym: symbol, data: d, failed: false }))
      .catch(() => alive && setFcf({ sym: symbol, data: null, failed: true }));
    return () => { alive = false; };
  }, [tab, symbol, fcf?.sym]);
  const fcfNow = fcf && fcf.sym === symbol ? fcf : null;
  // "Mar 2026" -> "2026": the financial year that ends in that March
  const fcfByYear = new Map<string, number | null>((fcfNow?.data?.rows ?? []).filter((r) => r.period.startsWith("Mar ")).map((r) => [r.period.slice(4), r.fcf_cr]));
  const last: Col[] = tab === "fcf"
    ? (fcfNow?.data?.rows ?? []).slice(-4).reverse().map((r) => ({ id: r.period, label: r.period.replace(" ", "\n"), q: null, fcf: r.fcf_cr, cfo: r.cfo_cr }))
    : quarters.slice(-4).reverse().map((q) => ({ id: q.period, label: dayLabel(q.period).replace(/ (\d{4})$/, "\n$1"), q, fcf: null, cfo: null }));
  // ₹ Crore -> ₹ Lakhs
  const L = (v: number | null) => (v == null ? null : v * 100);
  const q$ = (f: (q: Quarter) => number | null) => (c: Col) => (c.q ? f(c.q) : null);
  const series: { key: string; color: string; get: (c: Col) => number | null; mult?: number }[] =
    tab === "results"
      ? [
          { key: "Total Income", color: BAR_COLORS.income, get: q$((q) => L(q.total_income_cr)) },
          { key: "Profit Before Tax", color: BAR_COLORS.pbt, get: q$((q) => L(q.pbt_cr)) },
          { key: "Net Profit/Loss", color: BAR_COLORS.net, get: q$((q) => L(q.net_profit_cr)) },
          // free cash flow exists once a year: it sits on the quarter that closes the financial year (March), and the other quarters show "—"
          { key: "Free Cash Flow (yearly)", color: BAR_COLORS.fcf, get: q$((q) => (q.period.slice(5, 7) === "03" ? L(fcfByYear.get(q.period.slice(0, 4)) ?? null) : null)) },
        ]
      : tab === "pat"
        ? [{ key: "PAT", color: BAR_COLORS.net, get: q$((q) => L(q.net_profit_cr)) }]
        : tab === "fcf"
          ? [{ key: "Free Cash Flow", color: BAR_COLORS.fcf, get: (c: Col) => c.fcf }]
          : [{ key: "EPS", color: BAR_COLORS.eps, get: q$((q) => q.eps) }];
  const vals = last.flatMap((c) => series.filter((s) => s.key !== "EPS (right scale)").map((s) => s.get(c))).filter((v): v is number => v != null);
  const ticks = niceTicks(Math.min(...vals, 0), Math.max(...vals, 0));
  const top = ticks[ticks.length - 1];
  const bottom = ticks[0];
  const span = top - bottom || 1;
  const H = 220;
  const y = (v: number) => ((top - v) / span) * H;
  // EPS (₹ per share) cannot share the lakh scale, so on Results it has its own scale on the right. Both scales put zero on the same
  // line, and the right-hand labels sit on the same gridlines (a "nice" step), so a bar can be read against either side.
  const epsVals = tab === "results" ? last.map((c) => c.q?.eps).filter((v): v is number => v != null) : [];
  let epsK = 0;
  if (epsVals.length) {
    const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    const needUp = top > 0 ? Math.max(...epsVals, 0) / (top / step) : 0;
    const needDown = bottom < 0 ? Math.max(-Math.min(...epsVals, 0), 0) / (-bottom / step) : 0;
    const need = Math.max(needUp, needDown, 1e-6);
    const mag = Math.pow(10, Math.floor(Math.log10(need)));
    const stepR = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= need) ?? need;
    epsK = stepR / step; // ₹ of EPS per one unit of the left scale
  }
  if (epsK) series.push({ key: "EPS (right scale)", color: BAR_COLORS.eps, get: (c: Col) => c.q?.eps ?? null, mult: 1 / epsK });
  const money = (v: number | null) =>
    v == null ? "—" : tab === "eps" ? `₹${num(v, 2)}` : tab === "fcf" ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr` : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  const BOT = tab === "results" ? 58 : 26; // room under the bars for the date (and, on Results, that quarter EPS)
  const barW = tab === "eps" || tab === "pat" || tab === "fcf" ? 36 : epsK ? 12 : 16;

  const tabsEl = (
    <div className="mb-4 max-w-full overflow-x-auto">
      <SlidingTabs ariaLabel="Financial view" options={[{ id: "results", label: "Results" }, { id: "eps", label: "Earnings Per Share" }, { id: "pat", label: "PAT" }, { id: "fcf", label: "Free Cash Flow" }]} value={tab} onChange={onTab} />
    </div>
  );
  if (tab === "fcf" && !fcfNow?.data?.available) {
    return (
      <div>
        {tabsEl}
        {fcfNow === null ? (
          <div className="h-40 animate-pulse rounded-lg" style={{ background: "var(--overlay-weak)" }} aria-label="Reading free cash flow" />
        ) : (
          <Unavailable what={fcfNow.failed ? "Free cash flow (it could not be read right now)" : "Free cash flow"} />
        )}
      </div>
    );
  }

  return (
    <div>
      {tabsEl}
      <div className="mb-3 flex flex-wrap gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color, boxShadow: glow(s.color) }} />
            {s.key === "EPS (right scale)" ? "EPS (₹ per share, right scale)" : s.key === "EPS" ? "Earnings Per Share" : s.key === "PAT" ? "PAT (Profit After Tax)" : s.key === "Free Cash Flow" ? "Free Cash Flow (₹ Crore, by financial year)" : s.key}
          </span>
        ))}
      </div>
      <div className="flex" onMouseLeave={() => setHover(null)}>
        <div className="relative w-10 shrink-0 text-right text-[11px]" style={{ height: H, color: "var(--text-tertiary)" }}>
          {ticks.map((t) => (
            <span key={t} className="absolute right-1.5 -translate-y-1/2" style={{ top: y(t) }}>{axisLabel(t)}</span>
          ))}
        </div>
        <div className="relative flex-1" style={{ height: H + BOT }}>
          <div className="absolute inset-x-0 top-0 flex" style={{ height: H + BOT }}>
            {last.map((q, qi) => (
              <div
                key={q.id}
                role="button"
                tabIndex={0}
                aria-pressed={pinned === qi}
                aria-label={`Show the figures for ${q.id === q.q?.period ? dayLabel(q.id) : q.id}`}
                className="relative mx-1 flex-1 cursor-pointer overflow-hidden rounded-xl border outline-none transition-colors first:ml-0 last:mr-0"
                style={{ background: pinned === qi ? "var(--overlay)" : hover === qi ? "var(--overlay-weak)" : "transparent", borderColor: pinned === qi ? "var(--accent-border, var(--border-default))" : "var(--border-subtle)" }}
                onMouseEnter={() => setHover(qi)}
                onMouseMove={() => setHover(qi)}
                onClick={() => setPin(pinned === qi ? null : { key: pinKey, i: qi })}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPin(pinned === qi ? null : { key: pinKey, i: qi }); } }}
              >
                <div className="pointer-events-none absolute inset-x-0 top-0" style={{ height: H }}>
                  {ticks.map((t) => (
                    <div key={t} className="absolute inset-x-0 border-t" style={{ top: y(t), borderColor: "var(--grid)" }} />
                  ))}
                </div>
                <div className="absolute inset-x-0 top-0 flex items-start justify-center gap-1" style={{ height: H }}>
                  {series.map((s) => {
                    const raw = s.get(q);
                    if (raw == null) return <div key={s.key} style={{ width: barW }} />;
                    const v = raw * (s.mult ?? 1);
                    const h = Math.max(Math.abs(y(v) - y(0)), 2);
                    return (
                      <div key={s.key} className="relative" style={{ width: barW, height: H }}>
                        <div className="absolute w-full rounded-sm" style={{ background: s.color, boxShadow: glow(s.color), height: h, top: v >= 0 ? y(0) - h : y(0) }} />
                      </div>
                    );
                  })}
                </div>
                <div className="absolute inset-x-0 whitespace-pre-line text-center text-[11px] leading-tight" style={{ top: H + 6, color: "var(--text-tertiary)" }}>{q.label}</div>
                {tab === "results" && q.q?.eps != null && (
                  <div className="absolute inset-x-0 text-center text-[11px] font-semibold" style={{ top: H + 36, color: BAR_COLORS.eps, textShadow: `0 0 8px ${BAR_COLORS.eps}66` }}>EPS ₹{num(q.q.eps, 2)}</div>
                )}
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
                    <div className="mb-1 font-medium" style={{ color: "var(--text-primary)" }}>{q.id === q.q?.period ? dayLabel(q.id) : q.id}</div>
                    {series.filter((s) => !(s.key === "Free Cash Flow (yearly)" && s.get(q) == null)).map((s) => (
                      <div key={s.key} style={{ color: s.color }}>{s.key === "EPS (right scale)" ? "EPS" : s.key} : {s.key === "EPS (right scale)" ? (s.get(q) == null ? "—" : `₹${num(s.get(q), 2)}`) : money(s.get(q))}</div>
                    ))}
                    {tab === "pat" && q.q?.net_profit_cr != null && q.q.total_income_cr ? (
                      <div style={{ color: "var(--text-secondary)" }}>PAT margin : {num((q.q.net_profit_cr / q.q.total_income_cr) * 100, 1)}%</div>
                    ) : null}
                    {tab === "fcf" && q.cfo != null ? <div style={{ color: "var(--text-secondary)" }}>Cash from operations : {money(q.cfo)}</div> : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        {epsK ? (
          <div className="relative w-10 shrink-0 text-left text-[11px]" style={{ height: H, color: BAR_COLORS.eps }} aria-hidden>
            {ticks.map((t) => (
              <span key={t} className="absolute left-1.5 -translate-y-1/2" style={{ top: y(t) }}>{t === 0 ? "0" : num(t * epsK, epsK >= 1 ? 0 : 1)}</span>
            ))}
          </div>
        ) : null}
      </div>
      {pinned !== null && last[pinned] && (
        <BlockDetail tab={tab} col={last[pinned]} quarters={quarters} fcfRows={fcfNow?.data?.rows ?? []} fcfByYear={fcfByYear} onClose={() => setPin(null)} />
      )}
      <p className="mt-6 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        {standalone ? "Standalone results (this company reports no consolidated accounts)" : "Consolidated results (parent plus subsidiaries)"}, {tab === "fcf" ? "latest four financial years, newest first. Free cash flow is cash from operations less the fixed assets purchased, as Screener.in defines it; it is reported once a year." : "latest four quarters, newest first. PAT is the profit after tax Screener.in reports as net profit."}{tab === "results" ? " Free cash flow is reported once a year, so its bar sits on the March quarter and the other quarters have none." : ""} Source: Screener.in.
      </p>
    </div>
  );
}

const GAINC = "var(--gain, #10b981)";
const LOSSC = "var(--loss, #ef4444)";
const pctOf = (cur: number | null | undefined, base: number | null | undefined) => (cur != null && base != null && base > 0 ? (cur / base - 1) * 100 : null);
const signed = (v: number, d = 1) => `${v >= 0 ? "+" : "-"}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;

interface DetailRow { label: string; value: string; color?: string }

/** What a tapped block shows: that quarter's (or year's) figures and how they moved against the previous quarter and the same quarter
 *  a year earlier. A comparison that cannot be made (no earlier figure, or a loss as the starting point) is left out, not shown as zero. */
function BlockDetail({ tab, col, quarters, fcfRows, fcfByYear, onClose }: { tab: FinTab; col: Col; quarters: Quarter[]; fcfRows: FcfData["rows"]; fcfByYear: Map<string, number | null>; onClose: () => void }) {
  const rows: DetailRow[] = [];
  let title = col.id;
  const inL = (cr: number | null | undefined) => (cr == null ? null : cr * 100);
  const lakh = (v: number | null) => (v == null ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`);
  const cr0 = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
  const move = (label: string, cur: number | null | undefined, prev: number | null | undefined, unit: "pct" | "eps") => {
    if (cur == null || prev == null) return;
    if (unit === "eps") {
      const d = cur - prev;
      const p = pctOf(cur, prev);
      rows.push({ label, value: `${d >= 0 ? "+" : "-"}₹${num(Math.abs(d), 2)}${p != null ? ` (${signed(p)}%)` : ""}`, color: d >= 0 ? GAINC : LOSSC });
    } else {
      const p = pctOf(cur, prev);
      if (p != null) rows.push({ label, value: `${signed(p)}%`, color: p >= 0 ? GAINC : LOSSC });
    }
  };

  if (col.q) {
    const q = col.q;
    title = `${dayLabel(q.period)} quarter`;
    const i = quarters.findIndex((x) => x.period === q.period);
    const prev = i > 0 ? quarters[i - 1] : null;
    const yoyQ = i >= 4 && quarters[i - 4].period.slice(5, 7) === q.period.slice(5, 7) && Number(quarters[i - 4].period.slice(0, 4)) === Number(q.period.slice(0, 4)) - 1 ? quarters[i - 4] : null;
    const margin = q.net_profit_cr != null && q.total_income_cr ? (q.net_profit_cr / q.total_income_cr) * 100 : null;
    if (tab === "results") {
      rows.push({ label: "Total income", value: lakh(inL(q.total_income_cr)), color: BAR_COLORS.income });
      rows.push({ label: "Profit before tax", value: lakh(inL(q.pbt_cr)), color: BAR_COLORS.pbt });
      rows.push({ label: "Net profit (PAT)", value: lakh(inL(q.net_profit_cr)), color: BAR_COLORS.net });
      if (margin != null) rows.push({ label: "PAT margin", value: `${num(margin, 1)}%` });
      if (q.eps != null) rows.push({ label: "EPS", value: `₹${num(q.eps, 2)}`, color: BAR_COLORS.eps });
      if (q.period.slice(5, 7) === "03") {
        const f = fcfByYear.get(q.period.slice(0, 4));
        if (f != null) rows.push({ label: "Free cash flow (financial year)", value: cr0(f), color: BAR_COLORS.fcf });
      }
      move("Income vs last quarter", q.total_income_cr, prev?.total_income_cr, "pct");
      move("Income vs a year earlier", q.total_income_cr, yoyQ?.total_income_cr, "pct");
      move("Net profit vs last quarter", q.net_profit_cr, prev?.net_profit_cr, "pct");
      move("Net profit vs a year earlier", q.net_profit_cr, yoyQ?.net_profit_cr, "pct");
    } else if (tab === "pat") {
      rows.push({ label: "PAT (profit after tax)", value: lakh(inL(q.net_profit_cr)), color: BAR_COLORS.net });
      rows.push({ label: "Profit before tax", value: lakh(inL(q.pbt_cr)), color: BAR_COLORS.pbt });
      if (q.pbt_cr != null && q.net_profit_cr != null) rows.push({ label: "Tax and other items (PBT − PAT)", value: lakh(inL(q.pbt_cr - q.net_profit_cr)) });
      if (margin != null) rows.push({ label: "PAT margin (PAT ÷ total income)", value: `${num(margin, 1)}%` });
      move("PAT vs last quarter", q.net_profit_cr, prev?.net_profit_cr, "pct");
      move("PAT vs a year earlier", q.net_profit_cr, yoyQ?.net_profit_cr, "pct");
    } else {
      rows.push({ label: "EPS (diluted)", value: q.eps == null ? "—" : `₹${num(q.eps, 2)}`, color: BAR_COLORS.eps });
      move("Change vs last quarter", q.eps, prev?.eps, "eps");
      move("Change vs a year earlier", q.eps, yoyQ?.eps, "eps");
      const last4 = i >= 3 ? quarters.slice(i - 3, i + 1).map((x) => x.eps) : [];
      if (last4.length === 4 && last4.every((x) => x != null)) rows.push({ label: "Last four quarters together", value: `₹${num((last4 as number[]).reduce((a, b) => a + b, 0), 2)}` });
    }
  } else {
    title = `Financial year ended ${col.id}`;
    const i = fcfRows.findIndex((r) => r.period === col.id);
    const prev = i > 0 ? fcfRows[i - 1] : null;
    rows.push({ label: "Free cash flow", value: col.fcf == null ? "—" : cr0(col.fcf), color: BAR_COLORS.fcf });
    if (col.cfo != null) rows.push({ label: "Cash from operations", value: cr0(col.cfo) });
    if (col.cfo != null && col.fcf != null) rows.push({ label: "Fixed assets purchased (operations − FCF)", value: cr0(col.cfo - col.fcf) });
    if (col.cfo != null && col.cfo > 0 && col.fcf != null) rows.push({ label: "Share of operating cash left as FCF", value: `${num((col.fcf / col.cfo) * 100, 0)}%` });
    if (prev?.fcf_cr != null && col.fcf != null) {
      const d = col.fcf - prev.fcf_cr;
      const p = pctOf(col.fcf, prev.fcf_cr);
      rows.push({ label: `Change vs ${prev.period}`, value: `${d >= 0 ? "+" : "-"}${cr0(Math.abs(d))}${p != null ? ` (${signed(p)}%)` : ""}`, color: d >= 0 ? GAINC : LOSSC });
    }
  }
  return (
    <div className="mt-4 rounded-xl border p-4 text-sm" style={{ borderColor: "var(--border-subtle)", background: "var(--overlay-weak)" }}>
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">{title}</span>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded px-2 text-lg leading-none hover:bg-[var(--overlay)]" style={{ color: "var(--text-tertiary)" }}>×</button>
      </div>
      <div className="grid gap-x-8 gap-y-1.5 sm:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-3">
            <span style={{ color: "var(--text-secondary)" }}>{r.label}</span>
            <span className="whitespace-nowrap font-medium" style={{ color: r.color }}>{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const SH_COLORS: Record<string, string> = { promoter: "#14b8a6", fii: "#ec4899", dii: "#3b82f6", public: "#f97316" };
const SH_LABELS: Record<string, string> = { promoter: "Promoter & Promoter Group", fii: "FII", dii: "DII", public: "Public" };

export function ShareholdingPattern({ data, symbol }: { data: Shareholding; symbol?: string }) {
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
      <div className="mb-4 max-w-full overflow-x-auto">
        <SlidingTabs ariaLabel="Quarter" options={idxs.map((i) => ({ id: String(i), label: <><span className="sm:hidden">{data.quarters[i].replace(/ \d{2}(\d{2})$/, " ’$1")}</span><span className="hidden sm:inline">{data.quarters[i]}</span></> }))} value={String(sel)} onChange={(id) => setSel(Number(id))} />
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
      {openKey && <ShareholdingDetail data={data} k={openKey} sel={sel} symbol={symbol} onClose={() => setOpenKey(null)} />}
    </div>
  );
}

type ShKey = "promoter" | "fii" | "dii" | "public";
const SH_KEYS: ShKey[] = ["promoter", "fii", "dii", "public"];

/** Opens when a slice is tapped: that holder's share now, the change since the last quarter and a year earlier,
 *  and its path over every reported quarter. "All groups" overlays the four lines. A quarter with no figure stays
 *  blank (gap in the line, "—" in the text), never zero. */
function ShareholdingDetail({ data, k, sel, symbol, onClose }: { data: Shareholding; k: ShKey; sel: number; symbol?: string; onClose: () => void }) {
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
          <Switch on={all} onChange={() => setAll((v) => !v)} label="All groups" />
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
      {k === "promoter" && symbol && <PledgeBlock symbol={symbol} />}
    </div>
  );
}

interface PledgeRow {
  quarter: string;
  pledge_pct: number | null;
  shares_pledged: number | null;
  promoter_holding_pct: number | null;
  promoter_shares: number | null;
  issued_shares: number | null;
}
interface PledgeRes {
  status: "ok" | "none" | "unavailable";
  rows: PledgeRow[];
}

const monthYear = (q: string) => {
  const d = new Date(q);
  return Number.isNaN(d.getTime()) ? q : `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()]} ${d.getFullYear()}`;
};
/** Share of the promoter's own holding that is pledged (NSE "percPromoterShares"). */
const ofPromoter = (r: PledgeRow) => r.pledge_pct;
const crShares = (v: number | null) => (v == null ? "—" : v >= 1e7 ? `${(v / 1e7).toFixed(2)} Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(2)} L` : v.toLocaleString("en-IN"));

/** Promoter pledge from NSE's pledge filings. NSE lists a quarter only when a pledge exists, so "none" means NSE lists
 *  no pledge for this company and "unavailable" means the filing could not be read; neither is shown as 0%. */
function PledgeBlock({ symbol }: { symbol: string }) {
  const [res, setRes] = useState<PledgeRes | "loading">("loading");
  const [hov, setHov] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetchJson<PledgeRes & { symbol: string }>(`/api/v1/stock-pledge/${symbol}`, { retries: 1 })
      .then((r) => live && setRes(r))
      .catch(() => live && setRes({ status: "unavailable", rows: [] }));
    return () => {
      live = false;
    };
  }, [symbol]);

  const box = { borderColor: "var(--border-subtle)" };
  const head = <div className="mb-2 text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>Promoter pledge</div>;
  if (res === "loading") return <div className="mt-4 border-t pt-3" style={box}>{head}<div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading…</div></div>;
  if (res.status === "unavailable")
    return <div className="mt-4 border-t pt-3" style={box}>{head}<div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Pledge filing could not be read right now.</div></div>;
  if (res.status === "none" || res.rows.length === 0)
    return <div className="mt-4 border-t pt-3" style={box}>{head}<div className="text-xs" style={{ color: "var(--text-secondary)" }}>NSE lists no promoter pledge for this company.</div></div>;

  const rows = res.rows.slice(-8);
  const last = rows[rows.length - 1];
  const prev = rows.length > 1 ? rows[rows.length - 2] : null;
  const lastP = ofPromoter(last), prevP = prev ? ofPromoter(prev) : null;
  const d = lastP != null && prevP != null ? lastP - prevP : null;
  const tone = lastP === 0 ? "#10b981" : lastP != null && lastP >= 25 ? "#ef4444" : d == null || Math.abs(d) < 0.005 ? "var(--text-primary)" : d > 0 ? "#ef4444" : "#10b981";
  const vals = rows.map(ofPromoter);
  const ofEquity = last.shares_pledged != null && last.issued_shares ? (last.shares_pledged / last.issued_shares) * 100 : null;
  const max = Math.max(1, ...vals.filter((v): v is number => v != null));
  const shown = hov != null ? rows[hov] : last;

  return (
    <div className="mt-4 border-t pt-3" style={box}>
      {head}
      {lastP === 0 && <div className="mb-2 text-xs" style={{ color: "var(--text-secondary)" }}>None of the promoter&apos;s shares are pledged.</div>}
      <div className="grid grid-cols-3 gap-3 text-sm md:grid-cols-4">
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Pledged ({monthYear(last.quarter)})</div>
          <div className="font-semibold" style={{ color: tone }}>{lastP == null ? "—" : `${num(lastP)}%`}</div>
          <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>of promoter shares</div>
        </div>
        {d != null && (
          <div>
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>vs previous filing</div>
            <div className="font-semibold" style={{ color: tone }}>{`${d > 0 ? "+" : ""}${d.toFixed(2)} pts`}</div>
          </div>
        )}
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Shares pledged</div>
          <div className="font-semibold">{crShares(last.shares_pledged)}</div>
        </div>
        <div>
          <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>Of total equity</div>
          <div className="font-semibold">{ofEquity == null ? "—" : `${num(ofEquity)}%`}</div>
        </div>
      </div>
      {rows.length > 1 && (<>
      <div className="mt-3 flex h-16 items-end gap-1.5" onMouseLeave={() => setHov(null)}>
        {rows.map((r, i) => (
          <div key={r.quarter + i} className="flex h-full flex-1 items-end" onMouseEnter={() => setHov(i)}>
            <div
              className="w-full rounded-sm transition-all duration-500"
              style={{ height: `${ofPromoter(r) == null ? 0 : Math.max(4, ((ofPromoter(r) as number) / max) * 100)}%`, background: "#ef4444", opacity: hov == null || hov === i ? 0.9 : 0.35 }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        <span>{monthYear(rows[0].quarter)}</span>
        <span style={{ color: "var(--text-secondary)" }}>{monthYear(shown.quarter)}: {ofPromoter(shown) == null ? "—" : `${num(ofPromoter(shown))}%`}</span>
        <span>{monthYear(last.quarter)}</span>
      </div>
      </>)}
      <p className="mt-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>Source: NSE pledge filing for the latest quarter. Red at 25% or more of the promoter holding pledged.</p>
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
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
      <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
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
