"use client";

import { Check, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CatalogueEntry } from "./patterns";
import { EMPTY_FILTERS, type ScanFilters, type ScanOptions } from "./patternScan";

const SLIDER_STEPS = 1000;
const FALLBACK_CAP = { min: 100, max: 2_000_000 }; // Rs crore, used only until the real bounds arrive

// the slider is logarithmic: market caps span five orders of magnitude, a linear slider would be unusable
const toValue = (pos: number, lo: number, hi: number) => Math.round(lo * Math.pow(hi / lo, pos / SLIDER_STEPS));
const toPos = (v: number, lo: number, hi: number) => Math.round((Math.log(Math.max(v, lo) / lo) / Math.log(hi / lo)) * SLIDER_STEPS);

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

const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? (list.includes(v) ? list : [...list, v]) : list.filter((x) => x !== v));

function NumberBox({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number | null) => void }) {
  return (
    <label className="flex-1 text-xs" style={{ color: "var(--text-tertiary)" }}>
      {label}
      <div className="mt-1 flex items-center rounded-lg border px-3 py-2" style={{ borderColor: "var(--border-default)", background: "var(--surface-2, var(--surface-1))" }}>
        <span className="mr-1.5 text-sm" style={{ color: "var(--text-tertiary)" }}>₹</span>
        <input
          inputMode="numeric"
          placeholder="Any"
          value={value ?? ""}
          onChange={(e) => {
            const t = e.target.value.replace(/[^\d]/g, "");
            onChange(t === "" ? null : Number(t));
          }}
          className="w-full bg-transparent text-sm outline-none"
          style={{ color: "var(--text-primary)" }}
        />
        <span className="ml-1.5 text-xs">Cr</span>
      </div>
    </label>
  );
}

/** Moving-average filter (EMA and DMA are two separate sections): which periods, price above or below, any / all. */
function MaSection({
  title, short, periods, value, onChange,
}: {
  title: string;
  short: string;
  periods: number[];
  value: ScanFilters["ema"];
  onChange: (v: ScanFilters["ema"]) => void;
}) {
  return (
    <Section
      title={title}
      hint={`Compares the latest close with the ${short} of the daily chart`}
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
          <Tick key={p} checked={value.periods.includes(p)} label={`${short} ${p}`} onChange={(on) => onChange({ ...value, periods: toggle(value.periods, p, on) })} />
        ))}
      </div>
    </Section>
  );
}

/**
 * The popup that opens when a pattern is picked: indices, market-cap range (typed or slid), EMA, DMA, sectors and
 * status, each list with an Any / All switch, then Apply. An empty selection means "no restriction".
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
  const [secQ, setSecQ] = useState("");
  const bounds = {
    min: options?.market_cap_cr.min ? Math.max(1, Math.floor(options.market_cap_cr.min)) : FALLBACK_CAP.min,
    max: options?.market_cap_cr.max ? Math.ceil(options.market_cap_cr.max) : FALLBACK_CAP.max,
  };
  const sectors = useMemo(() => (options?.sectors ?? []).filter((s) => s.toLowerCase().includes(secQ.trim().toLowerCase())), [options, secQ]);

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

  const set = <K extends keyof ScanFilters>(k: K, v: ScanFilters[K]) => setF((p) => ({ ...p, [k]: v }));
  const mcMin = f.mcap.min ?? bounds.min;
  const mcMax = f.mcap.max ?? bounds.max;
  const badRange = f.mcap.min != null && f.mcap.max != null && f.mcap.min > f.mcap.max;

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[5vh]" role="dialog" aria-modal="true" aria-label={`${pattern.name} filters`}>
      <div className="absolute inset-0" style={{ background: "var(--backdrop)", backdropFilter: "blur(6px)" }} onMouseDown={onClose} />
      <div className="relative w-full max-w-[680px]">
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
          style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-md)", maxHeight: "90vh" }}
        >
          <div className="border-b px-6 py-5" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-tertiary)" }}>Filters · {pattern.category}</div>
            <h2 className="mt-1 text-xl font-semibold">{pattern.name}</h2>
            <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }} title={pattern.definition}>{pattern.definition}</p>
          </div>

          <div className="overflow-y-auto">
            <Section
              title="Indices"
              hint="Official NSE index membership"
              right={<SelectAll label="indices" total={options?.indices.length ?? 0} selected={f.indices.values.length} onAll={() => set("indices", { values: (options?.indices ?? []).map((i) => i.id) })} onNone={() => set("indices", { values: [] })} />}
            >
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {(options?.indices ?? []).map((i) => (
                  <Tick key={i.id} checked={f.indices.values.includes(i.id)} label={i.label} onChange={(on) => set("indices", { values: toggle(f.indices.values, i.id, on) })} />
                ))}
                {!options && <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading…</span>}
              </div>
            </Section>

            <Section
              title="Market cap range"
              hint="Type a value or slide (₹ crore)"
              right={(f.mcap.min != null || f.mcap.max != null) ? (
                <button type="button" onClick={() => set("mcap", { min: null, max: null })} className="text-xs font-medium" style={{ color: "var(--accent-text, #b7b4e7)" }}>Clear</button>
              ) : undefined}
            >
              <div className="flex gap-3">
                <NumberBox label="Minimum" value={f.mcap.min} onChange={(v) => set("mcap", { ...f.mcap, min: v })} />
                <NumberBox label="Maximum" value={f.mcap.max} onChange={(v) => set("mcap", { ...f.mcap, max: v })} />
              </div>
              <div className="mt-4 space-y-2.5">
                {([
                  ["Min", mcMin, (v: number) => set("mcap", { ...f.mcap, min: v <= bounds.min ? null : v })],
                  ["Max", mcMax, (v: number) => set("mcap", { ...f.mcap, max: v >= bounds.max ? null : v })],
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
              {badRange && <p className="mt-2 text-xs" style={{ color: "#f5a9a9" }}>Minimum is above the maximum, so nothing can match.</p>}
            </Section>

            <MaSection title="EMA" short="EMA" periods={options?.ma_periods ?? [10, 20, 50, 100, 200]} value={f.ema} onChange={(v) => set("ema", v)} />
            <MaSection title="DMA" short="DMA" periods={options?.ma_periods ?? [10, 20, 50, 100, 200]} value={f.dma} onChange={(v) => set("dma", v)} />

            <Section
              title="Sectors"
              right={<SelectAll label="sectors" total={options?.sectors.length ?? 0} selected={f.sectors.values.length} onAll={() => set("sectors", { values: [...(options?.sectors ?? [])] })} onNone={() => set("sectors", { values: [] })} />}
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
                  <Tick key={s} checked={f.sectors.values.includes(s)} label={s} onChange={(on) => set("sectors", { values: toggle(f.sectors.values, s, on) })} />
                ))}
                {options && sectors.length === 0 && <span className="px-2 py-1 text-xs" style={{ color: "var(--text-tertiary)" }}>No sector matches.</span>}
              </div>
            </Section>

            <Section
              title="Pattern status"
              hint="Where the formation is right now"
              right={<SelectAll label="statuses" total={options?.statuses.length ?? 0} selected={f.status.values.length} onAll={() => set("status", { values: (options?.statuses ?? []).map((x) => x.id) })} onNone={() => set("status", { values: [] })} />}
            >
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {(options?.statuses ?? []).map((s) => (
                  <Tick key={s.id} checked={f.status.values.includes(s.id)} label={s.label} onChange={(on) => set("status", { values: toggle(f.status.values, s.id, on) })} />
                ))}
              </div>
            </Section>
          </div>

          <div className="flex items-center justify-between gap-3 border-t px-6 py-4" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)" }}>
            <button type="button" onClick={() => setF(EMPTY_FILTERS)} className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              Reset all
            </button>
            <button
              type="button"
              onClick={() => onApply(f)}
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
