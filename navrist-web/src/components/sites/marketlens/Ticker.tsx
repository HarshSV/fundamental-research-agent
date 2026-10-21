"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchJson } from "@/lib/api";

interface Index {
  name: string;
  value: number;
  change: number;
  change_pct: number;
}

const REFRESH_MS = 30_000;

/**
 * Market-index ticker: its own bar above the header, content kept to the page width, edges faded out,
 * items scrolling continuously (pauses on hover). Values are live from the backend; if the data cannot be
 * loaded the bar says so instead of showing stale or invented numbers.
 */
export function Ticker() {
  const [rows, setRows] = useState<Index[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchJson<{ indices: Index[] }>("/api/v1/market-indices", { usable: (d) => (d.indices?.length ?? 0) > 0 })
        .then((d) => {
          if (!alive || !d.indices.length) return;
          setRows(d.indices); // an empty/failed refresh never replaces what is already showing
          setFailed(false);
        })
        .catch(() => alive && setFailed(true));
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const group = (rows ?? []).map((r) => {
    const up = r.change_pct >= 0;
    const Arrow = up ? ArrowUpRight : ArrowDownRight;
    return (
      <div key={r.name} className="flex shrink-0 items-center gap-3">
        <span className="text-[11.25px] tracking-wide" style={{ color: "var(--text-tertiary)" }}>{r.name}</span>
        <span className="nv-num text-[13.125px]" style={{ color: "var(--text-primary)" }}>
          {r.value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        <span className="nv-num flex items-center gap-0.5 text-[11.25px]" style={{ color: up ? "var(--gain)" : "var(--loss)" }}>
          <Arrow className="h-3 w-3" />
          {up ? "+" : ""}
          {r.change_pct.toFixed(2)}%
        </span>
      </div>
    );
  });

  return (
    <div className="border-b" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
      <div className="mx-auto max-w-7xl px-4">
        <div
          className="min-h-[41px] overflow-hidden py-3"
          style={{
            maskImage: "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
            WebkitMaskImage: "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)",
          }}
        >
          {rows ? (
            // two identical halves so the -50% scroll loops without a jump
            <div className="ticker-track flex w-max items-center">
              <div className="flex shrink-0 items-center gap-6 pr-6">{group}</div>
              <div className="flex shrink-0 items-center gap-6 pr-6" aria-hidden="true">{group}</div>
            </div>
          ) : (
            <div className="text-center text-[11.25px]" style={{ color: "var(--text-tertiary)" }}>
              {failed ? "Market index data is unavailable right now." : "Loading market indices…"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
