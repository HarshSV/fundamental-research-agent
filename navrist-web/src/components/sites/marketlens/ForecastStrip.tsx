"use client";

import { useState, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown, Minus } from "lucide-react";
import { CandleLoader } from "./CandleLoader";
import { basisNote, type Forecast } from "./forecast";

const SPAN = { session: "Next session", week: "Next 5 sessions", month: "Next 20 sessions" } as const;
const price = (v: number | undefined, d: number) => (v == null ? "—" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`);

const num = (v: number) => v.toLocaleString("en-IN");
const GAIN = "var(--gain)";
const LOSS = "var(--loss)";

/** A stock with too few sessions for any odds: what its data does show, and when odds start. Unmeasurable values show a dash, never zero. */
function YoungFacts({ y }: { y: NonNullable<Forecast["young"]> }) {
  const [open, setOpen] = useState(false);
  const p = (v: number | null | undefined) => (v == null ? "—" : price(v, 2));
  const when = new Date(y.starts_around).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  const cards: { label: string; value: ReactNode; sub: string; color?: string }[] = [
    { label: "Since listing", value: y.since_listing ? `${y.since_listing.pct > 0 ? "+" : ""}${y.since_listing.pct}%` : "—", sub: y.since_listing ? `${p(y.since_listing.from)} to ${p(y.since_listing.to)}` : "needs a second session", color: y.since_listing ? (y.since_listing.pct > 0 ? GAIN : y.since_listing.pct < 0 ? LOSS : undefined) : undefined },
    { label: "Typical daily move", value: y.typical_move_pct != null ? `${y.typical_move_pct}%` : "—", sub: y.typical_move_pct != null ? `average of ${y.sessions} sessions` : "needs about 5 sessions" },
    { label: "Today's range", value: y.today ? `${p(y.today.low)} to ${p(y.today.high)}` : "—", sub: y.today?.width_pct != null ? `${y.today.width_pct}% wide` : "" },
    { label: "Range since listing", value: y.range ? `${p(y.range.low)} to ${p(y.range.high)}` : "—", sub: y.range?.where ? `price is ${y.range.where}` : "needs a second session" },
    { label: "Nearest support", value: p(y.support), sub: y.support != null ? "lowest close so far" : "needs a second session", color: y.support != null ? GAIN : undefined },
    { label: "Nearest resistance", value: p(y.resistance), sub: y.resistance != null ? "highest close so far" : "needs a second session", color: y.resistance != null ? LOSS : undefined },
    { label: "Up days vs down days", value: y.days ? <><span style={{ color: GAIN }}>{y.days.up} up</span>, <span style={{ color: LOSS }}>{y.days.down} down</span></> : "—", sub: y.days ? `closed higher or lower than the day before${y.days.flat ? `; ${y.days.flat} unchanged` : ""}` : "needs a second session" },
    { label: "Volume today", value: y.volume ? num(y.volume.today) : "—", sub: y.volume?.average != null ? `average so far ${num(y.volume.average)}` : `vs average: — (needs about 5 sessions)` },
  ];
  return (
    <div className="mb-8 rounded-xl border px-4 py-3" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }} aria-label="Forecast">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md px-2.5 py-1 text-xs" style={{ background: "var(--overlay-weak)", color: "var(--text-secondary)" }}>Too new to forecast</span>
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {y.sessions} sessions of price history. Odds start at {y.needed}, in about {y.starts_in} sessions (around {when}). Until then, here is what the data does show.
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex min-h-8 items-center gap-1 rounded-md border px-3 py-1 text-xs font-medium hover:opacity-80"
          style={{ borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }}
        >
          Facts
          <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
        </button>
      </div>
      {open && (
        <>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--overlay-weak)" }}>
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, (y.sessions / y.needed) * 100)}%`, background: "var(--accent)" }} />
          </div>
          <div className="mt-1 flex justify-between text-[11px]" style={{ color: "var(--text-tertiary)" }}><span>{y.sessions} sessions</span><span>{y.needed} needed</span></div>
          <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
            {cards.map((c) => (
              <div key={c.label} className="rounded-lg border px-3 py-2" style={{ borderColor: "var(--border-subtle)" }}>
                <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{c.label}</div>
                <div className="text-sm font-semibold" style={{ color: c.color ?? "var(--text-primary)" }}>{c.value}</div>
                {c.sub && <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>{c.sub}</div>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** The forecast in one line per horizon, above the price chart: the lean, the odds of a clear rise and fall, and where the price is likely to
 *  land. It reads the same data as the Forecast section below (so it follows its Full history / Last 5 years setting). */
export function ForecastStrip({ data, loading = false, error = false }: { data: Forecast | null; loading?: boolean; error?: boolean }) {
  const rows = (data?.outlook ?? []).filter((h) => h.up != null);
  if (!rows.length) {
    // Never leave the heading empty: say whether the forecast is still loading, could not be read, or cannot be made for this stock (and why).
    const reasons = [...new Set((data?.outlook ?? []).map((h) => h.reason).filter((r): r is string => Boolean(r)))];
    if (!error && data?.young) return <YoungFacts y={data.young} />;
    if (!error && (loading || !data)) {
      return (
        <div className="mb-8" aria-label="Forecast">
          <CandleLoader label="Loading the forecast…" height={64} />
        </div>
      );
    }
    const text = error
      ? "The forecast could not be read right now."
      : loading || !data
        ? "Loading the forecast…"
        : reasons.length
          ? `No forecast for this stock yet. ${reasons.filter((r) => r !== "Not enough history.").join(" ") || reasons[0]}`
          : "No forecast is available for this stock right now.";
    return (
      <p className="mb-8 rounded-lg border px-3 py-2.5 text-sm" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)", color: "var(--text-secondary)" }} aria-label="Forecast">
        {text}
      </p>
    );
  }
  const dp = (rows[0].price_mid ?? data?.price ?? 1000) < 100 ? 2 : 0;
  return (
    <div className="mb-8" aria-label="Forecast">
    {basisNote(data) && <p className="mb-2 text-xs" style={{ color: "var(--text-tertiary)" }}>{basisNote(data)}</p>}
    <div className="grid gap-2 sm:grid-cols-3">
      {rows.map((h) => {
        const call = h.call;
        const color = call === "up" ? "var(--gain)" : call === "down" ? "var(--loss)" : "var(--text-secondary)";
        const Icon = call === "up" ? ArrowUpRight : call === "down" ? ArrowDownRight : Minus;
        const lean = call === "up" ? "Leans up" : call === "down" ? "Leans down" : "Too close to call";
        return (
          <div key={h.id} className="rounded-xl border px-3 py-2.5" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <div className="flex items-center justify-between gap-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
              <span>{SPAN[h.id]}</span>
              <span>{h.samples ? `${h.samples.toLocaleString("en-IN")} similar days` : ""}</span>
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-sm font-semibold" style={{ color }}>
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              {lean}
              <span className="font-normal" style={{ color: "var(--text-secondary)" }}>
                · <span style={{ color: "var(--gain)" }}>{h.up}%</span> up · <span style={{ color: "var(--loss)" }}>{h.down}%</span> down
              </span>
            </div>
            {h.price_low != null && h.price_high != null && (
              <div className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                Likely range {price(h.price_low, dp)} to {price(h.price_high, dp)}
              </div>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}
