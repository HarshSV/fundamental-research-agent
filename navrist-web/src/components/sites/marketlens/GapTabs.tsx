"use client";

import { useEffect, useRef } from "react";
import { SlidingTabs } from "./controls";
import { navigateTo } from "./scanners";

/** The four gap lists, shown as one row of toggles on every one of their pages (the menu has a single "Gaps" entry). */
export const GAP_IDS = ["gap-up", "gap-down", "gap-filling", "gap-filling-down"] as const;
export type GapId = (typeof GAP_IDS)[number];
export const isGapId = (id: string): id is GapId => (GAP_IDS as readonly string[]).includes(id);

const OPTIONS: { id: GapId; label: string }[] = [
  { id: "gap-up", label: "Gap Up" },
  { id: "gap-down", label: "Gap Down" },
  { id: "gap-filling", label: "Gap Filling Up" },
  { id: "gap-filling-down", label: "Gap Filling Down" },
];

export function GapTabs({ value }: { value: GapId }) {
  const row = useRef<HTMLDivElement>(null);
  // on a narrow screen the row scrolls sideways: bring the chosen toggle into view
  useEffect(() => {
    const box = row.current;
    const on = box?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (box && on) box.scrollTo({ left: on.offsetLeft - (box.clientWidth - on.offsetWidth) / 2 });
  }, [value]);
  return (
    <div ref={row} className="mb-6 mt-1 max-w-full overflow-x-auto">
      <SlidingTabs ariaLabel="Gaps" value={value} onChange={(id) => navigateTo({ type: "scanner", id })} options={OPTIONS} />
    </div>
  );
}
