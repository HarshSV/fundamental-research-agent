"use client";

import { Moon, Plus, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { Ticker } from "./Ticker";

export const THEME_KEY = "navrist_theme";
export const NEW_SCREEN_EVENT = "navrist-new-screen";
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
            className="flex min-w-0 items-center gap-3 rounded-lg outline-none transition-transform hover:scale-[1.01] focus-visible:ring-2 focus-visible:ring-[var(--btn-primary-bg)] sm:gap-4"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/sites/marketlens/navrist-logo.svg" alt="" className="h-11 w-11 shrink-0 rounded-xl sm:h-12 sm:w-12" />
            <span className="brand-wordmark text-[26px] font-extrabold leading-none sm:text-[30px]">NAVRIST AI</span>
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
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={light ? "Switch to dark mode" : "Switch to light mode"}
              aria-pressed={light}
              title={light ? "Switch to dark mode" : "Switch to light mode"}
              className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:text-[var(--accent)]"
              style={{ background: "var(--overlay)", color: "var(--text-secondary)" }}
            >
              {light ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event(NEW_SCREEN_EVENT))}
              title="Start a new screen: search a stock or a sector"
              className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-white transition-colors hover:bg-[var(--btn-primary-hover)] sm:px-5"
              style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
            >
              <Plus className="h-4 w-4" />
              <span>New Screen</span>
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
