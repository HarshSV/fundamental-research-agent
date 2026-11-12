"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchJson } from "@/lib/api";
import { SlidingTabs } from "./controls";

const GAIN = "var(--gain)";
const LOSS = "var(--loss)";
const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ym = (s: string | null | undefined) => (s ? `${MONTHS[Number(s.slice(5, 7)) - 1]} ${s.slice(0, 4)}` : "—");

interface Year { year: number; return: number | null; market: number | null; partial: boolean; beat_market: boolean | null }
interface Roll { windows: number; worst: number | null; median: number | null; best: number | null; positive_share: number | null }
interface Stats {
  available: boolean; reason?: string; from?: string; to?: string; years?: number; members_start?: number; members_now?: number;
  cagr?: number | null; total_return?: number | null; yearly?: Year[];
  best_year?: Year | null; worst_year?: Year | null;
  positive_years?: { count: number; of: number } | null; beat_market_years?: { count: number; of: number } | null;
  max_drawdown?: { depth: number | null; peak: string; trough: string; recovered: string | null; months_down: number; months_to_recover: number | null };
  drawdown_now?: number | null; rolling?: Record<string, Roll>;
  seasonal?: { month: number; average: number | null; positive_share: number | null; months: number }[];
  curve?: { m: string; v: number }[];
}
interface Sector extends Stats { sector: string; stocks_with_history: number }
interface Res { ready: boolean; note?: string; window?: string; market?: Stats & { name: string; stocks: number }; sectors?: Sector[]; limits?: string[]; as_of?: string; done?: number; total?: number; running?: boolean }

function Curve({ pts }: { pts: { m: string; v: number }[] }) {
  if (pts.length < 2) return null;
  const W = 640, H = 120;
  const lv = pts.map((p) => Math.log(p.v));
  const lo = Math.min(...lv), hi = Math.max(...lv);
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const y = (v: number) => H - 6 - ((v - lo) / (hi - lo || 1)) * (H - 12);
  const d = lv.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full" role="img" aria-label="Growth of 100 since the start, on a log scale">
      <path d={d} fill="none" stroke="#4d8dff" strokeWidth="2" />
      <text x="4" y="12" fontSize="10" fill="var(--text-tertiary)">{pts[0].m}</text>
      <text x={W - 4} y="12" fontSize="10" textAnchor="end" fill="var(--text-tertiary)">{pts[pts.length - 1].m} · 100 → {pts[pts.length - 1].v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} (log scale)</text>
    </svg>
  );
}

function YearBars({ years }: { years: Year[] }) {
  const vals = years.flatMap((y) => [y.return, y.market]).filter((v): v is number => v != null);
  const top = Math.max(...vals, 10), bot = Math.min(...vals, -10);
  const H = 150, span = top - bot, zero = (top / span) * H;
  const yy = (v: number) => ((top - v) / span) * H;
  return (
    <div className="overflow-x-auto">
      <div className="relative flex items-start gap-1" style={{ height: H + 22, minWidth: years.length * 30 }}>
        <div className="pointer-events-none absolute inset-x-0 border-t" style={{ top: zero, borderColor: "var(--grid)" }} />
        {years.map((y) => (
          <div key={y.year} className="relative flex-1" style={{ height: H + 22 }} title={`${y.year}${y.partial ? " (part year)" : ""}: sector ${pct(y.return)} · all stocks ${pct(y.market)}`}>
            {y.return != null && (
              <div className="absolute left-[10%] w-[38%] rounded-sm" style={{ background: y.return >= 0 ? "#10d9a8" : "#ff5f6d", opacity: y.partial ? 0.5 : 1, top: y.return >= 0 ? yy(y.return) : zero, height: Math.max(Math.abs(yy(y.return) - zero), 1) }} />
            )}
            {y.market != null && (
              <div className="absolute right-[10%] w-[38%] rounded-sm" style={{ background: "#9ca3af", opacity: y.partial ? 0.35 : 0.6, top: y.market >= 0 ? yy(y.market) : zero, height: Math.max(Math.abs(yy(y.market) - zero), 1) }} />
            )}
            <div className="absolute inset-x-0 text-center text-[9px]" style={{ top: H + 4, color: "var(--text-tertiary)" }}>{String(y.year).slice(2)}</div>
          </div>
        ))}
      </div>
      <p className="mt-1 text-[11px]" style={{ color: "var(--text-tertiary)" }}>Each year: sector (green or red) beside all stocks (grey). Faded bars are part years. Hover a year for the figures.</p>
    </div>
  );
}

function Detail({ s }: { s: Sector }) {
  const roll = s.rolling ?? {};
  return (
    <div className="grid gap-6 p-4 lg:grid-cols-2" style={{ background: "var(--overlay-weak)" }}>
      <div className="lg:col-span-2">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Growth of 100 since {ym(s.from)}</div>
        <Curve pts={s.curve ?? []} />
      </div>
      <div className="lg:col-span-2">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Return by calendar year</div>
        <YearBars years={s.yearly ?? []} />
      </div>
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>If you had held it for…</div>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: "var(--text-tertiary)" }} className="text-xs">
              <th className="py-1 text-left font-normal">Holding</th><th className="text-right font-normal">Worst</th><th className="text-right font-normal">Median</th><th className="text-right font-normal">Best</th><th className="text-right font-normal">Positive</th>
            </tr>
          </thead>
          <tbody>
            {["1", "3", "5", "10"].map((k) => roll[k] ? (
              <tr key={k} className="border-t" style={{ borderColor: "var(--border-subtle)" }}>
                <td className="py-1.5">{k} year{k === "1" ? "" : "s"}</td>
                <td className="text-right" style={{ color: tone(roll[k].worst) }}>{pct(roll[k].worst)}</td>
                <td className="text-right" style={{ color: tone(roll[k].median) }}>{pct(roll[k].median)}</td>
                <td className="text-right" style={{ color: tone(roll[k].best) }}>{pct(roll[k].best)}</td>
                <td className="text-right">{roll[k].positive_share == null ? "—" : `${roll[k].positive_share}%`}</td>
              </tr>
            ) : null)}
          </tbody>
        </table>
        <p className="mt-1 text-[11px]" style={{ color: "var(--text-tertiary)" }}>Yearly rate over every possible start month. Many windows overlap, so they are not independent.</p>
      </div>
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Average return by month</div>
        <div className="grid grid-cols-6 gap-1.5 sm:grid-cols-12 lg:grid-cols-6">
          {(s.seasonal ?? []).map((m) => (
            <div key={m.month} className="rounded-md p-1.5 text-center" style={{ background: m.average == null ? "var(--overlay)" : m.average >= 0 ? "rgba(16,217,168,.14)" : "rgba(255,95,109,.14)" }}>
              <div className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{MONTHS[m.month - 1]}</div>
              <div className="text-xs font-semibold" style={{ color: tone(m.average) }}>{pct(m.average)}</div>
              <div className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{m.positive_share == null ? "—" : `${m.positive_share}% up`}</div>
            </div>
          ))}
        </div>
        <p className="mt-1 text-[11px]" style={{ color: "var(--text-tertiary)" }}>Average of that calendar month across the years, and how often it closed up. A pattern in past months is not a promise.</p>
      </div>
      <div className="lg:col-span-2 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
        {s.max_drawdown && (
          <>
            <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Deepest fall</span><span style={{ color: LOSS }}>{pct(s.max_drawdown.depth)} ({ym(s.max_drawdown.peak)} → {ym(s.max_drawdown.trough)})</span></div>
            <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Back at the old high</span><span>{s.max_drawdown.recovered ? `${ym(s.max_drawdown.recovered)} (${s.max_drawdown.months_to_recover} months after the low)` : "Not yet"}</span></div>
          </>
        )}
        <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Now vs its own all-time peak</span><span style={{ color: tone(s.drawdown_now) }}>{pct(s.drawdown_now)}</span></div>
        <div className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Stocks in it (start → now)</span><span>{s.members_start} → {s.members_now}</span></div>
      </div>
    </div>
  );
}

export function SectorHistory() {
  const [win, setWin] = useState<"full" | "5y">("full");
  const [res, setRes] = useState<Res | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setRes(null);
    setError("");
    fetchJson<Res>(`/api/v1/market/sector-history?window=${win}`).then((d) => alive && setRes(d)).catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [win]);

  if (error) return <div className="py-16 text-center text-sm" style={{ color: "#f5a9a9" }}>Could not load this view: {error}</div>;
  if (!res) return <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading…</div>;
  if (!res.ready) return <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>{res.note ?? "The sector history has not been built yet."}</div>;
  const m = res.market;
  const rows = (res.sectors ?? []).filter((s) => s.available);
  const skipped = (res.sectors ?? []).filter((s) => !s.available);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SlidingTabs ariaLabel="History window" size="sm" value={win} onChange={setWin} options={[{ id: "full", label: "Full history" }, { id: "5y", label: "Last 5 years" }]} />
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Monthly, to {ym(res.as_of ? `${res.as_of}` : null)} · from each sector&apos;s first reliable month, about 1996 to 2002 onwards</span>
      </div>

      {m?.available && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { l: `All ${m.stocks} stocks, yearly growth`, v: pct(m.cagr), c: tone(m.cagr), s: `${ym(m.from)} to ${ym(m.to)}` },
            { l: "Years up", v: m.positive_years ? `${m.positive_years.count} of ${m.positive_years.of}` : "—", s: "full calendar years" },
            { l: "Deepest fall", v: pct(m.max_drawdown?.depth), c: LOSS, s: `${ym(m.max_drawdown?.peak)} → ${ym(m.max_drawdown?.trough)}` },
            { l: "Best / worst year", v: `${m.best_year ? m.best_year.year + " " + pct(m.best_year.return, 0) : "—"}`, s: m.worst_year ? `worst ${m.worst_year.year} ${pct(m.worst_year.return, 0)}` : "" },
          ].map((c) => (
            <div key={c.l} className="rounded-xl border p-3" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
              <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{c.l}</div>
              <div className="mt-1 text-lg font-semibold" style={{ color: c.c }}>{c.v}</div>
              <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{c.s}</div>
            </div>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <table className="w-full min-w-[860px] text-sm">
          <thead>
            <tr className="text-left text-xs" style={{ color: "var(--text-tertiary)" }}>
              <th className="px-3 py-2 font-normal">Sector</th><th className="px-2 font-normal">From</th><th className="px-2 text-right font-normal">Stocks</th>
              <th className="px-2 text-right font-normal">Yearly growth</th><th className="px-2 text-right font-normal">Years up</th><th className="px-2 text-right font-normal">Beat all stocks</th>
              <th className="px-2 text-right font-normal">Best year</th><th className="px-2 text-right font-normal">Worst year</th><th className="px-2 text-right font-normal">Deepest fall</th><th className="px-2 text-right font-normal">Now vs peak</th><th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <FragmentRow key={s.sector} s={s} open={open === s.sector} onToggle={() => setOpen(open === s.sector ? null : s.sector)} />
            ))}
          </tbody>
        </table>
      </div>
      {skipped.length > 0 && (
        <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>Not shown, too few stocks or too short a history: {skipped.map((s) => s.sector).join(", ")}.</p>
      )}
      <ul className="mt-4 list-disc space-y-1 pl-5 text-xs" style={{ color: "var(--text-tertiary)" }}>
        {(res.limits ?? []).map((l) => <li key={l}>{l}</li>)}
        <li>These figures describe the past. They are not a forecast.</li>
      </ul>
    </div>
  );
}

function FragmentRow({ s, open, onToggle }: { s: Sector; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer border-t hover:bg-[var(--overlay-weak)]" style={{ borderColor: "var(--border-subtle)" }}>
        <td className="px-3 py-2.5 font-medium">{s.sector}</td>
        <td className="px-2" style={{ color: "var(--text-secondary)" }}>{ym(s.from)}</td>
        <td className="px-2 text-right">{s.stocks_with_history}</td>
        <td className="px-2 text-right font-semibold" style={{ color: tone(s.cagr) }}>{pct(s.cagr)}</td>
        <td className="px-2 text-right">{s.positive_years ? `${s.positive_years.count}/${s.positive_years.of}` : "—"}</td>
        <td className="px-2 text-right">{s.beat_market_years ? `${s.beat_market_years.count}/${s.beat_market_years.of}` : "—"}</td>
        <td className="px-2 text-right" style={{ color: GAIN }}>{s.best_year ? `${s.best_year.year} ${pct(s.best_year.return, 0)}` : "—"}</td>
        <td className="px-2 text-right" style={{ color: LOSS }}>{s.worst_year ? `${s.worst_year.year} ${pct(s.worst_year.return, 0)}` : "—"}</td>
        <td className="px-2 text-right" style={{ color: LOSS }}>{pct(s.max_drawdown?.depth, 0)}</td>
        <td className="px-2 text-right" style={{ color: tone(s.drawdown_now) }}>{pct(s.drawdown_now, 0)}</td>
        <td className="pr-2"><ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} style={{ color: "var(--text-tertiary)" }} /></td>
      </tr>
      {open && (
        <tr><td colSpan={11} className="p-0"><Detail s={s} /></td></tr>
      )}
    </>
  );
}
