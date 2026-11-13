"use client";

import { BarChart3, ChevronDown, Menu, Moon, Search, SlidersHorizontal, Star, Sun, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { SlidingTabs } from "./controls";
import { OPEN_SCREENER_EVENT, openSearch } from "./searchEvents";
import { fetchCatalogue } from "./patterns";
import { navigateTo, type FeedName } from "./scanners";
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

interface Item {
  label: string;
  hint?: string;
  /** A chart pattern's direction: its row is shaded green (bullish), red (bearish) or grey (either way), as on the home page. */
  bias?: "bullish" | "bearish" | "both";
  run: () => void;
}

const BIAS_STYLE = {
  bullish: { color: "#10b981", bg: "rgba(16,185,129,.14)", label: "Bullish" },
  bearish: { color: "#ef4444", bg: "rgba(239,68,68,.14)", label: "Bearish" },
  both: { color: "#9ca3af", bg: "rgba(156,163,175,.16)", label: "Either direction" },
} as const;
const biasStyle = (it: Item): CSSProperties | undefined =>
  it.bias ? { background: BIAS_STYLE[it.bias].bg, borderLeft: `3px solid ${BIAS_STYLE[it.bias].color}` } : undefined;
interface Group {
  title: string;
  items: Item[];
}
interface Menu {
  id: string;
  label: string;
  groups: Group[];
}

const scanner = (id: string) => () => navigateTo({ type: "scanner", id });
const feed = (name: FeedName, kind?: "bulk" | "block") => () => navigateTo({ type: "feed", name, kind });
const analytics = (tab: "sectors" | "history" | "outlook" | "industries" | "rrg" | "breadth") => () => navigateTo({ type: "analytics", tab });

/** The top menu, in the order a trader works: build a scan, find a setup, check volume and gaps, then the market as a whole. */
const MENUS: Menu[] = [
  {
    id: "screeners",
    label: "Screeners",
    groups: [
      {
        title: "Build",
        items: [
          { label: "Create Screener", hint: "Your own rules: technicals, patterns, fundamentals", run: () => window.dispatchEvent(new Event(OPEN_SCREENER_EVENT)) },
          { label: "Multiple Scans", hint: "Stocks that appear in all the scanners you pick", run: () => navigateTo({ type: "multi" }) },
          { label: "Horizontal Resistance", hint: "Price pressing on a level three highs have touched", run: scanner("horizontal-resistance") },
          { label: "Patterns on the Home Page", hint: "The pattern chips, with the screens behind them", run: () => navigateTo({ type: "home", scroll: "patterns" }) },
        ],
      },
      {
        title: "Setups",
        items: [
          { label: "Tight Setup · daily", run: scanner("tight-setup") },
          { label: "Tight Setup · weekly", run: scanner("tight-setup-weekly") },
          { label: "Inside Bar · daily", run: scanner("inside-bar") },
          { label: "Inside Bar · weekly", run: scanner("inside-bar-weekly") },
          { label: "Filtered Inside Bar · daily", run: scanner("inside-bar-filtered") },
          { label: "Filtered Inside Bar · weekly", run: scanner("inside-bar-weekly-filtered") },
        ],
      },
      {
        title: "Volume and gaps",
        items: [
          { label: "Volume Gainers", run: scanner("volume-gainers") },
          { label: "High Volume Stocks", run: scanner("high-volume") },
          { label: "Gap Up", run: scanner("gap-up") },
          { label: "Gap Filling", run: scanner("gap-filling") },
        ],
      },
      {
        title: "Strength and weakness",
        items: [
          { label: "Momentum", run: scanner("momentum") },
          { label: "RS High Before Price High", run: scanner("rs-high-before-price-high") },
          { label: "Shorting Scanner", run: scanner("shorting") },
        ],
      },
      {
        title: "Earnings and IPOs",
        items: [
          { label: "Earnings Gap Up · latest quarter", run: scanner("earnings-gap-up") },
          { label: "Earnings Gap Up · previous", run: scanner("earnings-gap-up-prev") },
          { label: "Positive Earnings Reaction · latest", run: scanner("positive-earnings-reaction") },
          { label: "Positive Earnings Reaction · previous", run: scanner("positive-earnings-reaction-prev") },
          { label: "IPO Setups", run: scanner("ipo-setups") },
        ],
      },
    ],
  },
  {
    id: "analytics",
    label: "Market Analytics",
    groups: [
      {
        title: "Top down",
        items: [
          { label: "Sector Analytics", hint: "Which sectors lead and lag", run: analytics("sectors") },
          { label: "Sector History", hint: "Each sector since about 1996: years, falls, seasons", run: analytics("history") },
          { label: "Sector Outlook", hint: "Odds for the next 1 and 3 months, with the facts", run: analytics("outlook") },
          { label: "Industry Analytics", hint: "The strongest industry groups", run: analytics("industries") },
          { label: "RRG", hint: "Sector rotation across four quadrants", run: analytics("rrg") },
          { label: "Market Breadth", hint: "How many stocks take part in the move", run: analytics("breadth") },
          { label: "Sector Indices", hint: "Every NSE index today", run: feed("sector-indices") },
        ],
      },
      {
        title: "Movers",
        items: [
          { label: "Top Gainers", run: scanner("top-gainers") },
          { label: "Top Losers", run: scanner("top-losers") },
        ],
      },
    ],
  },
];

/** Top-level links without a dropdown, as on ChartsMaze: the watchlist (the trade journal link was removed for now) */
const DIRECT: { label: string; icon: typeof Star; run: () => void }[] = [
  { label: "Watchlist", icon: Star, run: () => navigateTo({ type: "watchlist" }) },
];

function NavMenu({ menu, open, onToggle, onPick }: { menu: Menu; open: boolean; onToggle: () => void; onPick: (i: Item) => void }) {
  const [active, setActive] = useState(0);
  return (
    <div className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={onToggle}
        className="flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-colors hover:bg-[var(--overlay)]"
        style={{ color: "var(--text-primary)", background: open ? "var(--overlay)" : undefined }}
      >
        {menu.label}
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div
          role="menu"
          className="menu-panel absolute left-0 top-full z-[60] mt-2 grid gap-x-8 gap-y-4 rounded-2xl border p-5"
          style={{
            background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "0 20px 50px rgba(0,0,0,.35)",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", width: menu.groups.length >= 3 ? "min(520px, calc(100vw - 32px))" : `min(${menu.groups.length * 210}px, calc(100vw - 32px))`,
          }}
        >
          {menu.groups.length >= 3 ? (
            <div className="flex gap-4" style={{ gridColumn: "1 / -1" }}>
              <div className="w-44 shrink-0 space-y-0.5 border-r pr-3" style={{ borderColor: "var(--border-default)" }}>
                {menu.groups.map((g, i) => (
                  <button
                    key={g.title}
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onFocus={() => setActive(i)}
                    onClick={() => setActive(i)}
                    className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-sm font-semibold transition-colors"
                    style={{ color: i === active ? "var(--accent)" : "var(--text-primary)", background: i === active ? "var(--overlay)" : undefined }}
                  >
                    {g.title}
                  </button>
                ))}
              </div>
              <ul className="min-w-0 flex-1 space-y-0.5 overflow-y-auto pr-1" style={{ maxHeight: "min(62vh, 440px)" }}>
                {menu.groups[Math.min(active, menu.groups.length - 1)].items.map((it) => (
                  <li key={it.label}>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => onPick(it)}
                      className="block w-full rounded-lg px-2.5 py-2 text-left text-sm transition-colors hover:bg-[var(--overlay-weak)] hover:text-[var(--accent)]"
                      style={{ color: "var(--text-primary)", ...biasStyle(it) }}
                      title={it.bias ? BIAS_STYLE[it.bias].label : undefined}
                    >
                      {it.label}
                      {it.hint && <span className="mt-0.5 block text-[11px] font-normal leading-snug" style={{ color: "var(--text-tertiary)" }}>{it.hint}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : menu.groups.map((g) => (
            <div key={g.title}>
              <div className="menu-heading text-[11px] uppercase">{g.title}</div>
              <ul className="space-y-0.5">
                {g.items.map((it) => (
                  <li key={it.label}>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => onPick(it)}
                      className="block w-full rounded-lg px-2.5 py-2 text-left text-sm transition-colors hover:bg-[var(--overlay-weak)] hover:text-[var(--accent)]"
                      style={{ color: "var(--text-primary)", ...biasStyle(it) }}
                      title={it.bias ? BIAS_STYLE[it.bias].label : undefined}
                    >
                      {it.label}
                      {it.hint && <span className="mt-0.5 block text-[11px] font-normal leading-snug" style={{ color: "var(--text-tertiary)" }}>{it.hint}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Header() {
  const light = useSyncExternalStore(subscribe, isLight, () => false);
  const [menu, setMenu] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  // the drawer stays mounted for the length of its slide-out animation
  const [drawerMounted, setDrawerMounted] = useState(false);
  useEffect(() => {
    if (drawer) {
      setDrawerMounted(true);
      return;
    }
    const t = setTimeout(() => setDrawerMounted(false), 350);
    return () => clearTimeout(t);
  }, [drawer]);
  const [section, setSection] = useState<string | null>("screeners");
  // every chart pattern, shaded by direction, as a group of the Screeners menu; each opens that pattern's scan
  const [patternItems, setPatternItems] = useState<Item[]>([]);
  useEffect(() => {
    let alive = true;
    fetchCatalogue()
      .then((cat) => {
        if (!alive) return;
        const rank = { bullish: 0, bearish: 1, both: 2 } as const;
        setPatternItems(
          Object.values(cat)
            .map((p): Item => ({ label: p.name, bias: p.bias ?? "both", run: () => navigateTo({ type: "scanner", id: p.id }) }))
            .sort((a, b) => rank[a.bias ?? "both"] - rank[b.bias ?? "both"] || a.label.localeCompare(b.label)),
        );
      })
      .catch(() => { /* the menu simply has no pattern list until the catalogue loads */ });
    return () => { alive = false; };
  }, []);
  const menus = useMemo(
    () => MENUS.map((m) => (m.id === "screeners" && patternItems.length ? { ...m, groups: [...m.groups, { title: "Chart Patterns", items: patternItems }] } : m)),
    [patternItems],
  );
  const bar = useRef<HTMLDivElement>(null);

  const pick = useCallback((it: Item) => {
    setMenu(null);
    setDrawer(false);
    it.run();
  }, []);

  // the open dropdown closes on a click elsewhere or Escape; the drawer on Escape; the page behind the drawer does not scroll
  useEffect(() => {
    const click = (e: MouseEvent) => {
      if (menu && bar.current && !bar.current.contains(e.target as Node)) setMenu(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu(null);
        setDrawer(false);
      }
    };
    document.addEventListener("mousedown", click);
    window.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", click);
      window.removeEventListener("keydown", key);
    };
  }, [menu]);
  useEffect(() => {
    if (!drawer) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawer]);

  const themeTabs = (
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
  );

  return (
    <>
      {/* index ticker: a slim strip above the header; it scrolls away, the header below stays pinned */}
      <Ticker />
      <header className="sticky top-0 z-50 border-b backdrop-blur-xl" style={{ background: "var(--bar-bg)", borderColor: "var(--bar-border)" }}>
        <div ref={bar} className="mx-auto flex max-w-7xl items-center gap-1.5 px-2 py-2 sm:gap-3 sm:px-4 sm:py-2.5">
          {/* mobile: menu button on the left */}
          <button
            type="button"
            aria-label="Open menu"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-[var(--overlay-weak)] lg:hidden"
            style={{ color: "var(--text-primary)" }}
          >
            <Menu className="h-5 w-5" />
          </button>
          {/* Brand: clickable, goes back to the home screen (a full load resets any open stock). */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full load is intended: it resets the open stock */}
          <a
            href="/"
            aria-label="NAVRIST AI home"
            className="flex min-w-0 shrink-0 items-center gap-2 rounded-lg outline-none transition-transform hover:scale-[1.01] focus-visible:ring-2 focus-visible:ring-[var(--btn-primary-bg)] sm:gap-3"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/sites/marketlens/navrist-logo.svg" alt="" className="ml-logo h-8 w-8 shrink-0 rounded-lg sm:h-10 sm:w-10" />
            <span className="brand-wordmark whitespace-nowrap text-[17px] font-extrabold leading-none min-[380px]:text-[19px] sm:text-[24px]">NAVRIST AI</span>
            <span className="hidden h-8 w-px xl:block" style={{ background: "var(--border-default)" }} aria-hidden="true" />
            <span className="hidden text-[11px] font-semibold uppercase leading-[1.25] tracking-[0.14em] xl:block" style={{ color: "var(--text-secondary)" }}>
              Research
              <br />
              Terminal
            </span>
          </a>
          {/* desktop: the top menu, just beside the logo */}
          <nav className="ml-2 hidden items-center gap-1 lg:flex" aria-label="Main">
            {menus.map((m) => (
              <NavMenu key={m.id} menu={m} open={menu === m.id} onToggle={() => setMenu((x) => (x === m.id ? null : m.id))} onPick={pick} />
            ))}
            {DIRECT.map((d) => (
              <button key={d.label} type="button" onClick={() => { setMenu(null); d.run(); }} className="flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-colors hover:bg-[var(--overlay)]" style={{ color: "var(--text-primary)" }}>
                <d.icon className="h-4 w-4" /> {d.label}
              </button>
            ))}
          </nav>
          <div className="min-w-0 flex-1" />
          {/* search: opens the full-screen search; hidden on the home view, where the hero has the big box */}
          <button
            type="button"
            onClick={(e) => openSearch(e.currentTarget)}
            aria-label="Search equity stocks or sectors"
            className="hdr-search hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border transition-colors hover:border-[var(--accent-border)] md:flex xl:w-[260px] xl:justify-start xl:gap-2.5 xl:px-4"
            style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", color: "var(--text-tertiary)" }}
          >
            <Search className="h-4 w-4 shrink-0" />
            <span className="hidden truncate text-sm xl:inline">Search stocks, sectors…</span>
          </button>
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-3">
            <div>{themeTabs}</div>
          </div>
        </div>
      </header>

      {/* mobile drawer: slides in from the left; Create Screener stays in the bar */}
      {drawerMounted && (
        <div className="fixed inset-0 z-[70] lg:hidden" role="dialog" aria-modal="true" aria-label="Menu" style={{ pointerEvents: drawer ? undefined : "none" }}>
          <div className="drawer-backdrop absolute inset-0" data-closing={!drawer} style={{ background: "var(--backdrop)", backdropFilter: "blur(4px)" }} onMouseDown={() => setDrawer(false)} />
          <aside data-closing={!drawer} className="drawer-panel absolute inset-y-0 left-0 flex w-[86%] max-w-[340px] flex-col border-r" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
            <div className="flex items-center justify-between border-b px-4 py-3" style={{ background: "var(--bar-bg)", borderColor: "var(--bar-border)" }}>
              <span className="text-lg font-extrabold tracking-wide" style={{ color: "#ffffff" }}>NAVRIST AI</span>
              <button type="button" aria-label="Close menu" onClick={() => setDrawer(false)} className="flex h-10 w-10 items-center justify-center rounded-lg text-white hover:bg-white/15">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="drawer-body flex-1 overflow-y-auto px-3 py-3">
              <button
                type="button"
                onClick={() => {
                  setDrawer(false);
                  openSearch(null);
                }}
                className="mb-3 flex min-h-[44px] w-full items-center gap-2.5 rounded-xl border px-3 text-left text-sm"
                style={{ background: "var(--surface-2, var(--surface-1))", borderColor: "var(--border-default)", color: "var(--text-tertiary)" }}
              >
                <Search className="h-4 w-4" /> Search stocks, sectors…
              </button>
              {DIRECT.map((d) => (
                <button key={d.label} type="button" onClick={() => { setDrawer(false); d.run(); }} className="mb-1 flex min-h-[48px] w-full items-center gap-2.5 rounded-lg border px-3 text-left text-[15px] font-semibold" style={{ color: "var(--text-primary)", background: "var(--overlay-weak)", borderColor: "var(--border-subtle)" }}>
                  <d.icon className="h-4 w-4" style={{ color: "var(--accent)" }} /> {d.label}
                </button>
              ))}
              {menus.map((m) => (
                <div key={m.id} className="mb-1">
                  <button
                    type="button"
                    aria-expanded={section === m.id}
                    onClick={() => setSection((s) => (s === m.id ? null : m.id))}
                    className="flex min-h-[48px] w-full items-center justify-between rounded-lg border px-3 text-left text-[15px] font-semibold"
                    style={{ color: "var(--text-primary)", background: section === m.id ? "var(--accent-surface)" : "var(--overlay-weak)", borderColor: section === m.id ? "var(--accent-border)" : "var(--border-subtle)" }}
                  >
                    <span className="flex items-center gap-2.5">{m.id === "analytics" ? <BarChart3 className="h-4 w-4" style={{ color: "var(--accent)" }} /> : <SlidersHorizontal className="h-4 w-4" style={{ color: "var(--accent)" }} />}{m.label}</span>
                    <ChevronDown className={`h-4 w-4 transition-transform ${section === m.id ? "rotate-180" : ""}`} />
                  </button>
                  {section === m.id && (
                    <div className="pb-2 pl-3">
                      {m.groups.map((g) => (
                        <div key={g.title} className="mb-1">
                          <div className="menu-heading mx-3 mt-2 text-[11px] uppercase">{g.title}</div>
                          {g.items.map((it) => (
                            <button key={it.label} type="button" onClick={() => pick(it)} className="flex min-h-[44px] w-full items-center rounded-lg px-3 text-left text-sm hover:bg-[var(--overlay-weak)]" style={{ color: "var(--text-secondary)", ...biasStyle(it) }}>
                              {it.label}
                            </button>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between border-t px-4 py-3" style={{ borderColor: "var(--border-subtle)" }}>
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Theme</span>
              {themeTabs}
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
