"use client";

import { useCallback, useEffect, useState } from "react";
import type { CompanyHit } from "@/lib/api";
import { NEW_SCREEN_EVENT } from "./Header";
import { Hero } from "./Hero";
import { PopularScreens } from "./PopularScreens";
import {
  fetchScreen, fetchSector, type ScreenResult, type SectorResult,
} from "./screens";
import { StockList } from "./StockList";
import { StockView } from "./StockView";

export const SEARCH_INPUT_ID = "navrist-search";

type View =
  | { kind: "home" }
  | { kind: "stock"; stock: CompanyHit }
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

  // "New Screen" (header button): back to the screener home with the cursor in the search box.
  useEffect(() => {
    const start = () => {
      setStack([{ kind: "home" }]);
      setTimeout(() => {
        const el = document.getElementById(SEARCH_INPUT_ID) as HTMLInputElement | null;
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.focus({ preventScroll: true });
      }, 60);
    };
    window.addEventListener(NEW_SCREEN_EVENT, start);
    return () => window.removeEventListener(NEW_SCREEN_EVENT, start);
  }, []);

  if (view.kind === "stock") return <StockView stock={view.stock} onBack={pop} />;
  if (view.kind === "sector") return <SectorPage name={view.name} onBack={pop} onSelect={openStock} />;
  if (view.kind === "screen") return <ScreenPage id={view.id} onBack={pop} onSelect={openStock} />;
  return (
    <>
      <Hero onSelect={openStock} onSector={(name) => push({ kind: "sector", name })} />
      <div className="mx-auto w-full max-w-7xl px-4 py-10">
        <PopularScreens onOpen={(id) => push({ kind: "screen", id })} />
      </div>
    </>
  );
}
