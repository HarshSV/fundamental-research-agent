"use client";

import { CalendarDays, ChevronDown, Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchJson } from "@/lib/api";

const GAIN = "var(--gain)";
const LOSS = "var(--loss)";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);

/** A small button that opens a light popover, closed by a click elsewhere or Escape (the same idea as the News button on the stock page). */
function Pop({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const close = () => {
    setShown(false);
    setTimeout(() => setOpen(false), 200);
  };
  const toggle = () => {
    if (open) return close();
    setOpen(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)));
  };
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && close();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  });
  return (
    <div ref={box} className="relative">
      <button onClick={toggle} aria-expanded={open} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:opacity-80" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-1)" }}>
        {icon}
        {label}
      </button>
      {open && (
        <div
          className="absolute left-0 top-full z-30 mt-2 max-h-[28rem] w-[min(34rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border p-4 text-sm shadow-xl"
          style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", opacity: shown ? 1 : 0, transform: shown ? "none" : "translateY(-6px) scale(0.98)", transformOrigin: "top left", transition: "opacity 220ms ease, transform 220ms ease" }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

interface Tilt { direction: "up" | "down" | "none"; size: "none" | "slight" | "clear" }
interface Hz {
  id: "1m" | "3m"; call?: string | null; reason?: string; up?: number; flat?: number; down?: number; beat_market?: number; p10?: number; median?: number; p90?: number;
  samples?: number; basis?: string; flat_band_pct?: number; usual_up?: number; usual_down?: number; usual_beat_market?: number;
  tilt_up_points?: number; tilt_beat_points?: number; tilt?: Tilt;
}
interface Driver { label: string; value: string; tone: "up" | "down"; detail?: string }
interface Row {
  sector: string; available: boolean; as_of: string; stocks: number; situation: string; horizons: Hz[]; drivers: Driver[];
  scenarios: { market_down_10: number; market_up_10: number; beta: number | null } | null;
  results: { available: boolean; quarter?: string; reported?: number; of?: number; median_sales_yoy?: number | null; median_profit_yoy?: number | null; profit_up_share?: number | null };
  flow: { orders_2w: number | null; deals_buy_cr: number | null; deals_sell_cr: number | null; deals_count: number | null };
  upcoming: {
    results_due_21d: number; seasonal_next_3: { month: number; average: number; positive_share: number | null; years: number }[];
    actions?: { ok: boolean; count: number; kinds: Record<string, number>; items: { date: string; symbol: string; name: string; subject: string }[] };
  };
}
interface Scheduled { events: { date: string; title: string; scope: string; source: string; expected: boolean }[]; unreadable: string[]; rbi_headlines: { title: string; link: string; date: string }[]; note: string }
interface Grp { months: number; share: number | null }
interface Val { months_tested: number; usual_rose: number | null; usual_beat_market: number | null; tilt_up_rose: Grp; tilt_down_rose: Grp; tilt_up_beat: Grp; tilt_down_beat: Grp }
interface Res { ready: boolean; note?: string; as_of?: string; sectors: Row[]; scheduled?: Scheduled; validation?: { ready: boolean; horizons: Record<string, Val>; meaning: string } }

function TiltChip({ h }: { h: Hz }) {
  const t = h.tilt;
  if (!t || h.up == null) return <span style={{ color: "var(--text-tertiary)" }}>—</span>;
  const txt = t.direction === "none" ? "Usual odds" : `${t.size === "clear" ? "Clearly" : "Slightly"} ${t.direction === "up" ? "better" : "worse"}`;
  const c = t.direction === "up" ? GAIN : t.direction === "down" ? LOSS : "var(--text-tertiary)";
  return <span className="whitespace-nowrap text-xs font-medium" style={{ color: c }}>{txt}</span>;
}

function OddsBar({ h }: { h: Hz }) {
  if (h.up == null) return <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>{h.reason ?? "Not enough history."}</p>;
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full" style={{ background: "var(--overlay)" }} role="img" aria-label={`Up ${h.up}%, flat ${h.flat}%, down ${h.down}%`}>
        <div style={{ width: `${h.up}%`, background: "var(--gain)" }} />
        <div style={{ width: `${h.flat}%`, background: "var(--text-tertiary)", opacity: 0.45 }} />
        <div style={{ width: `${h.down}%`, background: "var(--loss)" }} />
      </div>
      <p className="mt-2 text-sm">
        <b style={{ color: GAIN }}>{h.up}%</b> clear rise · <b>{h.flat}%</b> flat · <b style={{ color: LOSS }}>{h.down}%</b> clear fall
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}> (flat = within ±{h.flat_band_pct}%)</span>
      </p>
      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
        Usual for this sector: {h.usual_up}% rise · {h.usual_down}% fall. Chance of beating all stocks: {h.beat_market}% (usual {h.usual_beat_market}%).
      </p>
      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
        Range of past outcomes: {pct(h.p10)} (1 in 10 worst) · median {pct(h.median)} · {pct(h.p90)} (1 in 10 best). Based on {h.samples} past months, {h.basis}.
      </p>
    </div>
  );
}

function Detail({ r }: { r: Row }) {
  const sc = r.scenarios;
  const res = r.results;
  return (
    <div className="grid gap-6 p-4 lg:grid-cols-2" style={{ background: "var(--overlay-weak)" }}>
      <div className="lg:col-span-2 text-sm" style={{ color: "var(--text-secondary)" }}>
        Its situation at the end of {r.as_of}: <b style={{ color: "var(--text-primary)" }}>{r.situation}</b>.
      </div>
      {r.horizons.map((h) => (
        <div key={h.id}>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Next {h.id === "1m" ? "1 month" : "3 months"}</div>
          <OddsBar h={h} />
        </div>
      ))}
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Where it stands now</div>
        <ul className="space-y-1 text-sm">
          {r.drivers.map((d) => (
            <li key={d.label} className="flex justify-between gap-3">
              <span style={{ color: "var(--text-secondary)" }}>{d.label}</span>
              <span style={{ color: d.tone === "up" ? GAIN : LOSS }}>{d.value}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="space-y-4">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>This quarter&apos;s results</div>
          {res.available ? (
            <ul className="space-y-1 text-sm">
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Reported {res.quarter}</span><span>{res.reported} of {res.of} stocks</span></li>
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Median sales growth, year on year</span><span style={{ color: tone(res.median_sales_yoy) }}>{pct(res.median_sales_yoy)}</span></li>
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Median profit growth, year on year</span><span style={{ color: tone(res.median_profit_yoy) }}>{pct(res.median_profit_yoy)}</span></li>
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Stocks with higher profit</span><span>{res.profit_up_share == null ? "—" : `${res.profit_up_share}%`}</span></li>
            </ul>
          ) : <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Quarterly results are not available.</p>}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Upcoming and flow</div>
          <ul className="space-y-1 text-sm">
            <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Results due in the next 3 weeks</span><span>{r.upcoming.results_due_21d} stocks</span></li>
            <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Dividends, bonus, splits and buy-backs, next 30 days</span><span>{r.upcoming.actions?.ok ? (r.upcoming.actions.count ? Object.entries(r.upcoming.actions.kinds).map(([k, v]) => `${v} ${k}`).join(", ") : "none") : "could not be read"}</span></li>
            <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Order announcements, last 2 weeks</span><span>{r.flow.orders_2w ?? "—"}</span></li>
            <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Bulk and block deals, 30 days</span><span>bought ₹{(r.flow.deals_buy_cr ?? 0).toLocaleString("en-IN")} Cr · sold ₹{(r.flow.deals_sell_cr ?? 0).toLocaleString("en-IN")} Cr</span></li>
          </ul>
        </div>
      </div>
      <div className="lg:col-span-2 grid gap-6 md:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Its usual pattern in the coming months</div>
          {r.upcoming.seasonal_next_3.length ? (
            <div className="flex gap-2">
              {r.upcoming.seasonal_next_3.map((m) => (
                <div key={m.month} className="flex-1 rounded-md p-2 text-center" style={{ background: m.average >= 0 ? "rgba(16,217,168,.14)" : "rgba(255,95,109,.14)" }}>
                  <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{MONTHS[m.month - 1]}</div>
                  <div className="text-sm font-semibold" style={{ color: tone(m.average) }}>{pct(m.average)}</div>
                  <div className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{m.positive_share == null ? "—" : `${m.positive_share}% of ${m.years} years up`}</div>
                </div>
              ))}
            </div>
          ) : <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Not enough years.</p>}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>If the whole market moves 10%</div>
          {sc ? (
            <ul className="space-y-1 text-sm">
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Market up 10% in a month</span><span style={{ color: GAIN }}>sector about {pct(sc.market_up_10)}</span></li>
              <li className="flex justify-between"><span style={{ color: "var(--text-secondary)" }}>Market down 10% in a month</span><span style={{ color: LOSS }}>sector about {pct(sc.market_down_10)}</span></li>
              <li className="text-xs" style={{ color: "var(--text-tertiary)" }}>From how it moved in past up and down months{sc.beta != null ? ` (beta ${sc.beta})` : ""}.</li>
            </ul>
          ) : <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Not enough history.</p>}
        </div>
      </div>
    </div>
  );
}

function Reliability({ v }: { v: Res["validation"] }) {
  if (!v?.ready) return null;
  const h3 = v.horizons["3m"], h1 = v.horizons["1m"];
  const line = (g: Grp, usual: number | null, up: boolean) => (g.share == null ? "too few months" : `${g.share}% (${g.months.toLocaleString("en-IN")} months) against ${usual}% usually`);
  return (
    <div>
      <div className="mb-1 font-semibold">How far can this be trusted?</div>
      <p className="mb-2 text-xs" style={{ color: "var(--text-secondary)" }}>
        I replayed the method on the past, month by month, using only what was known then ({h3.months_tested.toLocaleString("en-IN")} sector-months). Whenever the situation made a rise more likely by 10 points or more:
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-xs">
        <li>Over the next month the sector rose in <b>{line(h1.tilt_up_rose, h1.usual_rose, true)}</b>; when it made a rise less likely, in <b>{line(h1.tilt_down_rose, h1.usual_rose, false)}</b>.</li>
        <li>Over the next 3 months: <b>{line(h3.tilt_up_rose, h3.usual_rose, true)}</b>, and when less likely, <b>{line(h3.tilt_down_rose, h3.usual_rose, false)}</b>.</li>
        <li>Beating all stocks over 3 months: <b>{line(h3.tilt_up_beat, h3.usual_beat_market, true)}</b> when better, <b>{line(h3.tilt_down_beat, h3.usual_beat_market, false)}</b> when worse.</li>
      </ul>
      <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>{v.meaning} The edge is a few percentage points, so read these as a lean, not a call.</p>
    </div>
  );
}

export function SectorOutlook() {
  const [res, setRes] = useState<Res | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetchJson<Res>("/api/v1/market/sector-outlook").then((d) => alive && setRes(d)).catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, []);
  if (error) return <div className="py-16 text-center text-sm" style={{ color: "#f5a9a9" }}>Could not load this view: {error}</div>;
  if (!res) return <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Working out the outlook…</div>;
  if (!res.ready) return <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>{res.note ?? "Not built yet."}</div>;

  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Odds for each sector over the next month and the next 3 months, from how that sector behaved after similar situations (as of {res.as_of}). The facts beside them are listed, not blended in. {res.note}
      </p>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Pop label="How far can this be trusted?" icon={<Info className="h-4 w-4" aria-hidden />}><Reliability v={res.validation} /></Pop>
        {res.scheduled && (
        <Pop label="Scheduled events ahead" icon={<CalendarDays className="h-4 w-4" aria-hidden />}>
          <div className="mb-1 font-semibold">Scheduled events ahead (next 90 days)</div>
          {res.scheduled.events.length ? (
            <ul className="space-y-1 text-xs">
              {res.scheduled.events.map((e) => (
                <li key={e.date + e.title} className="flex flex-wrap justify-between gap-x-3">
                  <span>{e.title}{e.expected ? " (expected)" : ""}</span>
                  <span style={{ color: "var(--text-tertiary)" }}>{e.date} · {e.source}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>No dated events found.</p>}
          {res.scheduled.rbi_headlines.length > 0 && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
              RBI policy dates: no source we can read gives them, so see {res.scheduled.rbi_headlines.slice(0, 2).map((h, i) => (
                <span key={h.link}>{i ? " · " : ""}<a href={h.link} target="_blank" rel="noopener noreferrer" className="underline">{h.title.slice(0, 70)}</a></span>
              ))}.
            </p>
          )}
          {res.scheduled.unreadable.length > 0 && <p className="mt-1 text-xs" style={{ color: "#f5a9a9" }}>Could not read: {res.scheduled.unreadable.join("; ")}.</p>}
          <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
            The odds below are not adjusted for these. Results due and company actions for each sector are inside its row. {res.scheduled.note}
          </p>
        </Pop>
        )}
      </div>
      <div className="overflow-x-auto rounded-xl border" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="text-left text-xs" style={{ color: "var(--text-tertiary)" }}>
              <th className="px-3 py-2 font-normal">Sector</th>
              <th className="px-2 text-right font-normal">Next month: rise / fall</th><th className="px-2 font-normal">vs its usual</th>
              <th className="px-2 text-right font-normal">Next 3 months: rise / fall</th><th className="px-2 font-normal">vs its usual</th>
              <th className="px-2 text-right font-normal">Beat all stocks (3m)</th><th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {res.sectors.map((r) => {
              const a = r.horizons[0], b = r.horizons[1];
              return (
                <RowView key={r.sector} r={r} a={a} b={b} open={open === r.sector} onToggle={() => setOpen(open === r.sector ? null : r.sector)} />
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
        Sorted by how much the current situation improves the 3-month odds against the sector&apos;s usual. Only stocks listed today are in the history, so the usual odds of a rise are higher than an investor would have seen.
      </p>
    </div>
  );
}

function RowView({ r, a, b, open, onToggle }: { r: Row; a: Hz; b: Hz; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer border-t hover:bg-[var(--overlay-weak)]" style={{ borderColor: "var(--border-subtle)" }}>
        <td className="px-3 py-2.5 font-medium">{r.sector}</td>
        <td className="px-2 text-right">{a.up == null ? "—" : <><span style={{ color: GAIN }}>{a.up}%</span> / <span style={{ color: LOSS }}>{a.down}%</span></>}</td>
        <td className="px-2"><TiltChip h={a} /></td>
        <td className="px-2 text-right">{b.up == null ? "—" : <><span style={{ color: GAIN }}>{b.up}%</span> / <span style={{ color: LOSS }}>{b.down}%</span></>}</td>
        <td className="px-2"><TiltChip h={b} /></td>
        <td className="px-2 text-right">{b.beat_market == null ? "—" : `${b.beat_market}%`}</td>
        <td className="pr-2"><ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} style={{ color: "var(--text-tertiary)" }} /></td>
      </tr>
      {open && <tr><td colSpan={7} className="p-0"><Detail r={r} /></td></tr>}
    </>
  );
}
