"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import type { CatalogueEntry } from "./patterns";
import { fetchBacktest, type BacktestResult, type ScanFilters } from "./patternScan";

const PAGE = 25;
const GAIN = "var(--gain)";
const LOSS = "var(--loss)";

const pct = (v: number | null | undefined, d = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? GAIN : LOSS);
const date = (ts: number) => new Date((ts + 19800) * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
      <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{label}</div>
      <div className="mt-1 text-xl font-semibold" style={{ color }}>{value}</div>
    </div>
  );
}

/** Return distribution at one horizon: a bar per 2.5% bucket, losses red, gains green, the two ends open-ended. */
function Histogram({ bins }: { bins: BacktestResult["histogram"] }) {
  const max = Math.max(1, ...bins.map((b) => b.n));
  const W = 640;
  const H = 150;
  const bw = W / bins.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 28}`} className="w-full" role="img" aria-label="Distribution of returns">
      {bins.map((b, i) => {
        const h = (b.n / max) * H;
        const win = b.lo != null && b.lo >= 0;
        return (
          <g key={i}>
            <rect x={i * bw + 2} y={H - h} width={bw - 4} height={Math.max(h, b.n ? 1 : 0)} rx={2} fill={win ? GAIN : LOSS} opacity={0.85}>
              <title>{`${b.lo == null ? "below" : b.lo}${b.lo != null && b.hi != null ? " to " : ""}${b.hi == null ? " and above" : b.hi}%: ${b.n} trades`}</title>
            </rect>
            {b.n > 0 && <text x={i * bw + bw / 2} y={H - h - 4} textAnchor="middle" fontSize="9" fill="var(--text-tertiary)">{b.n}</text>}
            {i % 2 === 0 && (
              <text x={i * bw + bw / 2} y={H + 16} textAnchor="middle" fontSize="9" fill="var(--text-tertiary)">
                {b.lo == null ? `<${b.hi}` : b.hi == null ? `${b.lo}+` : b.lo}
              </text>
            )}
          </g>
        );
      })}
      <line x1={W / 2} x2={W / 2} y1={0} y2={H} stroke="var(--border-default)" strokeDasharray="3 3" />
    </svg>
  );
}

/**
 * Backtest of one pattern: every time it confirmed in the last five years on the scanned stocks that pass the filters,
 * entered at the confirming close in the pattern's direction and measured 5 to 60 bars later.
 */
export function BacktestPanel({ pattern, filters, onOpenStock }: { pattern: CatalogueEntry; filters: ScanFilters; onOpenStock: (s: CompanyHit) => void }) {
  const [horizon, setHorizon] = useState(20);
  const [page, setPage] = useState(1);
  const [res, setRes] = useState<{ key: string; data?: BacktestResult; error?: string } | null>(null);
  const key = useMemo(() => JSON.stringify([pattern.id, filters, horizon, page]), [pattern.id, filters, horizon, page]);

  useEffect(() => {
    let alive = true;
    fetchBacktest(pattern.id, filters, { horizon, page, page_size: PAGE })
      .then((data) => alive && setRes({ key, data }))
      .catch((e: Error) => alive && setRes({ key, error: e.message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` already captures every input
  }, [key]);

  const loading = !res || res.key !== key;
  const d = res?.data;
  const s = d?.stats[String(horizon)];
  const pages = d ? Math.max(1, Math.ceil(d.trades_total / PAGE)) : 1;

  if (res?.error && res.key === key) return <p className="mt-6 text-sm" style={{ color: "#f5a9a9" }}>{res.error}</p>;
  if (!d) return <div className="py-16 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading backtest…</div>;
  if (d.trades_total === 0)
    return (
      <div className="mt-6 rounded-xl border py-16 text-center text-sm" style={{ borderColor: "var(--border-subtle)", color: "var(--text-tertiary)" }}>
        {d.scan.have === 0 ? "The market has not been scanned yet." : "No confirmed trades of this pattern among the stocks that pass these filters."}
      </div>
    );

  return (
    <div className="mt-6" style={{ opacity: loading ? 0.6 : 1, transition: "opacity 150ms" }}>
      <p className="mb-4 max-w-4xl text-xs leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
        Every confirmation of {pattern.name} in the last five years across {d.stocks.toLocaleString("en-IN")} stocks that pass your filters
        ({d.stocks_with_trades.toLocaleString("en-IN")} had at least one). A trade is entered at the close of the confirming bar, long for a bullish
        pattern and short for a bearish one, and measured the chosen number of bars later. It covers stocks listed today (delisted names are absent), ignores
        costs, and overlapping trades in one stock are counted separately. It describes the past, not a forecast.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span style={{ color: "var(--text-secondary)" }}>Measured</span>
        {d.horizons.map((h) => (
          <button
            key={h}
            onClick={() => { setHorizon(h); setPage(1); }}
            className="rounded-lg border px-3 py-2.5 text-xs sm:py-1.5 font-medium transition-colors"
            style={{
              borderColor: horizon === h ? "var(--accent-border)" : "var(--border-default)",
              background: horizon === h ? "var(--accent-surface)" : "transparent",
              color: horizon === h ? "var(--accent)" : "var(--text-secondary)",
            }}
          >
            {h} bars
          </button>
        ))}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Trades" value={d.trades_total.toLocaleString("en-IN")} />
        <Stat label={`Win rate (${horizon} bars)`} value={s?.win_rate == null ? "—" : `${s.win_rate}%`} />
        <Stat label="Average return" value={pct(s?.avg)} color={tone(s?.avg)} />
        <Stat label="Median return" value={pct(s?.median)} color={tone(s?.median)} />
        <Stat label="Best / worst" value={s?.best == null ? "—" : `${pct(s.best, 1)} / ${pct(s.worst, 1)}`} />
        <Stat label="Profit factor" value={s?.profit_factor == null ? "—" : String(s.profit_factor)} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border p-5" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
          <h3 className="mb-3 text-sm font-semibold">Distribution of {horizon}-bar returns</h3>
          <Histogram bins={d.histogram} />
        </div>
        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                <th className="px-4 py-3 text-left font-semibold">Bars after</th>
                <th className="px-4 py-3 text-right font-semibold">Trades</th>
                <th className="px-4 py-3 text-right font-semibold">Win rate</th>
                <th className="px-4 py-3 text-right font-semibold">Average</th>
                <th className="px-4 py-3 text-right font-semibold">Median</th>
                <th className="px-4 py-3 text-right font-semibold">Worst</th>
              </tr>
            </thead>
            <tbody>
              {d.horizons.map((h) => {
                const x = d.stats[String(h)];
                return (
                  <tr key={h} className="border-t" style={{ borderColor: "var(--border-subtle)", background: h === horizon ? "var(--accent-surface)" : undefined }}>
                    <td className="px-4 py-2.5 font-medium">{h}</td>
                    <td className="nv-num px-4 py-2.5 text-right">{x?.n ?? 0}</td>
                    <td className="nv-num px-4 py-2.5 text-right">{x?.win_rate == null ? "—" : `${x.win_rate}%`}</td>
                    <td className="nv-num px-4 py-2.5 text-right" style={{ color: tone(x?.avg) }}>{pct(x?.avg)}</td>
                    <td className="nv-num px-4 py-2.5 text-right" style={{ color: tone(x?.median) }}>{pct(x?.median)}</td>
                    <td className="nv-num px-4 py-2.5 text-right" style={{ color: tone(x?.worst) }}>{pct(x?.worst, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[1fr_2fr]">
        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                <th className="px-4 py-3 text-left font-semibold">Year</th>
                <th className="px-4 py-3 text-right font-semibold">Trades</th>
                <th className="px-4 py-3 text-right font-semibold">Win rate</th>
                <th className="px-4 py-3 text-right font-semibold">Average</th>
              </tr>
            </thead>
            <tbody>
              {d.by_year.map((y) => (
                <tr key={y.year} className="border-t" style={{ borderColor: "var(--border-subtle)" }}>
                  <td className="px-4 py-2.5 font-medium">{y.year}</td>
                  <td className="nv-num px-4 py-2.5 text-right">{y.n ?? 0}</td>
                  <td className="nv-num px-4 py-2.5 text-right">{y.win_rate == null ? "—" : `${y.win_rate}%`}</td>
                  <td className="nv-num px-4 py-2.5 text-right" style={{ color: tone(y.avg) }}>{pct(y.avg)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                  <th className="px-4 py-3 text-left font-semibold">Stock</th>
                  <th className="px-4 py-3 text-left font-semibold">Confirmed</th>
                  <th className="px-4 py-3 text-left font-semibold">Side</th>
                  <th className="px-4 py-3 text-right font-semibold">Entry</th>
                  {d.horizons.map((h) => <th key={h} className="px-3 py-3 text-right font-semibold">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {d.trades.map((t, i) => (
                  <tr
                    key={`${t.symbol}-${t.confirmed_ts}-${i}`}
                    onClick={() => onOpenStock({ symbol: t.symbol, name: t.name })}
                    className="cursor-pointer border-t transition-colors hover:bg-[var(--accent-surface)]"
                    style={{ borderColor: "var(--border-subtle)" }}
                  >
                    <td className="px-4 py-2.5"><div className="font-medium">{t.name}</div><div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{t.symbol}</div></td>
                    <td className="px-4 py-2.5 text-xs">{date(t.confirmed_ts)}</td>
                    <td className="px-4 py-2.5 text-xs" style={{ color: t.direction === "bullish" ? GAIN : LOSS }}>{t.direction === "bullish" ? "Long" : "Short"}</td>
                    <td className="nv-num px-4 py-2.5 text-right">₹{t.entry.toLocaleString("en-IN")}</td>
                    {d.horizons.map((h) => <td key={h} className="nv-num px-3 py-2.5 text-right text-xs" style={{ color: tone(t.returns[String(h)]) }}>{pct(t.returns[String(h)], 1)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs" style={{ color: "var(--text-tertiary)" }}>
            <span>Showing {((page - 1) * PAGE + 1).toLocaleString("en-IN")} - {Math.min(d.trades_total, page * PAGE).toLocaleString("en-IN")} of {d.trades_total.toLocaleString("en-IN")} trades, newest first</span>
            {pages > 1 && (
              <div className="flex items-center gap-2">
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="flex min-h-[40px] items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40 sm:min-h-0" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  <ChevronLeft className="h-3.5 w-3.5" /> Previous
                </button>
                <span className="rounded-lg px-3 py-1.5" style={{ background: "var(--btn-primary-bg)", color: "#fff" }}>{page} / {pages}</span>
                <button onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages} className="flex min-h-[40px] items-center gap-1 rounded-lg border px-3 py-1.5 disabled:opacity-40 sm:min-h-0" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  Next <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
