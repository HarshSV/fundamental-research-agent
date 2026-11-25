"use client";

import { Eye, EyeOff, Magnet, MousePointer2, Redo2, Ruler, Square, SeparatorVertical, Trash2, TrendingUp, Type, Undo2, Minus, MoveUpRight, ChartNoAxesGantt } from "lucide-react";
import type { ComponentType } from "react";
import { COLORS, TOOLS, type DrawLayer, type Tool } from "./drawLayer";

const ICON: Record<Tool, ComponentType<{ className?: string }>> = {
  cursor: MousePointer2,
  trend: TrendingUp,
  ray: MoveUpRight,
  hline: Minus,
  vline: SeparatorVertical,
  rect: Square,
  fib: ChartNoAxesGantt,
  text: Type,
  measure: Ruler,
};

export interface DrawState {
  tool: Tool;
  magnet: boolean;
  hidden: boolean;
  color: string;
}

/** The drawing tools' bar that sits to the left of the price chart (a row above it on a narrow screen). */
export function DrawToolbar({ state, onChange, layer, height }: { state: DrawState; onChange: (s: DrawState) => void; layer: DrawLayer | null; height?: number }) {
  const btn = "flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[var(--overlay-weak)]";
  const on = (active: boolean): React.CSSProperties => ({ background: active ? "var(--overlay)" : "transparent", color: active ? "var(--text-primary)" : "var(--text-secondary)" });
  const next = () => COLORS[(COLORS.indexOf(state.color) + 1) % COLORS.length];
  return (
    <div className="flex shrink-0 flex-row items-center gap-0.5 overflow-x-auto rounded-lg border p-1 sm:grid sm:grid-cols-2 sm:content-start sm:overflow-y-auto" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-1)", maxHeight: height }} role="toolbar" aria-label="Drawing tools">
      {TOOLS.map((t) => {
        const Icon = ICON[t.id];
        return (
          <button key={t.id} type="button" className={btn} style={on(state.tool === t.id)} title={`${t.label}: ${t.hint}`} aria-pressed={state.tool === t.id} aria-label={t.label} onClick={() => onChange({ ...state, tool: t.id })}>
            <Icon className="h-4 w-4" />
          </button>
        );
      })}
      <span className="mx-1 h-px w-5 self-center sm:col-span-2 sm:mx-0 sm:my-1 sm:w-full" style={{ background: "var(--border-subtle)" }} aria-hidden />
      <button type="button" className={btn} style={on(state.magnet)} title="Magnet: snap to a candle's open, high, low or close" aria-pressed={state.magnet} aria-label="Magnet" onClick={() => onChange({ ...state, magnet: !state.magnet })}>
        <Magnet className="h-4 w-4" />
      </button>
      <button type="button" className={btn} title="Colour of new drawings (and of the selected one). Click for the next colour" aria-label="Drawing colour" onClick={() => onChange({ ...state, color: next() })}>
        <span className="h-4 w-4 rounded-full border" style={{ background: state.color, borderColor: "var(--border-default)" }} />
      </button>
      <button type="button" className={btn} style={on(state.hidden)} title={state.hidden ? "Show drawings" : "Hide drawings"} aria-pressed={state.hidden} aria-label="Hide drawings" onClick={() => onChange({ ...state, hidden: !state.hidden })}>
        {state.hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
      <span className="mx-1 h-px w-5 self-center sm:col-span-2 sm:mx-0 sm:my-1 sm:w-full" style={{ background: "var(--border-subtle)" }} aria-hidden />
      <button type="button" className={btn} style={on(false)} title="Undo (Ctrl+Z over the chart)" aria-label="Undo" onClick={() => layer?.undoDrawing()}>
        <Undo2 className="h-4 w-4" />
      </button>
      <button type="button" className={btn} style={on(false)} title="Redo (Ctrl+Y over the chart)" aria-label="Redo" onClick={() => layer?.redoDrawing()}>
        <Redo2 className="h-4 w-4" />
      </button>
      <button type="button" className={btn} style={on(false)} title="Delete the selected drawing (Delete key)" aria-label="Delete selected" onClick={() => layer?.deleteSelected()}>
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}
