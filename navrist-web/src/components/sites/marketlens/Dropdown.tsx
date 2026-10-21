"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface DropdownOption {
  value: string;
  label: string;
  hint?: string; // right-aligned secondary text, e.g. a count
}

/**
 * Themed replacement for a native <select>. The browser draws a native select's list itself, so its
 * scrollbar can't be styled; this list is ordinary DOM and picks up the app's themed scrollbar.
 */
export function Dropdown({
  value, options, onChange, ariaLabel,
}: {
  value: string;
  options: DropdownOption[];
  onChange: (v: string) => void;
  ariaLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // keep the keyboard-highlighted row in view
  useEffect(() => {
    if (!open) return;
    list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const toggle = () => {
    if (!open) setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen((o) => !o);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") return setOpen(false);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return toggle();
      setActive((a) => Math.min(options.length - 1, Math.max(0, a + (e.key === "ArrowDown" ? 1 : -1))));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!open) return toggle();
      onChange(options[active].value);
      setOpen(false);
    }
  };

  return (
    <div ref={root} className="relative" onKeyDown={onKey}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={toggle}
        className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors"
        style={{
          borderColor: open ? "#b7b4e7" : "var(--border-default)",
          color: "var(--text-secondary)",
          background: open ? "#b7b4e71a" : "transparent",
        }}
      >
        <span className="max-w-[12rem] truncate">{current?.label}</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul
          ref={list}
          role="listbox"
          className="absolute left-0 top-full z-30 mt-2 max-h-72 min-w-[16rem] overflow-y-auto rounded-xl border p-1.5 text-xs"
          style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-md)" }}
        >
          {options.map((o, i) => {
            const selected = o.value === value;
            return (
              <li
                key={o.value}
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActive(i)}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className="flex cursor-pointer items-center justify-between gap-3 rounded-lg px-2.5 py-1.5"
                style={{
                  background: i === active ? "#b7b4e71f" : "transparent",
                  color: selected ? "#b7b4e7" : "var(--text-secondary)",
                }}
              >
                <span className="flex items-center gap-2">
                  <Check className={`h-3.5 w-3.5 ${selected ? "opacity-100" : "opacity-0"}`} />
                  {o.label}
                </span>
                {o.hint && <span className="nv-num" style={{ color: "var(--text-tertiary)" }}>{o.hint}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
