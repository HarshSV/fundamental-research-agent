"use client";

import { Search } from "lucide-react";
import { openSearch } from "./searchEvents";
import { TYPED_PHRASES } from "./data";
import type { CatalogueEntry } from "./patterns";
import { useTyped } from "./typing";

const BOX_HINTS = ["IT Services", "Banks", "Pharmaceuticals", "Tata Steel"];

export function Hero({ patterns, patternsError, onPattern }: { patterns: CatalogueEntry[]; patternsError: string; onPattern: (id: string) => void }) {
  const typed = useTyped(TYPED_PHRASES);
  const hint = useTyped(BOX_HINTS);

  return (
    <div
      className="relative overflow-hidden border-b"
      style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}
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
          <span style={{ color: "var(--accent)" }}>
            {typed}
            <span
              className="ml-0.5 inline-block h-[0.9em] w-[3px] animate-pulse align-middle"
              style={{ background: "var(--accent)" }}
            />
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
                className="flex h-14 w-full cursor-text items-center rounded-[10.5px] pl-[3.25rem] pr-32 text-left text-[15px]"
                style={{ background: "var(--surface-1)", color: "var(--text-tertiary)" }}
              >
                Search Equity Stocks or Sector :&nbsp;{hint}
              </button>
            </div>
          </div>
        </div>

        <div className="mb-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
          Browse by pattern
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {patterns.map((p) => (
            <button
              key={p.id}
              onClick={() => onPattern(p.id)}
              title={`${p.category}: ${p.definition}`}
              className="rounded-full border px-3.5 py-1.5 text-xs transition-all duration-200 hover:border-[var(--accent-border)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)]"
              style={{
                background: "var(--surface-1)",
                borderColor: "var(--border-default)",
                color: "var(--text-secondary)",
              }}
            >
              {p.name}
            </button>
          ))}
          {patterns.length === 0 && !patternsError && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading patterns…</span>}
          {patternsError && <span className="text-xs" style={{ color: "#f5a9a9" }}>Could not load patterns: {patternsError}</span>}
        </div>
      </div>

    </div>
  );
}
