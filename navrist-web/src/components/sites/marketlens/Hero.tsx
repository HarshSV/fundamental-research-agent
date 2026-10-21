"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { searchSymbols, type CompanyHit } from "@/lib/api";
import { SEARCH_HINTS, TYPED_PHRASES } from "./data";
import { fetchSectors, type SectorInfo } from "./screens";

function useTyped(phrases: string[]) {
  const [i, setI] = useState(0);
  const [n, setN] = useState(0);
  const [del, setDel] = useState(false);
  useEffect(() => {
    const full = phrases[i];
    const t = setTimeout(
      () => {
        if (!del && n < full.length) setN(n + 1);
        else if (!del) setDel(true);
        else if (n > 0) setN(n - 1);
        else {
          setDel(false);
          setI((i + 1) % phrases.length);
        }
      },
      !del && n === full.length ? 1500 : del ? 35 : 80,
    );
    return () => clearTimeout(t);
  }, [i, n, del, phrases]);
  return phrases[i].slice(0, n);
}

export function Hero({ onSelect, onSector }: { onSelect: (stock: CompanyHit) => void; onSector: (name: string) => void }) {
  const [sectors, setSectors] = useState<SectorInfo[]>([]);
  const [sectorsError, setSectorsError] = useState("");
  useEffect(() => {
    let alive = true;
    fetchSectors().then((s) => alive && setSectors(s)).catch((e: Error) => alive && setSectorsError(e.message));
    return () => {
      alive = false;
    };
  }, []);
  const typed = useTyped(TYPED_PHRASES);
  const hint = useTyped(SEARCH_HINTS);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CompanyHit[]>([]);
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    if (!q.trim()) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      searchSymbols(q, ctrl.signal)
        .then((r) => {
          setHits(r);
          setSearchError("");
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setSearchError(e.message);
        });
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

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
        <form className="relative mx-auto mb-10 w-full max-w-2xl" onSubmit={(e) => e.preventDefault()}>
          <div className="relative flex items-center">
            <Search className="absolute left-5 z-[2] h-5 w-5" style={{ color: "var(--text-tertiary)" }} />
            <input
              id="navrist-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`Search Equity Stocks or Sector : ${hint}`}
              className="h-14 w-full rounded-[10.5px] border pl-[3.25rem] pr-32 text-[15px] outline-none"
              style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}
            />
          </div>
          {q.trim() && (hits.length > 0 || searchError) && (
            <ul
              className="absolute left-0 right-0 top-full z-10 mt-2 overflow-hidden rounded-xl border text-left text-sm"
              style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-md)" }}
            >
              {searchError && (
                <li className="px-4 py-3 text-xs" style={{ color: "#f5a9a9" }}>
                  {searchError}
                </li>
              )}
              {hits.map((h) => (
                <li
                  key={h.symbol}
                  onClick={() => onSelect(h)}
                  className="flex cursor-pointer items-center justify-between px-4 py-2.5 hover:bg-[var(--accent-surface)]"
                >
                  <span>{h.name ?? h.company_name ?? h.symbol}</span>
                  <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                    {h.symbol}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </form>
        <div className="mb-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
          Browse by sector
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {sectors.map((s) => (
            <button
              key={s.name}
              onClick={() => onSector(s.name)}
              title={`${s.count} companies`}
              className="rounded-full border px-3.5 py-1.5 text-xs transition-all duration-200 hover:border-[var(--accent-border)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)]"
              style={{
                background: "var(--surface-1)",
                borderColor: "var(--border-default)",
                color: "var(--text-secondary)",
              }}
            >
              {s.name}
              <span className="ml-1.5" style={{ color: "var(--text-tertiary)" }}>{s.count}</span>
            </button>
          ))}
          {sectorsError && <span className="text-xs" style={{ color: "#f5a9a9" }}>Could not load sectors: {sectorsError}</span>}
        </div>
      </div>
    </div>
  );
}
