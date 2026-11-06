"use client";

import { Moon, Search, SlidersHorizontal, Sun, TrendingUp } from "lucide-react";
import { useSyncExternalStore } from "react";
import { SlidingTabs } from "./controls";
import { OPEN_RESISTANCE_EVENT, OPEN_SCREENER_EVENT, openSearch } from "./searchEvents";
import { Ticker } from "./Ticker";

export const THEME_KEY = "navrist_theme";
const THEME_EVENT = "navrist-theme-change";

// The <html class="light"> flag is the single source of truth (set before paint by the inline script in
// layout.tsx, so there is no flash); this subscribes React to it.
const subscribe = (cb: () => void) => {
  window.addEventListener(THEME_EVENT, cb);
  return () => window.removeEventListener(THEME_EVENT, cb);
};
const isLight = () => document.documentElement.classList.contains("light");

function toggleTheme() {
  const next = !isLight();
  document.documentElement.classList.toggle("light", next);
  try {
    localStorage.setItem(THEME_KEY, next ? "light" : "dark");
  } catch {
    /* storage unavailable: the choice just won't persist */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function Header() {
  const light = useSyncExternalStore(subscribe, isLight, () => false);
  return (
    <>
      {/* index ticker: its own bar above the header; it scrolls away, the header below stays pinned */}
      <Ticker />
      <header
        className="sticky top-0 z-50 border-b backdrop-blur-xl"
        style={{ background: "var(--glass-bg)", borderColor: "var(--border-subtle)" }}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-3 sm:px-4 sm:py-4">
          {/* Brand block: clickable, goes back to the home screen (a full load resets any open stock). */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full load is intended: it resets the open stock */}
          <a
            href="/"
            aria-label="NAVRIST AI — home"
            className="flex min-w-0 items-center rounded-lg outline-none transition-transform hover:scale-[1.01] focus-visible:ring-2 focus-visible:ring-[var(--btn-primary-bg)] gap-2 sm:gap-4"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/sites/marketlens/navrist-logo.svg" alt="" className="h-9 w-9 shrink-0 rounded-xl sm:h-12 sm:w-12" />
            <span className="brand-wordmark whitespace-nowrap text-[19px] font-extrabold leading-none sm:text-[30px]">NAVRIST AI</span>
            <span className="hidden h-9 w-px sm:block" style={{ background: "var(--border-default)" }} aria-hidden="true" />
            <span
              className="hidden text-[12px] font-semibold uppercase leading-[1.25] tracking-[0.14em] sm:block"
              style={{ color: "var(--text-secondary)" }}
            >
              Research
              <br />
              Terminal
            </span>
          </a>
          {/* search bar (as on the exchange's stock page): opens the same full-screen search; hidden on the home view */}
          <button
            type="button"
            onClick={(e) => openSearch(e.currentTarget)}
            aria-label="Search equity stocks or sectors"
            className="hdr-search hidden min-w-0 max-w-[360px] flex-1 items-center gap-2.5 rounded-xl border px-4 py-2.5 text-left text-sm transition-colors hover:border-[var(--accent-border)] md:flex"
            style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", color: "var(--text-tertiary)" }}
          >
            <Search className="h-4 w-4 shrink-0" />
            <span className="truncate">Search equity stocks , sectors ....</span>
          </button>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <SlidingTabs
              ariaLabel="Colour theme"
              size="icon"
              value={light ? "light" : "dark"}
              onChange={(t) => {
                if ((t === "light") !== light) toggleTheme();
              }}
              options={[
                { id: "dark", label: <Moon className="h-4 w-4" />, title: "Dark mode" },
                { id: "light", label: <Sun className="h-4 w-4" />, title: "Light mode" },
              ]}
            />
            <button
              type="button"
              aria-label="Horizontal Resistance scanner"
              onClick={() => window.dispatchEvent(new Event(OPEN_RESISTANCE_EVENT))}
              title="Horizontal Resistance: stocks pressing on a price level that at least three highs have touched"
              className="flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm transition-colors hover:border-[var(--accent-border)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)] sm:py-2"
              style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-1)" }}
            >
              <TrendingUp className="h-4 w-4" />
              <span className="hidden lg:inline">Horizontal Resistance</span>
            </button>
            <button
              type="button"
              aria-label="Create Screener"
              onClick={() => window.dispatchEvent(new Event(OPEN_SCREENER_EVENT))}
              title="Create a screener: filter every stock by technicals, fundamentals and horizontal resistance"
              className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-white transition-colors hover:bg-[var(--btn-primary-hover)] sm:px-5"
              style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span className="hidden sm:inline">Create Screener</span>
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
