"use client";

import { STATUS_LABEL, displayName, type CatalogueEntry, type PatternOcc } from "./patterns";

const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const dirTone = (d: string | null | undefined) => (d === "bullish" ? "var(--gain, #10b981)" : d === "bearish" ? "var(--loss, #ef4444)" : "var(--text-secondary)");

/** Patterns that are developing right now (Forming / Awaiting breakout). Click one to outline it on the chart. */
export function ActiveSetups({
  occs, catalogue, ltp, selectedId, onSelect,
}: {
  occs: PatternOcc[];
  catalogue: Record<string, CatalogueEntry>;
  ltp: number | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <div className="mt-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold">Active setups</h3>
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Patterns developing now. Status describes formation, not a forecast.</span>
      </div>
      {occs.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>No pattern is forming or awaiting a breakout on these bars right now.</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {occs.map((o) => {
            const dist = ltp != null && o.breakout_level != null ? ((o.breakout_level - ltp) / ltp) * 100 : null;
            const active = selectedId === o.occ_id;
            return (
              <button
                key={o.occ_id}
                onClick={() => onSelect(active ? null : o.occ_id)}
                aria-pressed={active}
                className="rounded-xl border p-4 text-left text-xs"
                style={{
                  background: active ? "var(--overlay)" : "var(--surface-1)",
                  borderColor: active ? "var(--text-tertiary)" : "var(--border-subtle)",
                  transition: "background 250ms ease, border-color 250ms ease",
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="text-sm font-semibold">{displayName(catalogue, o.pattern)}</span>
                  {o.direction && <span className="font-medium capitalize" style={{ color: dirTone(o.direction) }}>{o.direction}</span>}
                </div>
                <div className="mt-1" style={{ color: "var(--text-tertiary)" }}>
                  {STATUS_LABEL[o.status]} · since {new Date(o.start_ts * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  {o.maturity === "experimental" ? " · experimental" : ""}
                </div>
                <div className="mt-3 space-y-1">
                  <div className="flex items-center justify-between gap-3">
                    <span style={{ color: "var(--text-tertiary)" }}>Breakout</span>
                    <span className="nv-num" style={{ color: "var(--text-primary)" }}>
                      ₹{fmt(o.breakout_level)}
                      {dist != null ? <span className="ml-1.5" style={{ color: dist >= 0 ? "var(--gain, #10b981)" : "var(--loss, #ef4444)" }}>{dist >= 0 ? "+" : ""}{dist.toFixed(1)}%</span> : null}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span style={{ color: "var(--text-tertiary)" }}>Invalidation</span>
                    <span className="nv-num" style={{ color: "var(--text-primary)" }}>₹{fmt(o.invalidation_level)}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
