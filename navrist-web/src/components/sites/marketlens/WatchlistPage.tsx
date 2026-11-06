"use client";

import { ArrowLeft, Copy, LineChart, List, Plus, ScanLine, Search, Star, Trash2, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { searchSymbols, type CompanyHit } from "@/lib/api";
import { SlidingTabs } from "./controls";
import { STATUS_COLOR, STATUS_LABEL } from "./patterns";
import { emptyFilters, searchScan, type ScanRow } from "./patternScan";
import { TvChart } from "./TvChart";
import {
  activeList, addToWatchlist, createList, deleteList, importText, isWatched, removeFromWatchlist, selectList, setNote, setPriority, shareText,
  useWatchlists, type Priority, type WatchItem,
} from "./watchlist";

const PRIORITIES: { id: Priority; label: string; color: string }[] = [
  { id: "high", label: "High priority", color: "#ef4444" },
  { id: "medium", label: "Medium priority", color: "#f59e0b" },
  { id: "low", label: "Low priority", color: "#3b82f6" },
];
const num = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--text-tertiary)" : v >= 0 ? "var(--gain)" : "var(--loss)");

/** The star on a stock page: adds the stock to / removes it from the open watchlist. */
export function WatchStar({ symbol, name }: { symbol: string; name: string }) {
  const store = useWatchlists();
  const on = isWatched(store, symbol);
  return (
    <button
      type="button"
      onClick={() => (on ? removeFromWatchlist(symbol) : addToWatchlist(symbol, name))}
      aria-pressed={on}
      aria-label={on ? `Remove ${symbol} from the watchlist` : `Add ${symbol} to the watchlist`}
      title={on ? `In "${store.active}": click to remove` : `Add to "${store.active}"`}
      className="flex min-h-[40px] items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors hover:bg-[var(--overlay-weak)]"
      style={{ borderColor: on ? "#f59e0b" : "var(--border-default)", color: on ? "#f59e0b" : "var(--text-secondary)" }}
    >
      <Star className="h-4 w-4" fill={on ? "#f59e0b" : "none"} /> {on ? "Watching" : "Watchlist"}
    </button>
  );
}

/** Search box that adds a stock to the open watchlist. */
export function AddBox({ onAdd, placeholder = "Add a stock: name or symbol" }: { onAdd: (h: CompanyHit) => void; placeholder?: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CompanyHit[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    const ctl = new AbortController();
    const t = setTimeout(() => searchSymbols(q.trim(), ctl.signal).then((h) => setHits(h.slice(0, 8))).catch(() => {}), 200);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [q]);
  useEffect(() => {
    const click = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", click);
    return () => document.removeEventListener("mousedown", click);
  }, []);
  return (
    <div ref={box} className="relative w-full max-w-md">
      <div className="flex items-center gap-2 rounded-xl border px-3" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
        <Search className="h-4 w-4 shrink-0" style={{ color: "var(--text-tertiary)" }} />
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="min-h-[44px] w-full bg-transparent text-sm outline-none sm:min-h-[40px]"
        />
      </div>
      {open && hits.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-md)" }}>
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  onAdd(h);
                  setQ("");
                  setHits([]);
                  setOpen(false);
                }}
                className="flex min-h-[44px] w-full items-center justify-between gap-3 px-3 text-left text-sm hover:bg-[var(--overlay-weak)]"
              >
                <span className="truncate font-medium">{h.name ?? h.company_name ?? h.symbol}</span>
                <span className="flex shrink-0 items-center gap-1 text-xs" style={{ color: "var(--text-tertiary)" }}>{h.symbol} <Plus className="h-3.5 w-3.5" /></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WatchlistPage({
  onBack, onOpenStock, onScan,
}: {
  onBack: () => void;
  onOpenStock: (s: CompanyHit) => void;
  onScan: (symbols: string[]) => void;
}) {
  const store = useWatchlists();
  const items = activeList(store);
  const [view, setView] = useState<"list" | "charts">("list");
  const [rows, setRows] = useState<Record<string, ScanRow>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [note, setNoteMsg] = useState("");
  const symKey = items.map((i) => i.symbol).sort().join(",");

  useEffect(() => {
    if (!symKey) {
      setRows({});
      return;
    }
    let alive = true;
    setLoading(true);
    setError("");
    searchScan("all", { ...emptyFilters(), symbols: { values: symKey.split(",") } }, { q: "", page: 1, page_size: 100, sort: "market_cap" }, view === "charts")
      .then((res) => alive && setRows(Object.fromEntries(res.rows.map((r) => [r.symbol, r]))))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [symKey, view]);

  const flash = (t: string) => {
    setNoteMsg(t);
    setTimeout(() => setNoteMsg(""), 2800);
  };
  const grouped = useMemo(() => PRIORITIES.map((p) => ({ ...p, items: items.filter((i) => i.priority === p.id) })), [items]);
  const names = Object.keys(store.lists);

  const share = async () => {
    try {
      await navigator.clipboard.writeText(shareText(items));
      flash("Copied. Paste it into Import on another device.");
    } catch {
      flash("Could not copy.");
    }
  };
  const doImport = () => {
    const code = window.prompt("Paste a watchlist code");
    if (!code) return;
    const n = importText(code);
    flash(n < 0 ? "That is not a valid watchlist code." : `Imported ${n} stock${n === 1 ? "" : "s"}.`);
  };
  const newList = () => {
    const n = window.prompt("Name for the new watchlist");
    if (n && !createList(n)) flash("That name is empty or already used.");
  };

  const row = (it: WatchItem) => {
    const r = rows[it.symbol];
    return (
      <tr key={it.symbol} className="border-t align-top" style={{ borderColor: "var(--border-subtle)" }}>
        <td className="px-3 py-3 sm:px-4">
          <button type="button" onClick={() => onOpenStock({ symbol: it.symbol, name: it.name })} className="text-left hover:text-[var(--accent)]">
            <div className="font-semibold">{it.name}</div>
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{it.symbol}</div>
          </button>
        </td>
        <td className="px-3 py-3 sm:px-4">
          <select
            value={it.priority}
            onChange={(e) => setPriority(it.symbol, e.target.value as Priority)}
            aria-label={`Priority of ${it.symbol}`}
            className="min-h-[40px] rounded-lg border bg-transparent px-2 text-xs sm:min-h-0 sm:py-1"
            style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          >
            {PRIORITIES.map((p) => <option key={p.id} value={p.id} style={{ color: "#111" }}>{p.label.replace(" priority", "")}</option>)}
          </select>
        </td>
        <td className="nv-num px-3 py-3 text-right sm:px-4">{r ? `₹${num(r.price)}` : "—"}</td>
        <td className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(r?.ret_1m) }}>{pct(r?.ret_1m)}</td>
        <td className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(r?.ret_3m) }}>{pct(r?.ret_3m)}</td>
        <td className="nv-num px-3 py-3 text-right font-semibold sm:px-4">{r?.rs ?? "—"}</td>
        <td className="nv-num px-3 py-3 text-right sm:px-4">{r?.pct_from_52w_high == null ? "—" : `${r.pct_from_52w_high.toFixed(1)}%`}</td>
        <td className="px-3 py-3 sm:px-4">
          {r?.occurrence ? (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium" style={{ background: `${STATUS_COLOR[r.occurrence.status]}22`, color: STATUS_COLOR[r.occurrence.status] }}>
              {r.occurrence.pattern.replace(/-and-/g, " & ").replace(/-/g, " ")} · {STATUS_LABEL[r.occurrence.status]}
            </span>
          ) : r ? <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>No pattern now</span> : <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{loading ? "…" : "Not in the scanned list"}</span>}
        </td>
        <td className="px-3 py-3 sm:px-4">
          <input
            defaultValue={it.note ?? ""}
            onBlur={(e) => e.target.value !== (it.note ?? "") && setNote(it.symbol, e.target.value)}
            placeholder="Add a note"
            aria-label={`Note for ${it.symbol}`}
            className="min-h-[40px] w-40 rounded-lg border bg-transparent px-2 text-xs outline-none sm:min-h-0 sm:py-1"
            style={{ borderColor: "var(--border-subtle)" }}
          />
        </td>
        <td className="px-2 py-3 text-right sm:px-3">
          <button type="button" onClick={() => removeFromWatchlist(it.symbol)} aria-label={`Remove ${it.symbol}`} className="flex h-10 w-10 items-center justify-center rounded-lg hover:bg-[var(--overlay)] sm:h-8 sm:w-8" style={{ color: "var(--text-tertiary)" }}>
            <X className="h-4 w-4" />
          </button>
        </td>
      </tr>
    );
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <h1 className="text-3xl font-bold tracking-tight">Watchlist</h1>
      <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Keep the stocks you want to follow and sort them into high, medium and low priority. Lists are saved in this browser only; use Share to move one to another device.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <select
          value={store.active}
          onChange={(e) => selectList(e.target.value)}
          aria-label="Watchlist"
          className="min-h-[44px] rounded-xl border bg-transparent px-3 text-sm sm:min-h-[40px]"
          style={{ borderColor: "var(--border-default)", background: "var(--surface-1)", color: "var(--text-primary)" }}
        >
          {names.map((n) => <option key={n} value={n}>{n} ({store.lists[n].length})</option>)}
        </select>
        <button type="button" onClick={newList} className="flex min-h-[44px] items-center gap-1.5 rounded-xl border px-3 text-sm hover:bg-[var(--overlay-weak)] sm:min-h-[40px]" style={{ borderColor: "var(--border-default)" }}><Plus className="h-4 w-4" /> New list</button>
        <button
          type="button"
          onClick={() => window.confirm(`Delete the list "${store.active}"?`) && deleteList(store.active)}
          aria-label="Delete this list"
          className="flex min-h-[44px] items-center gap-1.5 rounded-xl border px-3 text-sm hover:bg-[var(--overlay-weak)] sm:min-h-[40px]"
          style={{ borderColor: "var(--border-default)" }}
        ><Trash2 className="h-4 w-4" /> Delete list</button>
        <div className="flex-1" />
        <button type="button" onClick={share} disabled={!items.length} className="flex min-h-[44px] items-center gap-1.5 rounded-xl border px-3 text-sm hover:bg-[var(--overlay-weak)] disabled:opacity-40 sm:min-h-[40px]" style={{ borderColor: "var(--border-default)" }}><Copy className="h-4 w-4" /> Share</button>
        <button type="button" onClick={doImport} className="flex min-h-[44px] items-center gap-1.5 rounded-xl border px-3 text-sm hover:bg-[var(--overlay-weak)] sm:min-h-[40px]" style={{ borderColor: "var(--border-default)" }}><Upload className="h-4 w-4" /> Import</button>
        <button
          type="button"
          disabled={!items.length}
          onClick={() => onScan(items.map((i) => i.symbol))}
          title="Open these stocks in the screener, with all its filters, list and chart views"
          className="flex min-h-[44px] items-center gap-1.5 rounded-xl px-4 text-sm font-medium text-white disabled:opacity-40 sm:min-h-[40px]"
          style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
        ><ScanLine className="h-4 w-4" /> Scan these</button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <AddBox onAdd={(h) => addToWatchlist(h.symbol, String(h.name ?? h.company_name ?? h.symbol))} />
        <SlidingTabs ariaLabel="View" value={view} onChange={setView} options={[{ id: "list", label: <span className="flex items-center gap-1.5"><List className="h-3.5 w-3.5" />List</span> }, { id: "charts", label: <span className="flex items-center gap-1.5"><LineChart className="h-3.5 w-3.5" />Charts</span> }]} />
        {note && <span className="text-sm" style={{ color: "var(--accent)" }}>{note}</span>}
      </div>
      {error && <p className="mt-3 text-sm" style={{ color: "#f5a9a9" }}>Could not load market data for the list: {error}</p>}

      {items.length === 0 ? (
        <div className="mt-8 rounded-xl border p-10 text-center text-sm" style={{ borderColor: "var(--border-default)", background: "var(--surface-1)", color: "var(--text-secondary)" }}>
          This watchlist is empty. Search above to add a stock, or open any stock and press the star.
        </div>
      ) : view === "list" ? (
        <div className="mt-6 space-y-6">
          {grouped.filter((g) => g.items.length).map((g) => (
            <section key={g.id}>
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.12em]" style={{ color: g.color }}>
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: g.color }} /> {g.label} ({g.items.length})
              </h2>
              <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
                <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                      <th className="px-3 py-3 text-left font-semibold sm:px-4">Stock</th>
                      <th className="px-3 py-3 text-left font-semibold sm:px-4">Priority</th>
                      <th className="px-3 py-3 text-right font-semibold sm:px-4">Price</th>
                      <th className="px-3 py-3 text-right font-semibold sm:px-4">1M</th>
                      <th className="px-3 py-3 text-right font-semibold sm:px-4">3M</th>
                      <th className="px-3 py-3 text-right font-semibold sm:px-4">RS</th>
                      <th className="whitespace-nowrap px-3 py-3 text-right font-semibold sm:px-4">From 52W high</th>
                      <th className="px-3 py-3 text-left font-semibold sm:px-4">Pattern now</th>
                      <th className="px-3 py-3 text-left font-semibold sm:px-4">Note</th>
                      <th className="px-2 py-3" />
                    </tr>
                  </thead>
                  <tbody>{g.items.map(row)}</tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          {items.map((it) => {
            const r = rows[it.symbol];
            return (
              <div key={it.symbol} className="overflow-hidden rounded-xl border" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
                <div className="flex items-center justify-between gap-3 px-4 py-3">
                  <button type="button" onClick={() => onOpenStock({ symbol: it.symbol, name: it.name })} className="min-w-0 text-left hover:text-[var(--accent)]">
                    <div className="truncate font-semibold">{it.name}</div>
                    <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{it.symbol} · {it.priority} priority{r ? ` · ₹${num(r.price)}` : ""}</div>
                  </button>
                  <button type="button" onClick={() => removeFromWatchlist(it.symbol)} aria-label={`Remove ${it.symbol}`} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg hover:bg-[var(--overlay)]"><X className="h-4 w-4" /></button>
                </div>
                {r?.candles ? <TvChart bars={r.candles} occurrence={r.occurrence} resistance={r.resistance} height={240} /> : (
                  <div className="px-4 pb-6 text-xs" style={{ color: "var(--text-tertiary)" }}>{loading ? "Loading chart…" : "No chart data: this stock is not in the scanned list."}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="mt-4 text-xs" style={{ color: "var(--text-tertiary)" }}>Market data shown for up to 100 stocks per list, from the daily scan. A blank means it cannot be computed.</p>
    </div>
  );
}
