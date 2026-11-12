"use client";

import { Check, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface LineOption {
  id: string;
  label: string;
  hint?: string;
  color: string;
  /** why it cannot be drawn right now (no plan for this stock, intraday chart...) */
  disabled?: string;
}

export interface LineGroup {
  title: string;
  options: LineOption[];
  note?: string;
}

/** The chart's filter: a small button that opens a list of the lines the chart can draw, each switched on or off. Closes on a click elsewhere or Escape. */
export function ChartLinesMenu({ groups, on, onToggle, onReset, count }: { groups: LineGroup[]; on: Record<string, boolean>; onToggle: (id: string) => void; onReset: () => void; count: number }) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState(false);
  const [alignRight, setAlignRight] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const close = () => {
    setShown(false);
    setTimeout(() => setOpen(false), 180);
  };
  const toggle = () => {
    if (open) return close();
    // open towards the side with room: the button can sit at the left or the right of the controls row
    const r = box.current?.getBoundingClientRect();
    if (r) setAlignRight(r.left + r.width / 2 > window.innerWidth / 2);
    setOpen(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)));
  };
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && close();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  });
  return (
    <div ref={box} className="relative">
      <button
        onClick={toggle}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm hover:opacity-80"
        style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-1)" }}
      >
        <SlidersHorizontal className="h-4 w-4" aria-hidden />
        Chart lines
        {count > 0 && <span className="rounded-full px-1.5 text-[11px] font-semibold" style={{ background: "var(--accent-surface, var(--overlay))", color: "var(--accent)" }}>{count}</span>}
      </button>
      {open && (
        <div
          className={`absolute bottom-full z-30 mb-2 max-h-[26rem] w-[min(20rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border p-3 text-sm shadow-xl sm:bottom-auto sm:top-full sm:mb-0 sm:mt-2 ${alignRight ? "right-0" : "left-0"}`}
          style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", opacity: shown ? 1 : 0, transform: shown ? "none" : "translateY(-6px) scale(0.98)", transformOrigin: alignRight ? "top right" : "top left", transition: "opacity 180ms ease, transform 180ms ease" }}
        >
          {groups.map((g) => (
            <div key={g.title} className="mb-3 last:mb-1">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>{g.title}</div>
              {g.options.map((o) => {
                const checked = Boolean(on[o.id]) && !o.disabled;
                return (
                  <button
                    key={o.id}
                    type="button"
                    disabled={Boolean(o.disabled)}
                    onClick={() => onToggle(o.id)}
                    title={o.disabled}
                    className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left hover:bg-[var(--overlay-weak)] disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border" style={{ borderColor: checked ? o.color : "var(--border-default)", background: checked ? o.color : "transparent" }}>
                      {checked && <Check className="h-3 w-3" strokeWidth={3} style={{ color: "#fff" }} aria-hidden />}
                    </span>
                    <span className="h-0.5 w-4 shrink-0 rounded" style={{ background: o.color }} aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span style={{ color: "var(--text-primary)" }}>{o.label}</span>
                      {(o.disabled || o.hint) && <span className="block text-[11px]" style={{ color: "var(--text-tertiary)" }}>{o.disabled ?? o.hint}</span>}
                    </span>
                  </button>
                );
              })}
              {g.note && <p className="mt-1 px-1.5 text-[11px] leading-snug" style={{ color: "var(--text-tertiary)" }}>{g.note}</p>}
            </div>
          ))}
          <button type="button" onClick={onReset} className="mt-1 w-full rounded-md py-1.5 text-xs underline" style={{ color: "var(--text-secondary)" }}>Back to the default (today&apos;s plan only)</button>
        </div>
      )}
    </div>
  );
}
