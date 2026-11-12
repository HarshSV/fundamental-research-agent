"use client";

import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { openSearch } from "./searchEvents";
import { TYPED_PHRASES } from "./data";
import type { CatalogueEntry } from "./patterns";
import { useTyped } from "./typing";

const LONGEST_PHRASE = TYPED_PHRASES.reduce((a, b) => (b.length > a.length ? b : a), "");
/** The chips shown first on the landing page; the rest sit behind "More". The first four are the only patterns with a measured, if small,
 *  average gain after costs (docs/PATTERN_STUDY.md, 100,541 past confirmations); the other six are well known and positive on average but not
 *  proven. The bearish patterns showed no selling edge in that study, so they are behind "More". */
const TOP_PATTERNS = [
  "pocket-pivot", "order-block", "falling-wedge", "undercut-and-rally",
  "cup-and-handle", "vcp", "double-bottom",
  "head-and-shoulders", "double-top",                      // well-known bearish ones, so the row shows both directions
];
const BOX_HINTS =["IT Services", "Banks", "Pharmaceuticals", "Tata Steel"];

export function Hero({ patterns, patternsError, onPattern }: { patterns: CatalogueEntry[]; patternsError: string; onPattern: (id: string) => void }) {
  const typed = useTyped(TYPED_PHRASES);
  const hint = useTyped(BOX_HINTS);
  // "closed" -> "open" (the rest rise in) -> "closing" (they sink out, last first) -> "closed"
  const [phase, setPhase] = useState<"closed" | "open" | "closing">("closed");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const toggle = () => {
    if (timer.current) clearTimeout(timer.current);
    if (phase === "open") {
      setPhase("closing");
      timer.current = setTimeout(() => setPhase("closed"), 760);
    } else {
      setPhase("open");
    }
  };
  // the first ten in their set order, then (after "More") the rest in catalogue order
  const first = TOP_PATTERNS.map((id) => patterns.find((p) => p.id === id)).filter((p): p is CatalogueEntry => Boolean(p));
  const rest = patterns.filter((p) => !TOP_PATTERNS.includes(p.id));
  const ordered = phase === "closed" ? first : [...first, ...rest];

  return (
    <div
      className="relative overflow-hidden border-b"
      style={{ background: "var(--surface-0)", borderColor: "var(--border-default)" }}
    >
      <div className="pointer-events-none absolute left-1/4 top-0 h-96 w-96 rounded-full blur-3xl" style={{ background: "#635ec80d" }} />
      <div className="pointer-events-none absolute right-1/4 top-20 h-80 w-80 rounded-full blur-3xl" style={{ background: "#b7b4e70d" }} />
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: "linear-gradient(180deg, var(--accent-surface) 0%, transparent 60%)" }}
      />
      <div className="relative mx-auto max-w-4xl px-4 pb-12 pt-16 text-center">
        <h1 className="mb-4 text-4xl font-bold leading-[1.15] tracking-tight lg:text-5xl">
          <span className="brand-font">NAVRIST AI.</span>{" "}
          {/* The longest phrase is laid out invisibly in the same grid cell, so the headline keeps one fixed size and
              wrapping while the phrase types and deletes (otherwise the search box below jumps up and down). */}
          <span className="inline-grid text-left" style={{ color: "var(--accent)" }}>
            <span aria-hidden="true" className="invisible col-start-1 row-start-1">
              {LONGEST_PHRASE}
              <span className="ml-0.5 inline-block w-[3px]" />
            </span>
            <span className="col-start-1 row-start-1">
              {typed}
              <span
                className="ml-0.5 inline-block h-[0.9em] w-[3px] animate-pulse align-middle"
                style={{ background: "var(--accent)" }}
              />
            </span>
          </span>
        </h1>
        <p className="mx-auto mb-10 max-w-2xl text-lg" style={{ color: "var(--text-secondary)" }}>
          Advanced stock screening powered by NSE Market data.
          <br />
          Explore 2000+ equity stocks with customizable filters and market analytics.
        </p>

        {/* The box is the trigger: it opens the full-screen search. */}
        <div className="relative mx-auto mb-10 w-full max-w-2xl">
          <div className="relative flex items-center">
            <Search className="pointer-events-none absolute left-5 z-[2] h-5 w-5" style={{ color: "var(--text-tertiary)" }} />
            <div className="search-glow w-full">
              <button
                id="navrist-search"
                type="button"
                onClick={(e) => openSearch(e.currentTarget)}
                aria-label="Search stocks or sectors"
                className="flex h-14 w-full cursor-text items-center rounded-[10.5px] pl-[3.25rem] pr-4 text-left text-[13px] sm:pr-32 sm:text-[15px]"
                style={{ background: "var(--surface-1)", color: "var(--text-tertiary)" }}
              >
                <span className="min-w-0 truncate whitespace-nowrap">
                  <span className="hidden sm:inline">Search Equity Stocks or Sector :&nbsp;</span>
                  <span className="sm:hidden">Search :&nbsp;</span>
                  {hint}
                </span>
              </button>
            </div>
          </div>
        </div>

        <div id="navrist-patterns" className="mb-4 scroll-mt-28 text-xs" style={{ color: "var(--text-tertiary)" }}>
          Browse by pattern
        </div>
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-5">
          {ordered.map((p, i) => (
            <div
              key={p.id}
              className={i >= first.length ? (phase === "closing" ? "chip-out" : "chip-in") : undefined}
              style={i >= first.length ? { animationDelay: `${phase === "closing" ? Math.min((ordered.length - 1 - i) * 22, 400) : Math.min((i - first.length) * 40, 600)}ms` } : undefined}
            >
              <span className={`pat-glow pat-glow-${p.bias ?? "both"} w-full`} style={{ ["--pat-delay" as string]: `${-((i * 0.7) % 4.5)}s` }}>
                <button
                  onClick={() => onPattern(p.id)}
                  title={`${p.category}${p.bias ? ` · ${p.bias === "both" ? "direction depends on the structure" : p.bias}` : ""}: ${p.definition}`}
                  className="flex min-h-[40px] w-full items-center justify-center rounded-full px-3 py-1.5 text-center text-xs leading-tight transition-colors duration-200 hover:bg-[var(--overlay)] hover:text-[var(--text-primary)]"
                  style={{ background: "var(--surface-1)", color: "var(--text-secondary)" }}
                >
                  {p.name}
                </button>
              </span>
            </div>
          ))}
          {patterns.length > TOP_PATTERNS.length && (
            <button
              type="button"
              onClick={toggle}
              aria-expanded={phase === "open"}
              className="flex min-h-[40px] w-full items-center justify-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-[var(--overlay)]"
              style={{ color: "var(--accent)", border: "1px dashed var(--border-default)" }}
            >
              {phase === "open" ? "Less" : `More (${rest.length})`}
            </button>
          )}
          {patterns.length === 0 && !patternsError && <span className="col-span-full text-xs" style={{ color: "var(--text-tertiary)" }}>Loading patterns…</span>}
          {patternsError && <span className="col-span-full text-xs" style={{ color: "#f5a9a9" }}>Could not load patterns: {patternsError}</span>}
        </div>
      </div>

    </div>
  );
}
