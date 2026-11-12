"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { Forecast } from "./forecast";

const SPAN = { session: "Next session", week: "Next 5 sessions", month: "Next 20 sessions" } as const;
const price = (v: number | undefined, d: number) => (v == null ? "—" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`);

/** The forecast in one line per horizon, above the price chart: the lean, the odds of a clear rise and fall, and where the price is likely to
 *  land. It reads the same data as the Forecast section below (so it follows its Full history / Last 5 years setting). */
export function ForecastStrip({ data }: { data: Forecast | null }) {
  const rows = (data?.outlook ?? []).filter((h) => h.up != null);
  if (!rows.length) return null;
  const dp = (rows[0].price_mid ?? data?.price ?? 1000) < 100 ? 2 : 0;
  return (
    <div className="mb-3 grid gap-2 sm:grid-cols-3" aria-label="Forecast">
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
  );
}
