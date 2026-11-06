"use client";

import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/api";
import { SlidingTabs } from "./controls";
import { navigateTo } from "./scanners";

export type AnalyticsTab = "sectors" | "rrg" | "breadth";

const GAIN = "var(--gain)";
const LOSS = "var(--loss)";
const QCOLOR: Record<string, string> = { leading: "#10b981", improving: "#3b82f6", weakening: "#f59e0b", lagging: "#ef4444" };
const QLABEL: Record<string, string> = { leading: "Leading", improving: "Improving", weakening: "Weakening", lagging: "Lagging" };

const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const plain = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);

interface SectorRow {
  name: string; stocks: number; ret_1d: number | null; ret_1w: number | null; ret_1m: number | null; ret_3m: number | null; ret_6m: number | null;
  ret_1y: number | null; above_50: number | null; above_200: number | null; rs: number | null; quadrant: string | null; vs_1m: number | null;
}
interface SectorsRes { stocks: number; benchmark: string; benchmark_returns: Record<string, number | null>; sectors: SectorRow[] }
interface RrgSector { name: string; quadrant: string; ratio: number; momentum: number; trail?: [number, number][] }
interface RrgRes { timeframe: string; benchmark: string; sectors: RrgSector[]; available: boolean }
interface BreadthRes {
  as_of?: string; stocks: number; universe?: number;
  today?: { advancing: number; declining: number; unchanged: number; advancing_pct: number | null; new_52w_highs: number; new_52w_lows: number; above_20: number | null; above_50: number | null; above_200: number | null };
  history?: { date: string; above_50: number | null; above_200: number | null; advancing: number | null; advances?: number; declines?: number; up_4_5?: number | null; down_4_5?: number | null; highs_52w?: number | null; lows_52w?: number | null; vol_above_20d?: number | null }[];
}

function useLoad<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    fetchJson<T>(url).then((d) => alive && setData(d)).catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [url]);
  return { data, error };
}

const Loading = ({ error }: { error: string }) => (
  <div className="py-16 text-center text-sm" style={{ color: error ? "#f5a9a9" : "var(--text-tertiary)" }}>{error ? `Could not load this view: ${error}` : "Loading…"}</div>
);

// ------------------------------------------------------------------ Sector analytics
type SortKey = keyof Pick<SectorRow, "name" | "stocks" | "ret_1d" | "ret_1w" | "ret_1m" | "ret_3m" | "ret_6m" | "ret_1y" | "vs_1m" | "above_50" | "above_200" | "rs">;

function Sectors() {
  const { data, error } = useLoad<SectorsRes>("/api/v1/market/sectors");
  const [key, setKey] = useState<SortKey>("ret_1m");
  const [dir, setDir] = useState<1 | -1>(-1);
  const rows = useMemo(() => {
    const r = [...(data?.sectors ?? [])];
    r.sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return typeof x === "string" ? dir * -x.localeCompare(y as string) : dir * ((x as number) - (y as number));
    });
    return r;
  }, [data, key, dir]);
  if (!data) return <Loading error={error} />;
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.ret_1m ?? 0)));
  const head: { k: SortKey; label: string; left?: boolean }[] = [
    { k: "name", label: "Sector", left: true }, { k: "stocks", label: "Stocks" }, { k: "ret_1d", label: "1D" }, { k: "ret_1w", label: "1W" },
    { k: "ret_1m", label: "1M" }, { k: "ret_3m", label: "3M" }, { k: "ret_6m", label: "6M" }, { k: "ret_1y", label: "1Y" },
    { k: "vs_1m", label: `1M vs ${data.benchmark}` }, { k: "above_50", label: "Above 50 DMA" }, { k: "above_200", label: "Above 200 DMA" }, { k: "rs", label: "Avg RS" },
  ];
  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Each sector is the equal-weighted average of its scanned stocks ({data.stocks} stocks up to date). Strong sectors are where money is flowing; even average
        stocks in them tend to follow. Click a column to sort, a sector to see its companies.
      </p>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
        <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
              {head.map((h) => (
                <th key={h.k} className={`whitespace-nowrap px-3 py-3 font-semibold sm:px-4 ${h.left ? "text-left" : "text-right"}`}>
                  <button type="button" className="inline-flex min-h-[32px] items-center gap-1" onClick={() => (key === h.k ? setDir((d) => (d === 1 ? -1 : 1)) : (setKey(h.k), setDir(h.k === "name" ? 1 : -1)))}>
                    {h.label}{key === h.k ? (dir === 1 ? " ▲" : " ▼") : ""}
                  </button>
                </th>
              ))}
              <th className="px-3 py-3 text-left font-semibold sm:px-4">Rotation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="cursor-pointer border-t transition-colors hover:bg-[var(--overlay-weak)]" style={{ borderColor: "var(--border-subtle)" }} onClick={() => navigateTo({ type: "sector", name: r.name })}>
                <td className="px-3 py-3 font-medium sm:px-4"><div className="max-w-[220px]">{r.name}</div></td>
                <td className="nv-num px-3 py-3 text-right sm:px-4">{r.stocks}</td>
                {([r.ret_1d, r.ret_1w] as (number | null)[]).map((v, i) => <td key={i} className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(v) }}>{pct(v)}</td>)}
                <td className="px-3 py-3 text-right sm:px-4">
                  <div className="flex items-center justify-end gap-2">
                    <div className="hidden h-1.5 w-16 overflow-hidden rounded-full sm:block" style={{ background: "var(--overlay)" }}>
                      <div className="h-full rounded-full" style={{ width: `${Math.min(100, (Math.abs(r.ret_1m ?? 0) / max) * 100)}%`, background: tone(r.ret_1m) }} />
                    </div>
                    <span className="nv-num" style={{ color: tone(r.ret_1m) }}>{pct(r.ret_1m)}</span>
                  </div>
                </td>
                {([r.ret_3m, r.ret_6m, r.ret_1y, r.vs_1m] as (number | null)[]).map((v, i) => <td key={i} className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(v) }}>{pct(v)}</td>)}
                <td className="nv-num px-3 py-3 text-right sm:px-4">{plain(r.above_50)}</td>
                <td className="nv-num px-3 py-3 text-right sm:px-4">{plain(r.above_200)}</td>
                <td className="nv-num px-3 py-3 text-right sm:px-4">{r.rs == null ? "—" : r.rs.toFixed(0)}</td>
                <td className="px-3 py-3 sm:px-4">
                  {r.quadrant ? <span className="whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium" style={{ background: `${QCOLOR[r.quadrant]}22`, color: QCOLOR[r.quadrant] }}>{QLABEL[r.quadrant]}</span> : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
        Index returns used for comparison: Nifty 500 1W {pct(data.benchmark_returns["1w"])}, 1M {pct(data.benchmark_returns["1m"])}, 3M {pct(data.benchmark_returns["3m"])}.
        Averages are equal-weighted and use only stocks that have the data; a blank means it cannot be computed.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ Relative rotation graph
function Rrg() {
  const [timeframe, setTimeframe] = useState<"weekly" | "daily">("weekly");
  const [benchmark, setBenchmark] = useState<"nifty50" | "nifty500">("nifty50");
  const { data, error } = useLoad<RrgRes>(`/api/v1/market/rrg?timeframe=${timeframe}&benchmark=${benchmark}&trail=5`);
  const [hover, setHover] = useState<string | null>(null);
  const [showTrails, setShowTrails] = useState(false);
  const W = 760, H = 520, PAD = 44;
  const geo = useMemo(() => {
    // the scale follows where the sectors are NOW; older trail points that fall outside are pinned to the frame edge
    const ends = (data?.sectors ?? []).map((s) => [s.ratio, s.momentum] as [number, number]);
    const half = Math.max(2, ...ends.map(([x, y]) => Math.max(Math.abs(x - 100), Math.abs(y - 100)))) * 1.3;
    const clamp = (v: number) => Math.max(100 - half, Math.min(100 + half, v));
    const sx = (x: number) => PAD + ((clamp(x) - (100 - half)) / (2 * half)) * (W - 2 * PAD);
    const sy = (y: number) => H - PAD - ((clamp(y) - (100 - half)) / (2 * half)) * (H - 2 * PAD);
    // labels: the sectors farthest from the centre first; a label is skipped when it would sit on one already placed (hover shows any sector)
    const shown = new Set<string>();
    const placed: [number, number][] = [];
    [...(data?.sectors ?? [])]
      .sort((a, b) => Math.hypot(b.ratio - 100, b.momentum - 100) - Math.hypot(a.ratio - 100, a.momentum - 100))
      .forEach((s) => {
        const px = sx(s.ratio), py = sy(s.momentum);
        if (placed.every(([x, y]) => Math.abs(x - px) > 70 || Math.abs(y - py) > 14)) {
          placed.push([px, py]);
          shown.add(s.name);
        }
      });
    return { half, sx, sy, shown };
  }, [data]);
  const head = (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <SlidingTabs ariaLabel="Timeframe" value={timeframe} onChange={setTimeframe} options={[{ id: "weekly", label: "Weekly" }, { id: "daily", label: "Daily" }]} />
      <SlidingTabs ariaLabel="Benchmark" value={benchmark} onChange={setBenchmark} options={[{ id: "nifty50", label: "vs Nifty 50" }, { id: "nifty500", label: "vs Nifty 500" }]} />
      <label className="flex min-h-[40px] cursor-pointer items-center gap-2 text-sm sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <input type="checkbox" checked={showTrails} onChange={(e) => setShowTrails(e.target.checked)} className="h-4 w-4 accent-[#b7b4e7]" />
        Show trails (hover a sector to see its own)
      </label>
    </div>
  );
  if (!data) return <div>{head}<Loading error={error} /></div>;
  if (!data.available) return <div>{head}<Loading error="Not enough index history to draw the rotation graph yet." /></div>;
  const { sx, sy, shown } = geo;
  const order = ["leading", "improving", "weakening", "lagging"];
  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Every sector is a trail on four quadrants, measured against the {benchmark === "nifty50" ? "Nifty 50" : "Nifty 500"}. <b>Leading</b> (top right): strong and getting stronger.
        <b> Improving</b> (top left): gaining momentum. <b>Weakening</b> (bottom right): strong but slowing. <b>Lagging</b> (bottom left): weak. A trail moving from Improving toward
        Leading shows a sector about to take off. This is an open approximation of the rotation graph, not the licensed JdK formula.
      </p>
      {head}
      <div className="overflow-x-auto rounded-xl border p-2" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto block h-auto w-full min-w-[460px] max-w-[900px]" role="img" aria-label="Sector relative rotation graph">
          <rect x={sx(100)} y={PAD} width={W - PAD - sx(100)} height={sy(100) - PAD} fill={QCOLOR.leading} opacity="0.07" />
          <rect x={PAD} y={PAD} width={sx(100) - PAD} height={sy(100) - PAD} fill={QCOLOR.improving} opacity="0.07" />
          <rect x={sx(100)} y={sy(100)} width={W - PAD - sx(100)} height={H - PAD - sy(100)} fill={QCOLOR.weakening} opacity="0.07" />
          <rect x={PAD} y={sy(100)} width={sx(100) - PAD} height={H - PAD - sy(100)} fill={QCOLOR.lagging} opacity="0.07" />
          <line x1={sx(100)} y1={PAD} x2={sx(100)} y2={H - PAD} stroke="var(--border-default)" />
          <line x1={PAD} y1={sy(100)} x2={W - PAD} y2={sy(100)} stroke="var(--border-default)" />
          {([["Improving", PAD + 8, PAD + 16, "start"], ["Leading", W - PAD - 8, PAD + 16, "end"], ["Lagging", PAD + 8, H - PAD - 8, "start"], ["Weakening", W - PAD - 8, H - PAD - 8, "end"]] as [string, number, number, "start" | "end"][]).map(([t, x, y, a]) => (
            <text key={t} x={x} y={y} textAnchor={a} fontSize="13" fontWeight="600" fill={QCOLOR[t.toLowerCase()]} opacity="0.85">{t}</text>
          ))}
          <text x={W / 2} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--text-tertiary)">RS-Ratio (relative strength) →</text>
          <text x={14} y={H / 2} textAnchor="middle" fontSize="11" fill="var(--text-tertiary)" transform={`rotate(-90 14 ${H / 2})`}>RS-Momentum →</text>
          {data.sectors.map((s) => {
            const pts = (s.trail ?? [[s.ratio, s.momentum]]).map(([x, y]) => `${sx(x)},${sy(y)}`);
            const last = (s.trail ?? [[s.ratio, s.momentum]]).slice(-1)[0];
            const dim = hover && hover !== s.name;
            return (
              <g key={s.name} opacity={dim ? 0.18 : 1} onMouseEnter={() => setHover(s.name)} onMouseLeave={() => setHover(null)} style={{ cursor: "pointer" }}>
                {(showTrails || hover === s.name) && <polyline points={pts.join(" ")} fill="none" stroke={QCOLOR[s.quadrant]} strokeWidth="1.4" strokeLinejoin="round" opacity="0.55" />}
                <circle cx={sx(last[0])} cy={sy(last[1])} r="5.5" fill={QCOLOR[s.quadrant]} stroke="var(--surface-1)" strokeWidth="1.5" />
                {(shown.has(s.name) || hover === s.name) && <text x={sx(last[0]) + 8} y={sy(last[1]) + 4} fontSize="11" fontWeight={hover === s.name ? 700 : 400} fill="var(--text-primary)">{s.name.split(/[ ,(/]/)[0]}</text>}
                <title>{`${s.name}: ${QLABEL[s.quadrant]} (RS-Ratio ${s.ratio}, RS-Momentum ${s.momentum})`}</title>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {order.map((q) => (
          <div key={q} className="rounded-xl border p-3" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: QCOLOR[q] }}>{QLABEL[q]}</div>
            <div className="flex flex-wrap gap-1.5">
              {data.sectors.filter((s) => s.quadrant === q).map((s) => (
                <button key={s.name} type="button" onClick={() => navigateTo({ type: "sector", name: s.name })} onMouseEnter={() => setHover(s.name)} onMouseLeave={() => setHover(null)}
                  className="rounded-full border px-3 py-2 text-xs transition-colors hover:bg-[var(--overlay-weak)] sm:px-2.5 sm:py-1" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  {s.name}
                </button>
              ))}
              {data.sectors.filter((s) => s.quadrant === q).length === 0 && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>None right now</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Market breadth
function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
      <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{label}</div>
      <div className="nv-num mt-1 text-2xl font-semibold" style={{ color: color ?? "var(--text-primary)" }}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-tertiary)" }}>{sub}</div>}
    </div>
  );
}

type HistRow = NonNullable<BreadthRes["history"]>[number];
type HistKey = Exclude<keyof HistRow, "date">;

/** A small multi-line history chart (SVG). Points where a series has no value are skipped, never drawn as zero. */
function HistChart({ title, hist, series, unit }: { title: string; hist: HistRow[]; series: { k: HistKey; label: string; color: string }[]; unit?: string }) {
  const W = 560, H = 220, PX = 38, PY = 14;
  const vals = series.flatMap((s) => hist.map((h) => h[s.k]).filter((v): v is number => typeof v === "number"));
  if (vals.length === 0) return null;
  const top = unit === "%" ? 100 : Math.max(1, ...vals) * 1.08;
  const x = (i: number) => PX + (i / Math.max(1, hist.length - 1)) * (W - PX - 8);
  const y = (v: number) => H - PY - (v / top) * (H - 2 * PY);
  const path = (k: HistKey) => {
    let d = "", pen = false;
    hist.forEach((h, i) => {
      const v = h[k];
      if (typeof v !== "number") { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
      pen = true;
    });
    return d;
  };
  const ticks = unit === "%" ? [20, 50, 80] : [0.25, 0.5, 0.75].map((f) => Math.round(top * f));
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
      <div className="mb-1 text-sm font-semibold">{title}</div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs">
        {series.map((s) => <span key={s.k} className="flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}><span className="h-2 w-2 rounded-full" style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full min-w-[360px]" role="img" aria-label={title}>
          {ticks.map((g) => (
            <g key={g}><line x1={PX} x2={W - 8} y1={y(g)} y2={y(g)} stroke="var(--border-subtle)" strokeDasharray="3 4" /><text x={4} y={y(g) + 4} fontSize="10" fill="var(--text-tertiary)">{g}{unit ?? ""}</text></g>
          ))}
          {series.map((s) => <path key={s.k} d={path(s.k)} fill="none" stroke={s.color} strokeWidth="1.8" strokeLinejoin="round" />)}
          <text x={PX} y={H - 1} fontSize="10" fill="var(--text-tertiary)">{hist[0].date}</text>
          <text x={W - 8} y={H - 1} fontSize="10" textAnchor="end" fill="var(--text-tertiary)">{hist[hist.length - 1].date}</text>
        </svg>
      </div>
    </div>
  );
}

function Breadth() {
  const { data, error } = useLoad<BreadthRes>("/api/v1/market/breadth");
  if (!data || !data.today) return <Loading error={error} />;
  const t = data.today;
  const verdict = t.above_50 == null ? "" : t.above_50 >= 60 ? "Broad, healthy strength" : t.above_50 >= 40 ? "Mixed participation" : "Narrow, fragile market";
  const hist = (data.history ?? []).filter((h) => h.above_50 != null);
  const series: { k: HistKey; label: string; color: string }[] = [
    { k: "above_50", label: "Above 50 DMA", color: "#3b82f6" }, { k: "above_200", label: "Above 200 DMA", color: "#f59e0b" }, { k: "advancing", label: "Advancing that day", color: "#10b981" },
  ];
  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Breadth shows whether a rally is healthy or fragile. If the index rises while only a fifth of stocks take part, that is a narrow move; when most stocks rise
        together it is broad strength. Based on {data.stocks} scanned stocks as of {data.as_of}.
      </p>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Advancing today" value={`${t.advancing}`} sub={`${t.declining} declining · ${plain(t.advancing_pct)} advancing`} color={GAIN} />
        <Stat label="Above 50-day average" value={plain(t.above_50)} sub={verdict} />
        <Stat label="Above 200-day average" value={plain(t.above_200)} />
        <Stat label="Above 20-day average" value={plain(t.above_20)} />
        <Stat label="New 52-week highs" value={`${t.new_52w_highs}`} color={GAIN} />
        <Stat label="At 52-week lows" value={`${t.new_52w_lows}`} sub="within 0.5% of the low" color={LOSS} />
      </div>
      {hist.length > 1 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <HistChart title="Share of stocks above their moving averages" unit="%" hist={hist} series={series} />
          <HistChart title="Stocks up / down 4.5% in a day" hist={hist} series={[{ k: "up_4_5", label: "Up 4.5%+", color: "#10b981" }, { k: "down_4_5", label: "Down 4.5%+", color: "#ef4444" }]} />
          <HistChart title="Advances and declines" hist={hist} series={[{ k: "advances", label: "Advances", color: "#10b981" }, { k: "declines", label: "Declines", color: "#ef4444" }]} />
          <HistChart title="52-week highs and lows (closing basis)" hist={hist} series={[{ k: "highs_52w", label: "New 52-week high", color: "#10b981" }, { k: "lows_52w", label: "New 52-week low", color: "#ef4444" }]} />
          <HistChart title="Stocks with volume above their 20-day average" hist={hist} series={[{ k: "vol_above_20d", label: "Volume above 20-day average", color: "#3b82f6" }]} />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ page
const TITLES: Record<AnalyticsTab, string> = { sectors: "Sector Analytics", rrg: "Relative Rotation Graph (RRG)", breadth: "Market Breadth" };

export function MarketAnalytics({ tab, onTab, onBack }: { tab: AnalyticsTab; onTab: (t: AnalyticsTab) => void; onBack: () => void }) {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <h1 className="text-3xl font-bold tracking-tight">{TITLES[tab]}</h1>
      <div className="mb-6 mt-4 max-w-full overflow-x-auto">
        <SlidingTabs ariaLabel="Market analytics" value={tab} onChange={onTab} options={[{ id: "sectors", label: "Sectors" }, { id: "rrg", label: "RRG" }, { id: "breadth", label: "Breadth" }]} />
      </div>
      {tab === "sectors" ? <Sectors /> : tab === "rrg" ? <Rrg /> : <Breadth />}
    </div>
  );
}
