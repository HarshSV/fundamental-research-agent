"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { openSearch } from "./searchEvents";
import { TYPED_PHRASES } from "./data";
import type { CatalogueEntry } from "./patterns";
import { useTyped } from "./typing";

const LONGEST_PHRASE = TYPED_PHRASES.reduce((a, b) => (b.length > a.length ? b : a), "");
/** The chips shown first on the landing page (5 bullish, 3 bearish, 2 either way); the rest sit behind "More". */
const TOP_PATTERNS = [
  "cup-and-handle", "vcp", "head-and-shoulders", "double-bottom", "symmetrical-triangle",
  "double-top", "ascending-triangle", "inverse-head-and-shoulders", "descending-triangle", "rectangle",
];
const BOX_HINTS =["IT Services", "Banks", "Pharmaceuticals", "Tata Steel"];

export function Hero({ patterns, patternsError, onPattern }: { patterns: CatalogueEntry[]; patternsError: string; onPattern: (id: string) => void }) {
  const typed = useTyped(TYPED_PHRASES);
  const hint = useTyped(BOX_HINTS);
  const [more, setMore] = useState(false);

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
          NAVRIST AI.{" "}
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
        <div className="flex flex-wrap justify-center gap-2.5">
          {(more ? patterns : patterns.filter((p) => TOP_PATTERNS.includes(p.id)).sort((a, b) => TOP_PATTERNS.indexOf(a.id) - TOP_PATTERNS.indexOf(b.id))).map((p, i) => (
            <span key={p.id} className={`pat-glow pat-glow-${p.bias ?? "both"}`} style={{ ["--pat-delay" as string]: `${-((i * 0.7) % 4.5)}s` }}>
              <button
                onClick={() => onPattern(p.id)}
                title={`${p.category}${p.bias ? ` · ${p.bias === "both" ? "direction depends on the structure" : p.bias}` : ""}: ${p.definition}`}
                className="rounded-full px-3.5 py-2.5 text-xs transition-colors sm:py-1.5 duration-200 hover:bg-[var(--overlay)] hover:text-[var(--text-primary)]"
                style={{ background: "var(--surface-1)", color: "var(--text-secondary)" }}
              >
                {p.name}
              </button>
            </span>
          ))}
          {patterns.length > TOP_PATTERNS.length && (
            <button
              type="button"
              onClick={() => setMore((v) => !v)}
              aria-expanded={more}
              className="rounded-full px-3 py-2.5 text-xs font-semibold transition-colors sm:py-1.5 hover:bg-[var(--overlay)]"
              style={{ color: "var(--accent)" }}
            >
              {more ? "Less" : "More"}
            </button>
          )}
          {patterns.length === 0 && !patternsError && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading patterns…</span>}
          {patternsError && <span className="text-xs" style={{ color: "#f5a9a9" }}>Could not load patterns: {patternsError}</span>}
        </div>
      </div>

    </div>
  );
}
