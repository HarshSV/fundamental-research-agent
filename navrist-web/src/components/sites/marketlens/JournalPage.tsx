"use client";

import { ArrowLeft, Download, Image as ImageIcon, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { SlidingTabs } from "./controls";
import {
  MISTAKES, compressImage, deleteTrade, metrics, newId, saveTrade, summarize, toCsv, useTrades, type Side, type Trade,
} from "./journal";
import { AddBox } from "./WatchlistPage";

const money = (v: number | null | undefined) => (v == null ? "—" : `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const dec = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toFixed(d));
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "var(--text-primary)" : v > 0 ? "var(--gain)" : "var(--loss)");
const today = () => new Date().toISOString().slice(0, 10);

interface Form {
  id: string; symbol: string; name: string; side: Side; setup: string; entryDate: string; entryPrice: string; qty: string; stop: string; target: string;
  exitDate: string; exitPrice: string; fees: string; notes: string; wentWell: string; improve: string; mistakes: string[]; image: string | null; createdAt: number;
}
const blank = (): Form => ({ id: newId(), symbol: "", name: "", side: "long", setup: "", entryDate: today(), entryPrice: "", qty: "", stop: "", target: "", exitDate: "", exitPrice: "", fees: "", notes: "", wentWell: "", improve: "", mistakes: [], image: null, createdAt: Date.now() });
const fromTrade = (t: Trade): Form => ({ ...t, entryPrice: String(t.entryPrice), qty: String(t.qty), stop: t.stop == null ? "" : String(t.stop), target: t.target == null ? "" : String(t.target), exitDate: t.exitDate ?? "", exitPrice: t.exitPrice == null ? "" : String(t.exitPrice), fees: t.fees == null ? "" : String(t.fees) });
const n = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block text-xs" style={{ color: "var(--text-secondary)" }}>
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px]" style={{ color: "var(--text-tertiary)" }}>{hint}</span>}
    </label>
  );
}
const input = "min-h-[44px] w-full rounded-lg border bg-transparent px-3 text-sm outline-none focus:border-[var(--accent-border)] sm:min-h-[38px]";
const inputStyle = { borderColor: "var(--border-default)", color: "var(--text-primary)" } as const;

function TradeForm({ initial, setups, onClose }: { initial: Form; setups: string[]; onClose: () => void }) {
  const [f, setF] = useState<Form>(initial);
  const [err, setErr] = useState("");
  const isNew = !useTrades().some((t) => t.id === initial.id);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((s) => ({ ...s, [k]: v }));
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", key);
    };
  }, [onClose]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const entry = n(f.entryPrice), qty = n(f.qty), exit = n(f.exitPrice);
    if (!f.symbol.trim()) return setErr("Pick the stock.");
    if (entry == null || entry <= 0) return setErr("Enter the entry price.");
    if (qty == null || qty <= 0) return setErr("Enter the quantity.");
    if ((exit != null) !== (f.exitDate !== "")) return setErr("An exit needs both an exit date and an exit price (leave both empty while the trade is open).");
    if (f.exitDate && f.exitDate < f.entryDate) return setErr("The exit date is before the entry date.");
    const trade: Trade = {
      id: f.id, symbol: f.symbol, name: f.name || f.symbol, side: f.side, setup: f.setup.trim(), entryDate: f.entryDate, entryPrice: entry, qty,
      stop: n(f.stop), target: n(f.target), exitDate: f.exitDate || null, exitPrice: exit, fees: n(f.fees), notes: f.notes, wentWell: f.wentWell,
      improve: f.improve, mistakes: f.mistakes, image: f.image, createdAt: f.createdAt,
    };
    const problem = saveTrade(trade);
    if (problem) return setErr(problem);
    onClose();
  };
  const pickImage = async (file: File | undefined) => {
    if (!file) return;
    try {
      set("image", await compressImage(file));
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-3 pt-[3vh] sm:px-4" role="dialog" aria-modal="true" aria-label="Trade">
      <div className="absolute inset-0" style={{ background: "var(--backdrop)", backdropFilter: "blur(6px)" }} onMouseDown={onClose} />
      <form onSubmit={submit} className="relative flex max-h-[94vh] w-full max-w-[760px] flex-col overflow-hidden rounded-2xl border" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "0 20px 60px rgba(0,0,0,.45)" }}>
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--border-subtle)" }}>
          <h2 className="text-lg font-semibold">{isNew ? "Log a trade" : "Edit trade"}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="flex h-10 w-10 items-center justify-center rounded-lg hover:bg-[var(--overlay)]"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <div>
            <div className="mb-1 text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Stock</div>
            {f.symbol ? (
              <div className="flex min-h-[44px] items-center justify-between rounded-lg border px-3 text-sm" style={inputStyle}>
                <span><b>{f.name || f.symbol}</b> <span style={{ color: "var(--text-tertiary)" }}>{f.symbol}</span></span>
                <button type="button" onClick={() => setF((s) => ({ ...s, symbol: "", name: "" }))} className="text-xs underline">Change</button>
              </div>
            ) : (
              <AddBox placeholder="Search the stock you traded" onAdd={(h) => setF((s) => ({ ...s, symbol: h.symbol, name: String(h.name ?? h.company_name ?? h.symbol) }))} />
            )}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field label="Side">
              <SlidingTabs ariaLabel="Side" value={f.side} onChange={(v) => set("side", v)} options={[{ id: "long", label: "Long" }, { id: "short", label: "Short" }]} />
            </Field>
            <Field label="Entry date"><input type="date" value={f.entryDate} onChange={(e) => set("entryDate", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Entry price (₹)"><input inputMode="decimal" value={f.entryPrice} onChange={(e) => set("entryPrice", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Quantity"><input inputMode="numeric" value={f.qty} onChange={(e) => set("qty", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Stop loss (₹)" hint="Needed for the R-multiple"><input inputMode="decimal" value={f.stop} onChange={(e) => set("stop", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Target (₹)"><input inputMode="decimal" value={f.target} onChange={(e) => set("target", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Exit date" hint="Empty while open"><input type="date" value={f.exitDate} onChange={(e) => set("exitDate", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Exit price (₹)"><input inputMode="decimal" value={f.exitPrice} onChange={(e) => set("exitPrice", e.target.value)} className={input} style={inputStyle} /></Field>
            <Field label="Fees and taxes (₹)"><input inputMode="decimal" value={f.fees} onChange={(e) => set("fees", e.target.value)} className={input} style={inputStyle} /></Field>
            <div className="col-span-2">
              <Field label="Setup / strategy" hint="For example Horizontal Resistance, VCP, Gap Up">
                <input list="journal-setups" value={f.setup} onChange={(e) => set("setup", e.target.value)} className={input} style={inputStyle} />
                <datalist id="journal-setups">{setups.map((s) => <option key={s} value={s} />)}</datalist>
              </Field>
            </div>
          </div>
          <Field label="Notes (why you took the trade, the plan)"><textarea value={f.notes} onChange={(e) => set("notes", e.target.value)} rows={3} className={`${input} py-2`} style={inputStyle} /></Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="What went well"><textarea value={f.wentWell} onChange={(e) => set("wentWell", e.target.value)} rows={3} className={`${input} py-2`} style={inputStyle} /></Field>
            <Field label="What to improve"><textarea value={f.improve} onChange={(e) => set("improve", e.target.value)} rows={3} className={`${input} py-2`} style={inputStyle} /></Field>
          </div>
          <div>
            <div className="mb-1.5 text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Mistakes (tick any that apply)</div>
            <div className="flex flex-wrap gap-2">
              {MISTAKES.map((m) => {
                const on = f.mistakes.includes(m);
                return (
                  <button key={m} type="button" aria-pressed={on} onClick={() => set("mistakes", on ? f.mistakes.filter((x) => x !== m) : [...f.mistakes, m])}
                    className="min-h-[40px] rounded-full border px-3 text-xs transition-colors sm:min-h-0 sm:py-1.5"
                    style={{ borderColor: on ? "var(--accent-border)" : "var(--border-default)", background: on ? "var(--accent-surface)" : "transparent", color: on ? "var(--accent)" : "var(--text-secondary)" }}>
                    {m}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <div className="mb-1.5 text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Chart screenshot</div>
            {f.image ? (
              <div className="relative inline-block">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={f.image} alt="Trade chart" className="max-h-56 rounded-lg border" style={{ borderColor: "var(--border-default)" }} />
                <button type="button" onClick={() => set("image", null)} aria-label="Remove the image" className="absolute right-2 top-2 flex h-9 w-9 items-center justify-center rounded-full bg-black/60 text-white"><X className="h-4 w-4" /></button>
              </div>
            ) : (
              <label className="flex min-h-[48px] cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-4 text-sm hover:bg-[var(--overlay-weak)]" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                <ImageIcon className="h-4 w-4" /> Add a picture of the chart
                <input type="file" accept="image/*" className="sr-only" onChange={(e) => pickImage(e.target.files?.[0])} />
              </label>
            )}
            <p className="mt-1 text-[11px]" style={{ color: "var(--text-tertiary)" }}>Pictures are shrunk and kept in this browser only.</p>
          </div>
          {err && <p role="alert" className="text-sm" style={{ color: "#f5a9a9" }}>{err}</p>}
        </div>
        <div className="flex items-center justify-between gap-3 border-t px-5 py-4" style={{ borderColor: "var(--border-subtle)" }}>
          {!isNew ? (
            <button type="button" onClick={() => window.confirm("Delete this trade?") && (deleteTrade(f.id), onClose())} className="flex min-h-[44px] items-center gap-1.5 text-sm sm:min-h-0" style={{ color: "var(--loss)" }}>
              <Trash2 className="h-4 w-4" /> Delete
            </button>
          ) : <span />}
          <button type="submit" className="min-h-[44px] rounded-lg px-8 text-sm font-medium text-white sm:min-h-[40px]" style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}>Save trade</button>
        </div>
      </form>
    </div>
  );
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)", boxShadow: "var(--shadow-md)" }}>
      <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{label}</div>
      <div className="nv-num mt-1 text-2xl font-semibold" style={{ color: color ?? "var(--text-primary)" }}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-tertiary)" }}>{sub}</div>}
    </div>
  );
}

export function JournalPage({ onBack, onOpenStock }: { onBack: () => void; onOpenStock: (s: { symbol: string; name: string }) => void }) {
  const trades = useTrades();
  const [edit, setEdit] = useState<Form | null>(null);
  const [show, setShow] = useState<"all" | "open" | "closed">("all");
  const [q, setQ] = useState("");
  const sum = useMemo(() => summarize(trades), [trades]);
  const setups = useMemo(() => [...new Set(trades.map((t) => t.setup).filter(Boolean))], [trades]);
  const list = useMemo(
    () =>
      [...trades]
        .sort((a, b) => (b.exitDate ?? b.entryDate).localeCompare(a.exitDate ?? a.entryDate) || b.createdAt - a.createdAt)
        .filter((t) => (show === "all" ? true : show === "open" ? !metrics(t).closed : metrics(t).closed))
        .filter((t) => !q.trim() || `${t.symbol} ${t.name} ${t.setup}`.toLowerCase().includes(q.trim().toLowerCase())),
    [trades, show, q],
  );
  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(trades)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "navrist-trade-journal.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold tracking-tight">Trade Journal</h1>
        <div className="flex gap-2">
          <button type="button" onClick={download} disabled={!trades.length} className="flex min-h-[44px] items-center gap-1.5 rounded-xl border px-3 text-sm hover:bg-[var(--overlay-weak)] disabled:opacity-40 sm:min-h-[40px]" style={{ borderColor: "var(--border-default)" }}><Download className="h-4 w-4" /> CSV</button>
          <button type="button" onClick={() => setEdit(blank())} className="flex min-h-[44px] items-center gap-1.5 rounded-xl px-4 text-sm font-medium text-white sm:min-h-[40px]" style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}><Plus className="h-4 w-4" /> Log a trade</button>
        </div>
      </div>
      <p className="mt-2 max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
        Log each trade with its numbers, notes and a chart picture, then look back at what worked and what repeats as a mistake. Everything is saved in this browser only; download the CSV to keep a copy.
      </p>

      {trades.length === 0 ? (
        <div className="mt-8 rounded-xl border p-10 text-center text-sm" style={{ borderColor: "var(--border-default)", background: "var(--surface-1)", color: "var(--text-secondary)" }}>
          No trades yet. Press <b>Log a trade</b> to add your first one.
        </div>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Trades" value={String(sum.trades)} sub={`${sum.closed} closed · ${sum.open} open`} />
            <Stat label="Win rate" value={sum.winRate == null ? "—" : `${sum.winRate.toFixed(0)}%`} sub={`${sum.wins} wins · ${sum.losses} losses`} />
            <Stat label="Total P&L" value={money(sum.totalPnl)} color={tone(sum.totalPnl)} sub="closed trades, after fees" />
            <Stat label="Expectancy per trade" value={money(sum.expectancy)} color={tone(sum.expectancy)} sub={sum.avgR == null ? "R-multiple needs stops" : `average ${dec(sum.avgR)} R`} />
            <Stat label="Average win" value={money(sum.avgWin)} color="var(--gain)" />
            <Stat label="Average loss" value={money(sum.avgLoss)} color="var(--loss)" />
            <Stat label="Profit factor" value={dec(sum.profitFactor)} sub="gross profit over gross loss" />
            <Stat label="Most common mistake" value={sum.mistakes[0]?.tag ?? "—"} sub={sum.mistakes[0] ? `${sum.mistakes[0].n} trade${sum.mistakes[0].n > 1 ? "s" : ""}` : "none ticked"} />
          </div>

          {(sum.bySetup.length > 0 || sum.mistakes.length > 0) && (
            <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
              {sum.bySetup.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
                  <div className="mb-2 text-sm font-semibold">By setup</div>
                  <table className="w-full text-sm">
                    <tbody>
                      {sum.bySetup.map((s) => (
                        <tr key={s.setup} className="border-t first:border-t-0" style={{ borderColor: "var(--border-subtle)" }}>
                          <td className="py-2 pr-2">{s.setup}</td>
                          <td className="nv-num py-2 text-right text-xs" style={{ color: "var(--text-tertiary)" }}>{s.n} trade{s.n > 1 ? "s" : ""} · {s.winRate.toFixed(0)}% wins</td>
                          <td className="nv-num py-2 pl-3 text-right font-medium" style={{ color: tone(s.pnl) }}>{money(s.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {sum.mistakes.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
                  <div className="mb-2 text-sm font-semibold">Mistakes that repeat</div>
                  <div className="flex flex-wrap gap-2">
                    {sum.mistakes.map((m) => <span key={m.tag} className="rounded-full px-3 py-1 text-xs" style={{ background: "var(--accent-surface)", color: "var(--accent)" }}>{m.tag} · {m.n}</span>)}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <SlidingTabs ariaLabel="Show" value={show} onChange={setShow} options={[{ id: "all", label: "All" }, { id: "open", label: "Open" }, { id: "closed", label: "Closed" }]} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search stock or setup" aria-label="Search trades" className={`${input} max-w-xs`} style={{ ...inputStyle, background: "var(--surface-1)" }} />
          </div>
          <div className="mt-3 overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
            <p className="sticky left-0 w-[calc(100vw-2rem)] px-4 py-2 text-[11px] sm:hidden" style={{ color: "var(--text-tertiary)" }}>Swipe sideways for more columns →</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs" style={{ color: "var(--text-tertiary)", background: "var(--overlay-weak)" }}>
                  {["Date", "Stock", "Side", "Setup", "Entry", "Exit", "Qty", "P&L", "Return", "R", "Days", "Mistakes"].map((h, i) => (
                    <th key={h} className={`whitespace-nowrap px-3 py-3 font-semibold sm:px-4 ${i < 4 || i === 11 ? "text-left" : "text-right"}`}>{h}</th>
                  ))}
                  <th className="px-3 py-3" />
                </tr>
              </thead>
              <tbody>
                {list.map((t) => {
                  const m = metrics(t);
                  return (
                    <tr key={t.id} className="cursor-pointer border-t align-top transition-colors hover:bg-[var(--overlay-weak)]" style={{ borderColor: "var(--border-subtle)" }} onClick={() => setEdit(fromTrade(t))}>
                      <td className="whitespace-nowrap px-3 py-3 text-xs sm:px-4" style={{ color: "var(--text-secondary)" }}>{t.entryDate}</td>
                      <td className="px-3 py-3 sm:px-4">
                        <button type="button" onClick={(e) => { e.stopPropagation(); onOpenStock({ symbol: t.symbol, name: t.name }); }} className="text-left font-semibold hover:text-[var(--accent)]">{t.name}</button>
                        <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{t.symbol}</div>
                      </td>
                      <td className="px-3 py-3 text-xs capitalize sm:px-4">{t.side}</td>
                      <td className="px-3 py-3 text-xs sm:px-4">{t.setup || "—"}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4">₹{t.entryPrice.toLocaleString("en-IN")}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4">{t.exitPrice == null ? <span className="rounded-full px-2 py-0.5 text-[11px]" style={{ background: "var(--accent-surface)", color: "var(--accent)" }}>Open</span> : `₹${t.exitPrice.toLocaleString("en-IN")}`}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4">{t.qty.toLocaleString("en-IN")}</td>
                      <td className="nv-num px-3 py-3 text-right font-medium sm:px-4" style={{ color: tone(m.pnl) }}>{money(m.pnl)}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(m.pct) }}>{m.pct == null ? "—" : `${m.pct >= 0 ? "+" : ""}${m.pct.toFixed(1)}%`}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4" style={{ color: tone(m.r) }}>{m.r == null ? "—" : `${m.r.toFixed(1)}R`}</td>
                      <td className="nv-num px-3 py-3 text-right sm:px-4">{m.days ?? "—"}</td>
                      <td className="px-3 py-3 text-xs sm:px-4"><div className="max-w-[220px]">{t.mistakes.join(", ") || "—"}</div></td>
                      <td className="px-3 py-3 text-xs">{t.image ? <ImageIcon className="h-4 w-4" style={{ color: "var(--text-tertiary)" }} aria-label="Has a chart picture" /> : null}</td>
                    </tr>
                  );
                })}
                {list.length === 0 && <tr><td colSpan={13} className="px-4 py-8 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>No trades match.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
      {edit && <TradeForm key={edit.id} initial={edit} setups={setups} onClose={() => setEdit(null)} />}
    </div>
  );
}
