"use client";

import { ArrowUpRight, Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { searchSymbols, type CompanyHit } from "@/lib/api";
import type { SectorInfo } from "./screens";
import { useTyped } from "./typing";

const HINTS = ["Banks", "Tata Steel", "Pharmaceuticals", "IT Services", "TCS"];

// Spring curve for the panel (a damped spring sampled as a CSS linear() easing: ~0.8% overshoot, settles
// at ~90% of the duration). Measured from the reference page's own opening transition.
const SPRING =
  "linear(0 0%, 0.023 2.27%, 0.0809 4.55%, 0.1602 6.82%, 0.2505 9.09%, 0.3444 11.36%, 0.4368 13.64%, " +
  "0.5241 15.91%, 0.6042 18.18%, 0.6759 20.45%, 0.7388 22.73%, 0.7929 25%, 0.8388 27.27%, 0.877 29.55%, " +
  "0.9083 31.82%, 0.9337 34.09%, 0.9538 36.36%, 0.9695 38.64%, 0.9816 40.91%, 0.9906 43.18%, " +
  "0.9971 45.45%, 1.0017 47.73%, 1.0047 50%, 1.0066 52.27%, 1.0076 54.55%, 1.0079 56.82%, " +
  "1.0078 59.09%, 1.0074 61.36%, 1.0068 63.64%, 1.0061 65.91%, 1.0054 68.18%, 1.0046 70.45%, " +
  "1.0039 72.73%, 1.0033 75%, 1.0027 77.27%, 1.0022 79.55%, 1.0017 81.82%, 1.0014 84.09%, " +
  "1.001 86.36%, 1.0008 88.64%, 1 90.91%, 1 100%)";

type Row =
  | { kind: "sector"; sector: SectorInfo }
  | { kind: "stock"; hit: CompanyHit };

/** Wraps the part of `text` that matches `q` (case-insensitive) in an accent highlight. */
function Highlight({ text, q }: { text: string; q: string }) {
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <span style={{ background: "var(--accent-surface)", color: "var(--accent)" }}>{text.slice(i, i + q.length)}</span>
      {text.slice(i + q.length)}
    </>
  );
}

/**
 * Full-screen search, opened from the hero box: blurred backdrop, a centred panel with the input, a
 * "Browse Sectors" list while empty, and as you type sector matches first, then stocks (symbol and
 * industry shown). Arrow keys + Enter navigate, Esc or a backdrop click closes.
 */
export function SearchOverlay({
  sectors, origin, onClose, onSelectStock, onSelectSector,
}: {
  sectors: SectorInfo[];
  origin: DOMRect | null; // the search box it was opened from: the panel springs up out of it
  onClose: () => void;
  onSelectStock: (hit: CompanyHit) => void;
  onSelectSector: (name: string) => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [result, setResult] = useState<{ for: string; hits: CompanyHit[]; error: string } | null>(null);
  const hint = useTyped(HINTS);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closing = useRef(false);
  const query = q.trim();

  // Opening: backdrop fades in (250ms), the panel springs up from the search box (450ms) while fading in.
  useLayoutEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const panel = panelRef.current;
    const backdrop = backdropRef.current;
    if (!panel || !backdrop) return;
    // Effects can run twice (React strict mode in dev): drop any running animation first, otherwise the
    // second run would measure the panel mid-flight and compute a zero travel distance.
    panel.getAnimations().forEach((a) => a.cancel());
    backdrop.getAnimations().forEach((a) => a.cancel());
    backdrop.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 250, easing: "ease-out", fill: "both" });
    const final = panel.getBoundingClientRect();
    const dy = origin ? origin.top - final.top : 24;
    const dx = origin ? origin.left + origin.width / 2 - (final.left + final.width / 2) : 0;
    panel.animate(
      [
        { opacity: 0, transform: `translate(${dx}px, ${dy}px) scale(0.89, 0.93)` },
        { opacity: 1, transform: "translate(0, 0) scale(1, 1)" },
      ],
      { duration: 450, easing: SPRING, fill: "both" },
    );
  }, [origin]);

  // Closing: fade the backdrop and tuck the panel back up, then unmount.
  const close = () => {
    if (closing.current) return;
    closing.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return onClose();
    const done = [
      backdropRef.current?.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: "ease-in", fill: "both" }),
      panelRef.current?.animate(
        [{ opacity: 1, transform: "translateY(0) scale(1)" }, { opacity: 0, transform: "translateY(-10px) scale(0.98)" }],
        { duration: 200, easing: "ease-in", fill: "both" },
      ),
    ];
    Promise.all(done.map((a) => a?.finished)).then(onClose, onClose);
  };

  // lock page scroll behind the overlay
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  // debounced stock search
  useEffect(() => {
    if (!query) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      searchSymbols(query, ctrl.signal)
        .then((hits) => setResult({ for: query, hits, error: "" }))
        .catch((e: Error) => {
          if (e.name !== "AbortError") setResult({ for: query, hits: [], error: e.message });
        });
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query]);

  const rows = useMemo<Row[]>(() => {
    if (!query) return [];
    const lq = query.toLowerCase();
    const sec = sectors.filter((s) => s.name.toLowerCase().includes(lq)).slice(0, 4);
    const hits = result && result.for === query ? result.hits : [];
    return [...sec.map((sector): Row => ({ kind: "sector", sector })), ...hits.map((hit): Row => ({ kind: "stock", hit }))];
  }, [query, sectors, result]);

  const pending = !!query && (!result || result.for !== query);
  const error = result && result.for === query ? result.error : "";

  const choose = (r: Row) => (r.kind === "sector" ? onSelectSector(r.sector.name) : onSelectStock(r.hit));

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") return close();
    if (!rows.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(rows.length - 1, Math.max(0, active + (e.key === "ArrowDown" ? 1 : -1)));
      setActive(next);
      listRef.current?.querySelectorAll("button")[next]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(rows[Math.min(active, rows.length - 1)]);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[8vh]"
      onMouseDown={(e) => e.target === e.currentTarget && close()}
      role="dialog"
      aria-modal="true"
      aria-label="Search stocks and sectors"
    >
      <div
        ref={backdropRef}
        className="absolute inset-0"
        style={{ background: "var(--backdrop)", backdropFilter: "blur(6px)" }}
        onMouseDown={close}
      />
      <div ref={panelRef} className="relative w-full max-w-[700px] origin-top">
      <button
        type="button"
        onClick={close}
        aria-label="Close search"
        title="Close (Esc)"
        className="absolute -right-3 -top-3 z-10 flex h-7 w-7 items-center justify-center rounded-full text-white transition-transform duration-150 hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
        style={{ background: "#ef6c35", boxShadow: "0 4px 14px rgba(239, 108, 53, 0.45)" }}
      >
        <X className="h-4 w-4" strokeWidth={2.5} />
      </button>
      <div
        className="flex w-full flex-col overflow-hidden rounded-2xl border"
        style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-md)", maxHeight: "82vh" }}
      >
        <div className="flex items-center gap-3 border-b px-5 py-4" style={{ borderColor: "var(--border-subtle)" }}>
          <Search className="h-4 w-4 shrink-0" style={{ color: "var(--text-tertiary)" }} />
          <div className="relative flex-1">
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKey}
              aria-label="Search stocks or sectors"
              className="w-full bg-transparent text-[15px] outline-none"
            />
            {!q && (
              <span className="ov-hint pointer-events-none absolute inset-y-0 left-0 flex items-center text-[15px]" style={{ color: "var(--text-secondary)" }}>
                Search Stock or Sector :&nbsp;<em style={{ color: "var(--text-tertiary)" }}>{hint}</em>
              </span>
            )}
          </div>
        </div>

        <div ref={listRef} className="overflow-y-auto">
          {!query ? (
            <div className="ov-content p-5">
              <div className="mb-4 flex items-center gap-4">
                <div className="h-px flex-1" style={{ background: "var(--border-subtle)" }} />
                <span className="text-[10px] font-medium uppercase tracking-[0.18em]" style={{ color: "var(--text-tertiary)" }}>
                  Or search directly
                </span>
                <div className="h-px flex-1" style={{ background: "var(--border-subtle)" }} />
              </div>
              <h3 className="mb-3 text-base font-semibold">Browse Sectors</h3>
              <div className="ov-late flex flex-wrap gap-2">
                {sectors.map((s) => (
                  <button
                    key={s.name}
                    onClick={() => onSelectSector(s.name)}
                    className="rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors hover:border-[var(--accent-border)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)]"
                    style={{ background: "var(--surface-2, var(--surface-1))", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
                  >
                    {s.name}
                  </button>
                ))}
                {sectors.length === 0 && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading sectors…</span>}
              </div>
            </div>
          ) : rows.length > 0 ? (
            rows.map((r, i) => {
              const name = r.kind === "sector" ? r.sector.name : r.hit.name ?? r.hit.company_name ?? r.hit.symbol;
              const sub = r.kind === "sector" ? `${r.sector.count} stocks` : (r.hit.sector as string | null | undefined) ?? "";
              return (
                <button
                  key={r.kind === "sector" ? `s-${r.sector.name}` : `c-${r.hit.symbol}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(r)}
                  className="group flex w-full items-start gap-3 border-b px-5 py-3.5 text-left transition-colors duration-150 last:border-b-0"
                  style={{ borderColor: "var(--border-subtle)", background: i === active ? "var(--overlay)" : "transparent" }}
                >
                  <div className="min-w-0 flex-1">
                    <span className="mb-0.5 block text-[11px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{r.kind}</span>
                    <div className="flex items-center gap-2">
                      <span className="truncate"><Highlight text={name} q={query} /></span>
                      {r.kind === "stock" && (
                        <span className="shrink-0 text-sm" style={{ color: "var(--text-tertiary)" }}><Highlight text={r.hit.symbol} q={query} /></span>
                      )}
                      <ArrowUpRight className="h-4 w-4 shrink-0 opacity-70 transition-opacity group-hover:opacity-100" style={{ color: "var(--gold)" }} />
                    </div>
                    {sub && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{sub}</span>}
                  </div>
                </button>
              );
            })
          ) : (
            <div className="px-5 py-10 text-center text-sm" style={{ color: error ? "#f5a9a9" : "var(--text-tertiary)" }}>
              {error ? `Search failed: ${error}` : pending ? "Searching…" : `No stocks or sectors match “${query}”.`}
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
