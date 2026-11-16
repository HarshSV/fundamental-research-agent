"use client";

import { SlidingTabs } from "./controls";
import { navigateTo } from "./scanners";

export type SectorTab = "sectors" | "history" | "outlook" | "industries" | "rrg" | "breadth" | "indices" | "gainers" | "losers";

const OPTIONS: { id: SectorTab; label: string }[] = [
  { id: "sectors", label: "Sectors" },
  { id: "history", label: "Sector History" },
  { id: "outlook", label: "Sector Outlook" },
  { id: "industries", label: "Industries" },
  { id: "rrg", label: "RRG" },
  { id: "breadth", label: "Breadth" },
  { id: "indices", label: "Sector Indices" },
  { id: "gainers", label: "Top Gainers" },
  { id: "losers", label: "Top Losers" },
];

/** The one row of toggles at the top of every Sector Analytics page (the pages behind Sector Indices, Top Gainers and Top Losers share it). */
export function AnalyticsTabs({ value }: { value: SectorTab }) {
  const go = (t: SectorTab) => {
    if (t === "indices") navigateTo({ type: "feed", name: "sector-indices" });
    else if (t === "gainers") navigateTo({ type: "scanner", id: "top-gainers" });
    else if (t === "losers") navigateTo({ type: "scanner", id: "top-losers" });
    else navigateTo({ type: "analytics", tab: t });
  };
  return (
    <div className="mb-6 mt-1 max-w-full overflow-x-auto">
      <SlidingTabs ariaLabel="Sector analytics" value={value} onChange={go} options={OPTIONS} />
    </div>
  );
}

/** True for a page that belongs to the Sector Analytics toggles (so moving between them replaces the page instead of stacking). */
export const isAnalyticsFamily = (v: { kind: string; name?: string; pattern?: string }) =>
  v.kind === "analytics" || (v.kind === "feed" && v.name === "sector-indices") || (v.kind === "patternScan" && (v.pattern === "top-gainers" || v.pattern === "top-losers"));
