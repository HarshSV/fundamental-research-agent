"use client";

import { useCallback, useEffect, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import { NEW_SCREEN_EVENT } from "./Header";
import { OPEN_SEARCH_EVENT } from "./searchEvents";
import { SearchOverlay } from "./SearchOverlay";
import { Hero } from "./Hero";
import { PatternFilterModal } from "./PatternFilterModal";
import { PatternScanPage } from "./PatternScanPage";
import { fetchCatalogue, type CatalogueEntry } from "./patterns";
import { EMPTY_FILTERS, fetchScanOptions, type ScanFilters, type ScanOptions } from "./patternScan";
import { PopularScreens } from "./PopularScreens";
import {
  fetchScreen, fetchSector, fetchSectors, type ScreenResult, type SectorInfo, type SectorResult,
} from "./screens";
import { StockList } from "./StockList";
import { StockView } from "./StockView";

export const SEARCH_INPUT_ID = "navrist-search";

type View =
  | { kind: "home" }
  | { kind: "stock"; stock: CompanyHit }
  | { kind: "patternScan"; pattern: string; filters: ScanFilters }
  | { kind: "sector"; name: string }
  | { kind: "screen"; id: string };

/** A sector page: every company NSE classifies in that sector. */
function SectorPage({ name, onBack, onSelect }: { name: string; onBack: () => void; onSelect: (s: CompanyHit) => void }) {
  const [res, setRes] = useState<SectorResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    fetchSector(name).then((r) => alive && setRes(r)).catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [name]);
  return (
    <StockList
      title={name}
      description={res ? `${res.count} companies in this sector (NSE classification).` : undefined}
      stocks={res?.stocks ?? null}
      universe={res?.universe}
      loading={!res && !error}
      error={error}
      extraMetrics={["eps", "ret_1y"]}
      onBack={onBack}
      onSelect={onSelect}
    />
  );
}

/** A screen page: the companies matching one Popular Screen's criteria. */
function ScreenPage({ id, onBack, onSelect }: { id: string; onBack: () => void; onSelect: (s: CompanyHit) => void }) {
  const [res, setRes] = useState<ScreenResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchScreen(id)
        .then((r) => {
          if (!alive) return;
          setRes(r);
          if (r.universe.building) timer = setTimeout(load, 8000); // results fill in while the data builds
        })
        .catch((e: Error) => alive && setError(e.message));
    let timer: ReturnType<typeof setTimeout> | null = null;
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id]);
  const metrics = res?.stocks[0]?.matched ? Object.keys(res.stocks[0].matched) : [];
  return (
    <StockList
      title={res?.title ?? "Screen"}
      description={res?.description}
      criteria={res?.criteria}
      stocks={res?.stocks ?? null}
      universe={res?.universe}
      loading={!res && !error}
      error={error}
      extraMetrics={metrics}
      onBack={onBack}
      onSelect={onSelect}
    />
  );
}

export function HomeScreen() {
  // A small history so Back from a stock returns to the list it was opened from.
  const [stack, setStack] = useState<View[]>([{ kind: "home" }]);
  const view = stack[stack.length - 1];
  const push = useCallback((v: View) => {
    setStack((s) => [...s, v]);
    window.scrollTo({ top: 0 });
  }, []);
  const pop = useCallback(() => {
    setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
    window.scrollTo({ top: 0 });
  }, []);
  const openStock = useCallback((stock: CompanyHit) => push({ kind: "stock", stock }), [push]);

  // One full-screen search for the whole page: opened from the hero box or the header search bar.
  const [sectors, setSectors] = useState<SectorInfo[]>([]);
  const [search, setSearch] = useState<{ open: boolean; origin: DOMRect | null }>({ open: false, origin: null });
  useEffect(() => {
    let alive = true;
    fetchSectors().then((x) => alive && setSectors(x)).catch(() => {});
    const open = (e: Event) => setSearch({ open: true, origin: (e as CustomEvent<{ rect: DOMRect | null }>).detail?.rect ?? null });
    window.addEventListener(OPEN_SEARCH_EVENT, open);
    return () => {
      alive = false;
      window.removeEventListener(OPEN_SEARCH_EVENT, open);
    };
  }, []);
  // Patterns: the catalogue feeds the "Browse by pattern" chips; picking one opens the filter popup, Apply opens the results.
  const [catalogue, setCatalogue] = useState<CatalogueEntry[]>([]);
  const [patternsError, setPatternsError] = useState("");
  const [scanOptions, setScanOptions] = useState<ScanOptions | null>(null);
  const [modal, setModal] = useState<{ pattern: string; initial: ScanFilters; edit: boolean } | null>(null);
  useEffect(() => {
    let alive = true;
    fetchCatalogue()
      .then((c) => alive && setCatalogue(Object.values(c)))
      .catch((e: Error) => alive && setPatternsError(e.message));
    fetchScanOptions().then((o) => alive && setScanOptions(o)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const openPattern = useCallback((id: string) => {
    setSearch({ open: false, origin: null });
    setModal({ pattern: id, initial: EMPTY_FILTERS, edit: false });
  }, []);
  const applyFilters = (f: ScanFilters) => {
    if (!modal) return;
    const next: View = { kind: "patternScan", pattern: modal.pattern, filters: f };
    if (modal.edit) setStack((st) => [...st.slice(0, -1), next]); // editing the filters replaces the page, it does not stack another
    else push(next);
    window.scrollTo({ top: 0 });
    setModal(null);
  };
  // the header search bar is hidden on the home view (the hero already has the big box)
  useEffect(() => {
    document.documentElement.dataset.view = view.kind;
  }, [view.kind]);

  // "New Screen" (header button): back to the screener home with the cursor in the search box.
  useEffect(() => {
    const start = () => {
      setStack([{ kind: "home" }]);
      setTimeout(() => {
        // the home search box opens the full-screen search overlay
        (document.getElementById(SEARCH_INPUT_ID) as HTMLButtonElement | null)?.click();
      }, 60);
    };
    window.addEventListener(NEW_SCREEN_EVENT, start);
    return () => window.removeEventListener(NEW_SCREEN_EVENT, start);
  }, []);

  const page =
    view.kind === "stock" ? <StockView key={view.stock.symbol} stock={view.stock} onBack={pop} onOpenStock={openStock} />
    : view.kind === "sector" ? <SectorPage name={view.name} onBack={pop} onSelect={openStock} />
    : view.kind === "screen" ? <ScreenPage id={view.id} onBack={pop} onSelect={openStock} />
    : view.kind === "patternScan" && catalogue.find((c) => c.id === view.pattern) ? (
      <PatternScanPage
        key={view.pattern}
        pattern={catalogue.find((c) => c.id === view.pattern) as CatalogueEntry}
        filters={view.filters}
        options={scanOptions}
        onBack={pop}
        onEdit={() => setModal({ pattern: view.pattern, initial: view.filters, edit: true })}
        onOpenStock={openStock}
      />
    )
    : (
      <>
        <Hero patterns={catalogue} patternsError={patternsError} onPattern={openPattern} />
        <div className="mx-auto w-full max-w-7xl px-4 py-10">
          <PopularScreens onOpen={(id) => push({ kind: "screen", id })} />
        </div>
      </>
    );
  return (
    <>
      {page}
      {search.open && (
        <SearchOverlay
          sectors={sectors}
          patterns={catalogue}
          onSelectPattern={openPattern}
          origin={search.origin}
          onClose={() => setSearch({ open: false, origin: null })}
          onSelectStock={(h) => {
            setSearch({ open: false, origin: null });
            openStock(h);
          }}
          onSelectSector={(name) => {
            setSearch({ open: false, origin: null });
            push({ kind: "sector", name });
          }}
        />
      )}
      {modal && catalogue.find((c) => c.id === modal.pattern) && (
        <PatternFilterModal
          key={`${modal.pattern}-${modal.edit}`}
          pattern={catalogue.find((c) => c.id === modal.pattern) as CatalogueEntry}
          options={scanOptions}
          initial={modal.initial}
          onApply={applyFilters}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
}
