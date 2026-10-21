"use client";

import { STATUS_COLOR, STATUS_LABEL, displayName, type CatalogueEntry, type PatternOcc } from "./patterns";

const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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
    <div className="mt-5">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        Active setups
        <span className="text-xs font-normal" style={{ color: "var(--text-tertiary)" }}>
          patterns developing now — status describes formation, not a forecast
        </span>
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
                className="rounded-xl border p-3 text-left text-xs transition-colors"
                style={{
                  background: active ? "var(--overlay)" : "var(--surface-1)",
                  borderColor: active ? STATUS_COLOR[o.status] : "var(--border-subtle)",
                }}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{displayName(catalogue, o.pattern)}</span>
                  <span className="rounded-full px-2 py-0.5 font-medium" style={{ background: `${STATUS_COLOR[o.status]}22`, color: STATUS_COLOR[o.status] }}>
                    {STATUS_LABEL[o.status]}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5" style={{ color: "var(--text-secondary)" }}>
                  {o.direction && <span>{o.direction}</span>}
                  <span>since {new Date(o.start_ts * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
                  {o.maturity === "experimental" && <span style={{ color: "#f59e0b" }}>experimental</span>}
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-x-3" style={{ color: "var(--text-tertiary)" }}>
                  <span>Breakout</span>
                  <span className="nv-num text-right" style={{ color: "var(--text-secondary)" }}>
                    ₹{fmt(o.breakout_level)}
                    {dist != null ? ` (${dist >= 0 ? "+" : ""}${dist.toFixed(1)}%)` : ""}
                  </span>
                  <span>Invalidation</span>
                  <span className="nv-num text-right" style={{ color: "var(--text-secondary)" }}>₹{fmt(o.invalidation_level)}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
