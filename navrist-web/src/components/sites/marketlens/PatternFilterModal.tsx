"use client";

import { Check, ChevronDown, Share2, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CatalogueEntry } from "./patterns";
import {
  MCAP_KEY, RANGE_DEFS, RESISTANCE_ID, SCREENER_ID, deleteSaved, emptyFilters, isSpecial, loadSaved, parseShareCode, saveFilter, shareCode,
  type Quadrant, type RangeDef, type SavedFilter, type ScanFilters, type ScanOptions, type Tab,
} from "./patternScan";

const SLIDER_STEPS = 1000;
const FALLBACK_CAP = { min: 100, max: 2_000_000 }; // Rs crore, used only until the real bounds arrive
type ModalTab = Tab | "resistance";
const TABS: { id: ModalTab; label: string }[] = [
  { id: "technicals", label: "Technicals" },
  { id: "fundamentals", label: "Fundamentals" },
  { id: "misc", label: "Miscellaneous" },
  { id: "resistance", label: "Horizontal Resistance" },
];
const QUADRANTS: { id: Quadrant; label: string }[] = [
  { id: "leading", label: "Leading" }, { id: "improving", label: "Improving" }, { id: "weakening", label: "Weakening" }, { id: "lagging", label: "Lagging" },
];

// the slider is logarithmic: market caps span five orders of magnitude, a linear slider would be unusable
const toValue = (pos: number, lo: number, hi: number) => Math.round(lo * Math.pow(hi / lo, pos / SLIDER_STEPS));
const toPos = (v: number, lo: number, hi: number) => Math.round((Math.log(Math.max(v, lo) / lo) / Math.log(hi / lo)) * SLIDER_STEPS);
const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? (list.includes(v) ? list : [...list, v]) : list.filter((x) => x !== v));

const box = { borderColor: "var(--border-default)", background: "var(--surface-2, var(--surface-1))", color: "var(--text-primary)" };

function Tick({ checked, label, onChange }: { checked: boolean; label: string; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-[var(--overlay-weak)]">
      <span
        className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors"
        style={{ borderColor: checked ? "#b7b4e7" : "var(--border-default)", background: checked ? "#b7b4e7" : "transparent" }}
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} style={{ color: "var(--on-accent)" }} />}
      </span>
      <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span style={{ color: "var(--text-primary)" }}>{label}</span>
    </label>
  );
}

/** "Select all" at the top of a filter: ticks every option, and becomes "Clear" once they are all ticked. */
function SelectAll({ label, total, selected, onAll, onNone }: { label: string; total: number; selected: number; onAll: () => void; onNone: () => void }) {
  const all = total > 0 && selected >= total;
  return (
    <button
      type="button"
      disabled={total === 0}
      onClick={all ? onNone : onAll}
      aria-label={`${all ? "Clear" : "Select all"} ${label}`}
      className="rounded-lg border px-3 py-1 text-xs font-medium transition-colors hover:border-[var(--accent-border)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)] disabled:opacity-40"
      style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
    >
      {all ? "Clear" : "Select all"}
    </button>
  );
}

function Section({ title, hint, right, children }: { title: string; hint?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-b px-6 py-5 last:border-b-0" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {hint && <p className="mt-0.5 text-xs" style={{ color: "var(--text-tertiary)" }}>{hint}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

/** A filter row that is ignored until its checkbox is ticked (as on the reference screener). */
function Row({ on, onToggle, children, hint }: { on: boolean; onToggle: (v: boolean) => void; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2" title={hint}>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        onClick={() => onToggle(!on)}
        className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors"
        style={{ borderColor: on ? "#b7b4e7" : "var(--border-default)", background: on ? "#b7b4e7" : "transparent" }}
      >
        {on && <Check className="h-3 w-3" strokeWidth={3} style={{ color: "var(--on-accent)" }} />}
      </button>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-sm" style={{ opacity: on ? 1 : 0.8 }}>{children}</div>
    </div>
  );
}

function Num({ value, onChange, placeholder, width = "w-24" }: { value: number | null; onChange: (v: number | null) => void; placeholder?: string; width?: string }) {
  return (
    <input
      inputMode="decimal"
      placeholder={placeholder ?? "Any"}
      value={value ?? ""}
      onChange={(e) => {
        const t = e.target.value.replace(/[^\d.\-]/g, "");
        onChange(t === "" || t === "-" || t === "." ? null : Number(t));
      }}
      className={`${width} rounded-lg border px-2.5 py-1.5 text-sm outline-none`}
      style={box}
    />
  );
}

function Pick<T extends string | number>({ value, options, onChange, label }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <span className="relative inline-flex items-center">
      <select
        aria-label={label}
        value={String(value)}
        onChange={(e) => onChange((typeof value === "number" ? Number(e.target.value) : e.target.value) as T)}
        className="appearance-none rounded-lg border py-1.5 pl-2.5 pr-7 text-sm outline-none"
        style={box}
      >
        {options.map((o) => <option key={String(o.v)} value={String(o.v)}>{o.label}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5" style={{ color: "var(--text-tertiary)" }} />
    </span>
  );
}

function RangeRow({ def, f, set }: { def: RangeDef; f: ScanFilters; set: (k: string, v: { on: boolean; min: number | null; max: number | null }) => void }) {
  const r = f.ranges[def.key];
  const u = def.unit ? <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{def.unit}</span> : null;
  return (
    <Row on={r.on} onToggle={(on) => set(def.key, on ? { ...r, on } : { on: false, min: null, max: null })} hint={def.hint}>
      <span className="min-w-[10.5rem] flex-1">{def.label}</span>
      {def.minOnly ? <span className="text-xs">≥</span> : null}
      <Num value={r.min} onChange={(min) => set(def.key, { ...r, on: true, min })} placeholder={def.minOnly ? "Min" : "From"} />
      {!def.minOnly && (
        <>
          <span style={{ color: "var(--text-tertiary)" }}>–</span>
          <Num value={r.max} onChange={(max) => set(def.key, { ...r, on: true, max })} placeholder="To" />
        </>
      )}
      {u}
    </Row>
  );
}

function RangeList({ tab, f, set }: { tab: Tab; f: ScanFilters; set: (k: string, v: { on: boolean; min: number | null; max: number | null }) => void }) {
  return <>{RANGE_DEFS.filter((d) => d.tab === tab).map((d) => <RangeRow key={d.key} def={d} f={f} set={set} />)}</>;
}

function MaSection({
  title, periods, value, onChange,
}: { title: string; periods: number[]; value: ScanFilters["ema"]; onChange: (v: ScanFilters["ema"]) => void }) {
  return (
    <Section
      title={title}
      hint={`Compares the latest close with the ${title} of the daily chart`}
      right={<SelectAll label={title} total={periods.length} selected={value.periods.length} onAll={() => onChange({ ...value, periods: [...periods] })} onNone={() => onChange({ ...value, periods: [] })} />}
    >
      <div className="mb-3 inline-flex rounded-lg p-0.5 text-xs font-medium" style={{ background: "var(--overlay-weak)" }}>
        {(["above", "below"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onChange({ ...value, side: s })}
            className="rounded-md px-3 py-1 transition-colors"
            style={{ background: value.side === s ? "#b7b4e7" : "transparent", color: value.side === s ? "var(--on-accent)" : "var(--text-secondary)" }}
          >
            Price {s}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">
        {periods.map((p) => (
          <Tick key={p} checked={value.periods.includes(p)} label={`${title} ${p}`} onChange={(on) => onChange({ ...value, periods: toggle(value.periods, p, on) })} />
        ))}
      </div>
    </Section>
  );
}

/**
 * The popup behind every scanner: a pattern, the Create Screener or the Horizontal Resistance scan. Three tabs
 * (Technicals / Fundamentals / Miscellaneous) of filters that only count once their checkbox is ticked, lists with
 * Select all, and Save / Load / Share of a filter set. Apply runs the scan.
 */
export function PatternFilterModal({
  pattern, options, initial, onApply, onClose,
}: {
  pattern: CatalogueEntry;
  options: ScanOptions | null;
  initial: ScanFilters;
  onApply: (f: ScanFilters) => void;
  onClose: () => void;
}) {
  const [f, setF] = useState<ScanFilters>(initial);
  const [tab, setTab] = useState<ModalTab>("technicals");
  const [secQ, setSecQ] = useState("");
  const [saved, setSaved] = useState<SavedFilter[]>(() => loadSaved());
  const [menu, setMenu] = useState<null | "load" | "save">(null);
  const [name, setName] = useState("");
  const [asDefault, setAsDefault] = useState(false);
  const [note, setNote] = useState("");
  const special = isSpecial(pattern.id);
  const bounds = {
    min: options?.market_cap_cr.min ? Math.max(1, Math.floor(options.market_cap_cr.min)) : FALLBACK_CAP.min,
    max: options?.market_cap_cr.max ? Math.ceil(options.market_cap_cr.max) : FALLBACK_CAP.max,
  };
  const sectors = useMemo(() => (options?.sectors ?? []).filter((s) => s.toLowerCase().includes(secQ.trim().toLowerCase())), [options, secQ]);
  const periods = options?.ma_periods ?? [10, 20, 50, 100, 200];

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const patch = (p: Partial<ScanFilters>) => setF((s) => ({ ...s, ...p }));
  const setRange = (k: string, v: { on: boolean; min: number | null; max: number | null }) => setF((s) => ({ ...s, ranges: { ...s.ranges, [k]: v } }));
  const mc = f.ranges[MCAP_KEY];
  const mcMin = mc.min ?? bounds.min;
  const mcMax = mc.max ?? bounds.max;
  const flash = (t: string) => {
    setNote(t);
    setTimeout(() => setNote(""), 2500);
  };
  const doSave = () => {
    const n = name.trim();
    if (!n) return;
    saveFilter({ name: n, pattern: pattern.id, filters: f, isDefault: asDefault });
    setSaved(loadSaved());
    setMenu(null);
    setName("");
    flash(`Saved “${n}”`);
  };
  const doShare = async () => {
    try {
      await navigator.clipboard.writeText(shareCode(pattern.id, f));
      flash("Share code copied. Paste it into Load > Import on any browser.");
    } catch {
      flash("Could not copy the share code.");
    }
  };
  const doImport = () => {
    const code = window.prompt("Paste a share code");
    const got = code ? parseShareCode(code) : null;
    if (got) {
      setF(got.filters);
      setMenu(null);
      flash("Filters imported");
    } else if (code) flash("That is not a valid share code.");
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[4vh]" role="dialog" aria-modal="true" aria-label={`${pattern.name} filters`}>
      <div className="absolute inset-0" style={{ background: "var(--backdrop)", backdropFilter: "blur(6px)" }} onMouseDown={onClose} />
      <div className="relative w-full max-w-[760px]">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close filters"
          title="Close (Esc)"
          className="absolute -right-3 -top-3 z-10 flex h-7 w-7 items-center justify-center rounded-full text-white transition-transform duration-150 hover:scale-110"
          style={{ background: "#ef6c35", boxShadow: "0 4px 14px rgba(239, 108, 53, 0.45)" }}
        >
          <X className="h-4 w-4" strokeWidth={2.5} />
        </button>
        <div
          className="flex w-full flex-col overflow-hidden rounded-2xl border"
          style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-md)", maxHeight: "92vh" }}
        >
          <div className="border-b px-6 pb-0 pt-5" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-tertiary)" }}>Filters · {pattern.category}</div>
                <h2 className="mt-1 text-xl font-semibold">{pattern.name}</h2>
              </div>
              <div className="relative flex items-center gap-2">
                <button type="button" onClick={doShare} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  <Share2 className="h-3.5 w-3.5" /> Share
                </button>
                <button type="button" onClick={() => setMenu(menu === "save" ? null : "save")} className="rounded-lg px-3 py-1.5 text-xs font-medium text-white" style={{ background: "var(--btn-primary-bg)" }}>
                  Save
                </button>
                <button type="button" onClick={() => setMenu(menu === "load" ? null : "load")} className="flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-medium" style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
                  Load <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {menu === "save" && (
                  <div className="absolute right-0 top-11 z-20 w-72 rounded-xl border p-4 shadow-lg" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
                    <div className="mb-2 text-sm font-semibold">Save filter</div>
                    <input
                      autoFocus
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && doSave()}
                      placeholder="Filter name"
                      aria-label="Filter name"
                      className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                      style={box}
                    />
                    <div className="mt-2"><Tick checked={asDefault} label="Set as default filter" onChange={setAsDefault} /></div>
                    <div className="mt-3 flex justify-end gap-2">
                      <button type="button" onClick={() => setMenu(null)} className="rounded-lg px-3 py-1.5 text-xs" style={{ color: "var(--text-secondary)" }}>Cancel</button>
                      <button type="button" onClick={doSave} disabled={!name.trim()} className="rounded-lg px-4 py-1.5 text-xs font-medium text-white disabled:opacity-40" style={{ background: "var(--btn-primary-bg)" }}>Save</button>
                    </div>
                  </div>
                )}
                {menu === "load" && (
                  <div className="absolute right-0 top-11 z-20 w-72 rounded-xl border p-2 shadow-lg" style={{ background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
                    {saved.length === 0 && <div className="px-3 py-2 text-xs" style={{ color: "var(--text-tertiary)" }}>No saved filters yet.</div>}
                    {saved.map((s) => (
                      <div key={s.name} className="flex items-center justify-between gap-2 rounded-lg px-3 py-1.5 hover:bg-[var(--overlay-weak)]">
                        <button type="button" className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => { setF(s.filters); setMenu(null); flash(`Loaded “${s.name}”`); }}>
                          {s.name}{s.isDefault && <span className="ml-1.5 text-[10px] uppercase" style={{ color: "var(--text-tertiary)" }}>default</span>}
                        </button>
                        <button type="button" aria-label={`Delete ${s.name}`} onClick={() => { deleteSaved(s.name); setSaved(loadSaved()); }} style={{ color: "var(--text-tertiary)" }}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                    <button type="button" onClick={doImport} className="mt-1 w-full rounded-lg px-3 py-1.5 text-left text-xs font-medium hover:bg-[var(--overlay-weak)]" style={{ color: "var(--accent-text, #b7b4e7)" }}>
                      Import a share code…
                    </button>
                  </div>
                )}
              </div>
            </div>
            <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }} title={pattern.definition}>{pattern.definition}</p>
            {note && <p className="mt-1 text-xs" style={{ color: "var(--accent-text, #b7b4e7)" }} role="status">{note}</p>}
            <div className="mt-3 flex gap-1" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className="rounded-t-lg border border-b-0 px-4 py-2 text-sm font-medium transition-colors"
                  style={{
                    borderColor: tab === t.id ? "var(--accent-border)" : "transparent",
                    background: tab === t.id ? "var(--accent-surface)" : "transparent",
                    color: tab === t.id ? "var(--accent)" : "var(--text-secondary)",
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-y-auto">
            {tab === "technicals" && (
              <>
                <MaSection title="EMA" periods={periods} value={f.ema} onChange={(v) => patch({ ema: v })} />
                <MaSection title="DMA" periods={periods} value={f.dma} onChange={(v) => patch({ dma: v })} />

                <Section title="Market cap" hint="Type a value or slide (₹ crore)" right={mc.on ? <button type="button" onClick={() => setRange(MCAP_KEY, { on: false, min: null, max: null })} className="text-xs font-medium" style={{ color: "var(--accent-text, #b7b4e7)" }}>Clear</button> : undefined}>
                  <div className="flex gap-3">
                    {([["Minimum", mc.min, "min"], ["Maximum", mc.max, "max"]] as const).map(([lab, val, key]) => (
                      <label key={key} className="flex-1 text-xs" style={{ color: "var(--text-tertiary)" }}>
                        {lab}
                        <div className="mt-1 flex items-center rounded-lg border px-3 py-2" style={box}>
                          <span className="mr-1.5 text-sm" style={{ color: "var(--text-tertiary)" }}>₹</span>
                          <input
                            inputMode="numeric"
                            placeholder="Any"
                            value={val ?? ""}
                            onChange={(e) => {
                              const t = e.target.value.replace(/[^\d]/g, "");
                              const v = t === "" ? null : Number(t);
                              setRange(MCAP_KEY, { ...mc, on: v != null || (key === "min" ? mc.max : mc.min) != null, [key]: v });
                            }}
                            className="w-full bg-transparent text-sm outline-none"
                          />
                          <span className="ml-1.5 text-xs">Cr</span>
                        </div>
                      </label>
                    ))}
                  </div>
                  <div className="mt-4 space-y-2.5">
                    {([
                      ["Min", mcMin, (v: number) => setRange(MCAP_KEY, { ...mc, on: true, min: v <= bounds.min ? null : v })],
                      ["Max", mcMax, (v: number) => setRange(MCAP_KEY, { ...mc, on: true, max: v >= bounds.max ? null : v })],
                    ] as const).map(([lab, val, setVal]) => (
                      <div key={lab} className="flex items-center gap-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
                        <span className="w-7">{lab}</span>
                        <input
                          type="range"
                          min={0}
                          max={SLIDER_STEPS}
                          value={toPos(val, bounds.min, bounds.max)}
                          onChange={(e) => setVal(toValue(Number(e.target.value), bounds.min, bounds.max))}
                          aria-label={`${lab} market cap`}
                          className="h-1.5 flex-1 cursor-pointer accent-[#b7b4e7]"
                        />
                        <span className="w-24 text-right tabular-nums" style={{ color: "var(--text-secondary)" }}>₹{val.toLocaleString("en-IN")} Cr</span>
                      </div>
                    ))}
                  </div>
                  {mc.min != null && mc.max != null && mc.min > mc.max && <p className="mt-2 text-xs" style={{ color: "#f5a9a9" }}>Minimum is above the maximum, so nothing can match.</p>}
                </Section>

                <Section title="Price and strength" hint="Tick a row to use it">
                  <RangeList tab="technicals" f={f} set={setRange} />
                  <Row on={f.nearHigh.on} onToggle={(on) => patch({ nearHigh: { ...f.nearHigh, on } })}>
                    <span>Made a new 52-week high within the last</span>
                    <Pick label="Sessions" value={f.nearHigh.sessions} onChange={(sessions) => patch({ nearHigh: { on: true, sessions } })}
                      options={(options?.near_high_sessions ?? [1, 5, 10, 21, 63, 126]).map((v) => ({ v, label: v === 1 ? "session (today)" : `${v} sessions` }))} />
                  </Row>
                </Section>

                <Section title="Trend and volatility" hint="Moving-average order, trend age and daily range">
                  <Row on={f.maOrder.on} onToggle={(on) => patch({ maOrder: { ...f.maOrder, on } })} hint="Each average at or above the next, e.g. 20 ≥ 50 ≥ 200">
                    <span>MA order</span>
                    <Pick label="Average type" value={f.maOrder.kind} onChange={(kind) => patch({ maOrder: { ...f.maOrder, on: true, kind } })} options={[{ v: "sma", label: "SMA" }, { v: "ema", label: "EMA" }]} />
                    {f.maOrder.periods.map((p, i) => (
                      <span key={i} className="inline-flex items-center gap-2">
                        {i > 0 && <span style={{ color: "var(--text-tertiary)" }}>≥</span>}
                        <Pick label={`Average ${i + 1}`} value={p} onChange={(v) => { const next = [...f.maOrder.periods] as [number, number, number]; next[i] = v; patch({ maOrder: { ...f.maOrder, on: true, periods: next } }); }} options={periods.map((v) => ({ v, label: `${v} MA` }))} />
                      </span>
                    ))}
                  </Row>
                  <Row on={f.uptrend.on} onToggle={(on) => patch({ uptrend: { ...f.uptrend, on } })}>
                    <Pick label="Average" value={f.uptrend.period} onChange={(period) => patch({ uptrend: { ...f.uptrend, on: true, period } })} options={(options?.uptrend.periods ?? [20, 50, 100, 200]).map((v) => ({ v, label: `${v} days MA` }))} />
                    <span>has been rising for at least</span>
                    <Pick label="Months" value={f.uptrend.months} onChange={(months) => patch({ uptrend: { ...f.uptrend, on: true, months } })} options={(options?.uptrend.months ?? [1, 2, 3, 6]).map((v) => ({ v, label: `${v} month${v > 1 ? "s" : ""}` }))} />
                  </Row>
                  <Row on={f.adr.on} onToggle={(on) => patch({ adr: { ...f.adr, on } })} hint="Average daily range: (high / low - 1) in %">
                    <Pick label="ADR days" value={f.adr.days} onChange={(days) => patch({ adr: { ...f.adr, on: true, days } })} options={(options?.adr_days ?? [5, 10, 20, 30]).map((v) => ({ v, label: `${v} days` }))} />
                    <span>average daily range % &gt;</span>
                    <Num value={f.adr.min} onChange={(min) => patch({ adr: { ...f.adr, on: true, min } })} placeholder="e.g. 3" width="w-20" />
                  </Row>
                  <Row on={f.rrg.on} onToggle={(on) => patch({ rrg: { ...f.rrg, on } })} hint="Sector rotation: where the stock's sector sits against the benchmark">
                    <span>Sector is</span>
                    {QUADRANTS.map((q) => (
                      <button
                        key={q.id}
                        type="button"
                        onClick={() => patch({ rrg: { ...f.rrg, on: true, quadrants: toggle(f.rrg.quadrants, q.id, !f.rrg.quadrants.includes(q.id)) } })}
                        className="rounded-full border px-3 py-1 text-xs font-medium transition-colors"
                        style={{
                          borderColor: f.rrg.quadrants.includes(q.id) ? "var(--accent-border)" : "var(--border-default)",
                          background: f.rrg.quadrants.includes(q.id) ? "var(--accent-surface)" : "transparent",
                          color: f.rrg.quadrants.includes(q.id) ? "var(--accent)" : "var(--text-secondary)",
                        }}
                      >
                        {q.label}
                      </button>
                    ))}
                    <span>on</span>
                    <Pick label="Timeframe" value={f.rrg.timeframe} onChange={(timeframe) => patch({ rrg: { ...f.rrg, on: true, timeframe } })} options={[{ v: "daily", label: "Daily" }, { v: "weekly", label: "Weekly" }]} />
                    <span>vs</span>
                    <Pick label="Benchmark" value={f.rrg.benchmark} onChange={(benchmark) => patch({ rrg: { ...f.rrg, on: true, benchmark } })} options={(options?.rrg.benchmarks ?? [{ id: "nifty50", label: "Nifty 50" }]).map((b) => ({ v: b.id as "nifty50" | "nifty500", label: b.label }))} />
                    {options && !options.rrg.available && <span className="text-xs" style={{ color: "#f5a9a9" }}>Benchmark data arrives with the next market scan.</span>}
                  </Row>
                </Section>

              </>
            )}

            {tab === "resistance" && (
              <Section
                title="Horizontal resistance"
                hint="Stocks pressing on a price level that at least three separate highs have touched"
              >
                {pattern.id === RESISTANCE_ID ? (
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>This scan always requires a horizontal resistance.</p>
                ) : (
                  <Row on={f.resistance.on} onToggle={(on) => patch({ resistance: { ...f.resistance, on } })}>
                    <span>Show horizontal resistance stocks only</span>
                  </Row>
                )}
                <div className="mt-1 flex flex-wrap gap-1 pl-7">
                  {(options?.resistance_states ?? [{ id: "near", label: "Near (up to 5% below)" }, { id: "breakout", label: "Breakout (last 3 sessions)" }]).map((st) => (
                    <Tick key={st.id} checked={f.resistance.states.includes(st.id as "near" | "breakout")} label={st.label}
                      onChange={(on) => patch({ resistance: { ...f.resistance, states: toggle(f.resistance.states, st.id as "near" | "breakout", on) } })} />
                  ))}
                </div>
                <p className="mt-4 text-xs leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  A resistance is a price zone that at least three separate highs touched within 2% of each other, with the first and last touch at least
                  15 sessions apart, and that no close has cleared since the first touch. <b>Near</b>: the price is up to 5% under it.
                  <b> Breakout</b>: it closed up to 3% above it, the first close above coming in the last 3 sessions. With this on, the charts draw
                  the level as a red line, and a stock opened from the results shows the same line on its price chart.
                </p>
              </Section>
            )}

            {tab === "fundamentals" && (
              <Section title="Fundamentals" hint={fundamentalsHint(options)}>
                <RangeList tab="fundamentals" f={f} set={setRange} />
              </Section>
            )}

            {tab === "misc" && (
              <>
                <Section
                  title="Indices"
                  hint="Official NSE index membership"
                  right={<SelectAll label="indices" total={options?.indices.length ?? 0} selected={f.indices.values.length} onAll={() => patch({ indices: { values: (options?.indices ?? []).map((i) => i.id) } })} onNone={() => patch({ indices: { values: [] } })} />}
                >
                  <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                    {(options?.indices ?? []).map((i) => (
                      <Tick key={i.id} checked={f.indices.values.includes(i.id)} label={i.label} onChange={(on) => patch({ indices: { values: toggle(f.indices.values, i.id, on) } })} />
                    ))}
                    {!options && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading…</span>}
                  </div>
                </Section>
                <Section
                  title="Sectors"
                  right={<SelectAll label="sectors" total={options?.sectors.length ?? 0} selected={f.sectors.values.length} onAll={() => patch({ sectors: { values: [...(options?.sectors ?? [])] } })} onNone={() => patch({ sectors: { values: [] } })} />}
                >
                  <input
                    value={secQ}
                    onChange={(e) => setSecQ(e.target.value)}
                    placeholder="Search sectors"
                    aria-label="Search sectors"
                    className="mb-2 w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none"
                    style={{ borderColor: "var(--border-default)" }}
                  />
                  <div className="grid max-h-52 grid-cols-1 gap-x-4 overflow-y-auto sm:grid-cols-2">
                    {sectors.map((s) => (
                      <Tick key={s} checked={f.sectors.values.includes(s)} label={s} onChange={(on) => patch({ sectors: { values: toggle(f.sectors.values, s, on) } })} />
                    ))}
                    {options && sectors.length === 0 && <span className="px-2 py-1 text-xs" style={{ color: "var(--text-tertiary)" }}>No sector matches.</span>}
                  </div>
                </Section>
                {!special && (
                  <Section
                    title="Pattern status"
                    hint="Where the formation is right now"
                    right={<SelectAll label="statuses" total={options?.statuses.length ?? 0} selected={f.status.values.length} onAll={() => patch({ status: { values: (options?.statuses ?? []).map((x) => x.id) } })} onNone={() => patch({ status: { values: [] } })} />}
                  >
                    <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                      {(options?.statuses ?? []).map((s) => (
                        <Tick key={s.id} checked={f.status.values.includes(s.id)} label={s.label} onChange={(on) => patch({ status: { values: toggle(f.status.values, s.id, on) } })} />
                      ))}
                    </div>
                  </Section>
                )}
                <Section title="Returns, volume and volatility" hint="Tick a row to use it">
                  <RangeList tab="misc" f={f} set={setRange} />
                </Section>
              </>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t px-6 py-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <button type="button" onClick={() => setF(emptyFilters())} className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              Reset
            </button>
            <button
              type="button"
              onClick={() => onApply(pattern.id === RESISTANCE_ID ? { ...f, resistance: { ...f.resistance, on: true } } : f)}
              className="rounded-lg px-8 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[var(--btn-primary-hover)]"
              style={{ background: "var(--btn-primary-bg)", boxShadow: "var(--shadow-accent)" }}
            >
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { SCREENER_ID };


/** The note above the Fundamentals filters: where they come from, for how many stocks, and how recent they are. */
function fundamentalsHint(o: ScanOptions | null): string {
  const have = o?.fundamentals_have ?? 0;
  let age = "";
  if (o?.fundamentals_as_of) {
    const d = new Date(o.fundamentals_as_of * 1000);
    const hrs = (Date.now() - d.getTime()) / 3600000;
    age = ` Updated ${d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true })}${hrs > 36 ? " (refresh under way)" : ""}.`;
  }
  const stale = o?.fundamentals_stale ? ` ${o.fundamentals_stale} stocks are being refreshed and may show last results.` : "";
  const yahoo = o?.fundamentals_yahoo ? ` ${o.fundamentals_yahoo} stocks use Yahoo Finance for P/E and dividend yield (Screener had no figures for them).` : "";
  return `From Screener.in, refreshed daily. Known for ${have} scanned stocks; a stock without a value is left out when you filter on it.${age}${stale}${yahoo}`;
}
