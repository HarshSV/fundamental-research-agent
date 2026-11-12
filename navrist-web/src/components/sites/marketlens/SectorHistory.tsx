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

interface EvRef { month: string; title: string; scope: string }
interface Move { month: string; sector_return: number | null; market_return: number | null; excess: number | null; kind: string; events: EvRef[] }
interface Reaction { month: string; title: string; scope: string; sector_month: number | null; market_month: number | null; sector_after_3m: number | null; market_after_3m: number | null; excess_month: number | null }
interface EventsRes {
  ready: boolean; available?: boolean; reason?: string; note?: string; from?: string; to?: string;
  beta?: number | null; correlation?: number | null; up_capture?: number | null; down_capture?: number | null;
  moves?: { outperformed: Move[]; underperformed: Move[] }; reactions?: Reaction[]; events_known?: number;
}
interface RecentRes {
  stocks: number; orders: { time: string; symbol: string; name: string | null; subject: string; link: string | null }[]; orders_count: number;
  deals: { date: string; kind: string; symbol: string; name: string | null; client: string | null; side: string | null; value_cr: number }[]; deals_count: number; deals_buy_cr: number; deals_sell_cr: number;
  upcoming: { date: string; symbol: string; name: string | null; purpose: string | null }[]; upcoming_count: number;
}
interface HeadRes { ok: boolean; items: { date: string | null; title: string; source: string | null; link: string | null }[] }

const Sub = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2 mt-1 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>{children}</div>
);

function MoveRow({ m, sector }: { m: Move; sector: string }) {
  const [heads, setHeads] = useState<HeadRes | "loading" | "failed" | null>(null);
  const load = () => {
    if (heads) return setHeads(null);
    setHeads("loading");
    fetchJson<HeadRes>(`/api/v1/market/sector-headlines?sector=${encodeURIComponent(sector)}&month=${m.month}`).then(setHeads).catch(() => setHeads("failed"));
  };
  return (
    <li className="border-t py-2 text-sm first:border-t-0" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="font-medium">{ym(`${m.month}-01`)}</span>
        <span className="text-xs">
          <span style={{ color: tone(m.sector_return) }}>sector {pct(m.sector_return)}</span>
          <span style={{ color: "var(--text-tertiary)" }}> · all stocks </span>
          <span style={{ color: tone(m.market_return) }}>{pct(m.market_return)}</span>
        </span>
      </div>
      <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
        {m.kind === "moved with the market" ? "Mostly moved with the market" : `${pct(m.excess)} against the market: specific to this sector`}
      </div>
      {m.events.length ? (
        <ul className="mt-1 space-y-0.5 text-xs">
          {m.events.map((e) => <li key={e.month + e.title}>Around then: <b>{e.title}</b> <span style={{ color: "var(--text-tertiary)" }}>({ym(`${e.month}-01`)})</span></li>)}
        </ul>
      ) : (
        <div className="mt-1 text-xs" style={{ color: "var(--text-tertiary)" }}>No event in our list around this month.</div>
      )}
      <button onClick={load} className="mt-1 text-xs underline" style={{ color: "var(--accent)" }}>{heads ? "Hide headlines" : "Headlines that month"}</button>
      {heads === "loading" && <div className="mt-1 text-xs" style={{ color: "var(--text-tertiary)" }}>Searching…</div>}
      {heads === "failed" && <div className="mt-1 text-xs" style={{ color: "var(--text-tertiary)" }}>Headlines could not be read right now.</div>}
      {heads && typeof heads === "object" && (
        heads.items.length ? (
          <ul className="mt-1 space-y-1 text-xs">
            {heads.items.map((h) => (
              <li key={h.title}>{h.link ? <a href={h.link} target="_blank" rel="noopener noreferrer" className="hover:underline">{h.title}</a> : h.title}<span style={{ color: "var(--text-tertiary)" }}> · {h.source ?? ""} {h.date ?? ""}</span></li>
            ))}
            <li style={{ color: "var(--text-tertiary)" }}>Google News search; some items may be only loosely related.</li>
          </ul>
        ) : <div className="mt-1 text-xs" style={{ color: "var(--text-tertiary)" }}>No headlines found for that month.</div>
      )}
    </li>
  );
}

function WhatMoved({ sector }: { sector: string }) {
  const [ev, setEv] = useState<EventsRes | null>(null);
  const [rc, setRc] = useState<RecentRes | null>(null);
  const [failed, setFailed] = useState(false);
  const [all, setAll] = useState(false);
  useEffect(() => {
    let alive = true;
    const q = encodeURIComponent(sector);
    fetchJson<EventsRes>(`/api/v1/market/sector-events?sector=${q}`).then((d) => alive && setEv(d)).catch(() => alive && setFailed(true));
    fetchJson<RecentRes>(`/api/v1/market/sector-recent?sector=${q}`).then((d) => alive && setRc(d)).catch(() => {});
    return () => { alive = false; };
  }, [sector]);
  if (failed) return <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>What moved this sector could not be read right now.</p>;
  if (!ev) return <div className="h-24 animate-pulse rounded-lg" style={{ background: "var(--overlay)" }} />;
  if (!ev.available) return <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>{ev.reason ?? ev.note}</p>;
  const reactions = [...(ev.reactions ?? [])].sort((a, b) => Math.abs(b.excess_month ?? 0) - Math.abs(a.excess_month ?? 0));
  const shown = (all ? reactions : reactions.slice(0, 8)).sort((a, b) => a.month.localeCompare(b.month));
  return (
    <div className="border-t pt-5" style={{ borderColor: "var(--border-subtle)" }}>
      <h3 className="mb-1 text-base font-semibold">What moved this sector</h3>
      <p className="mb-3 text-xs" style={{ color: "var(--text-tertiary)" }}>{ev.note}</p>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { l: "Beta to all stocks", v: ev.beta == null ? "—" : ev.beta.toFixed(2), s: ev.beta == null ? "" : ev.beta > 1.1 ? "swings more than the market" : ev.beta < 0.9 ? "swings less than the market" : "moves about with the market" },
          { l: "Gain captured in up months", v: ev.up_capture == null ? "—" : `${ev.up_capture}%`, s: "of the market's rise" },
          { l: "Loss taken in down months", v: ev.down_capture == null ? "—" : `${ev.down_capture}%`, s: "of the market's fall" },
          { l: "Moves with the market", v: ev.correlation == null ? "—" : ev.correlation.toFixed(2), s: "correlation, monthly" },
        ].map((c) => (
          <div key={c.l} className="rounded-lg border p-2.5" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{c.l}</div>
            <div className="text-base font-semibold">{c.v}</div>
            <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{c.s}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <Sub>Months it beat the market the most</Sub>
          <ul>{(ev.moves?.outperformed ?? []).map((m) => <MoveRow key={m.month} m={m} sector={sector} />)}</ul>
        </div>
        <div>
          <Sub>Months it lagged the market the most</Sub>
          <ul>{(ev.moves?.underperformed ?? []).map((m) => <MoveRow key={m.month} m={m} sector={sector} />)}</ul>
        </div>
      </div>

      <Sub>How it reacted to known events</Sub>
      {shown.length === 0 ? <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>None of the listed events fall inside this sector&apos;s history.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                <th className="py-1 text-left font-normal">Event</th><th className="text-right font-normal">That month: sector</th><th className="text-right font-normal">all stocks</th>
                <th className="text-right font-normal">Next 3 months: sector</th><th className="text-right font-normal">all stocks</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.month + r.title} className="border-t" style={{ borderColor: "var(--border-subtle)" }}>
                  <td className="py-1.5 pr-3">{r.title} <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>({ym(`${r.month}-01`)}{r.scope === "sectors" ? ", this sector" : ""})</span></td>
                  <td className="text-right" style={{ color: tone(r.sector_month) }}>{pct(r.sector_month)}</td>
                  <td className="text-right" style={{ color: tone(r.market_month) }}>{pct(r.market_month)}</td>
                  <td className="text-right" style={{ color: tone(r.sector_after_3m) }}>{pct(r.sector_after_3m)}</td>
                  <td className="text-right" style={{ color: tone(r.market_after_3m) }}>{pct(r.market_after_3m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {reactions.length > 8 && <button onClick={() => setAll((v) => !v)} className="mt-2 text-xs underline" style={{ color: "var(--accent)" }}>{all ? "Show the 8 biggest" : `Show all ${reactions.length}`}</button>}
        </div>
      )}

      {rc && rc.stocks > 0 && (
        <div className="mt-6">
          <Sub>Happening now among its {rc.stocks} companies</Sub>
          <div className="grid gap-5 lg:grid-cols-3">
            <div>
              <div className="mb-1 text-sm font-medium">Order and contract announcements <span className="text-xs font-normal" style={{ color: "var(--text-tertiary)" }}>({rc.orders_count}, last 2 weeks)</span></div>
              {rc.orders.length ? <ul className="space-y-1 text-xs">{rc.orders.slice(0, 5).map((o) => <li key={o.symbol + o.time}>{o.link ? <a href={o.link} target="_blank" rel="noopener noreferrer" className="hover:underline">{o.name ?? o.symbol}</a> : o.name ?? o.symbol}<span style={{ color: "var(--text-tertiary)" }}> · {o.time.slice(0, 11)}</span></li>)}</ul> : <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>None found.</p>}
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">Bulk and block deals <span className="text-xs font-normal" style={{ color: "var(--text-tertiary)" }}>({rc.deals_count}, last 30 days)</span></div>
              {rc.deals.length ? (
                <>
                  <p className="mb-1 text-xs" style={{ color: "var(--text-secondary)" }}>Bought ₹{rc.deals_buy_cr.toLocaleString("en-IN")} Cr · sold ₹{rc.deals_sell_cr.toLocaleString("en-IN")} Cr</p>
                  <ul className="space-y-1 text-xs">{rc.deals.slice(0, 5).map((d) => <li key={d.date + d.symbol + d.client + d.value_cr}>{d.name ?? d.symbol}: {d.side ?? ""} ₹{d.value_cr.toLocaleString("en-IN")} Cr <span style={{ color: "var(--text-tertiary)" }}>· {d.date}</span></li>)}</ul>
                </>
              ) : <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>None found.</p>}
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">Results and board meetings <span className="text-xs font-normal" style={{ color: "var(--text-tertiary)" }}>({rc.upcoming_count}, next 3 weeks)</span></div>
              {rc.upcoming.length ? <ul className="space-y-1 text-xs">{rc.upcoming.slice(0, 6).map((u) => <li key={u.symbol + u.date}>{u.name ?? u.symbol}<span style={{ color: "var(--text-tertiary)" }}> · {u.date}</span></li>)}</ul> : <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>None announced yet.</p>}
            </div>
          </div>
        </div>
      )}
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
      <div className="lg:col-span-2"><WhatMoved sector={s.sector} /></div>
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
