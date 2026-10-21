"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchScreens, startUniverseBuild, type ScreensResponse } from "./screens";

const ALL = "All";

/** Popular Screens: tabs filter the cards by group; each card opens the stocks that match its criteria. */
export function PopularScreens({ onOpen }: { onOpen: (screenId: string) => void }) {
  const [tab, setTab] = useState(ALL);
  const [data, setData] = useState<ScreensResponse | null>(null);
  const [error, setError] = useState("");
  const triggered = useRef(false);

  // Load the screens. While the backend is still preparing the universe, poll so counts fill in.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = () =>
      fetchScreens()
        .then(async (d) => {
          if (!alive) return;
          setData(d);
          setError("");
          if (d.universe.have === 0 && !d.universe.building && !triggered.current) {
            triggered.current = true; // first visit on a fresh install: start the one-off background build
            await startUniverseBuild().catch(() => {});
          }
          if (d.universe.building || d.universe.have === 0) timer = setTimeout(load, 8000);
        })
        .catch((e: Error) => alive && setError(e.message));
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const tabs = useMemo(() => [...(data?.groups ?? []), ALL], [data]);
  const shown = useMemo(
    () => (data?.screens ?? []).filter((s) => tab === ALL || s.group === tab),
    [data, tab],
  );

  return (
    <section className="pb-8">
      <div className="mb-5 flex items-center gap-3">
        <div className="h-6 w-1 rounded-full" style={{ background: "var(--gold)" }} />
        <h2 className="text-xl font-semibold">Popular Screens</h2>
      </div>
      <div className="no-scrollbar mb-6 flex items-end overflow-x-auto border-b" style={{ borderColor: "var(--border-subtle)" }}>
        {(tabs.length > 1 ? tabs : ["Loading…"]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="relative shrink-0 whitespace-nowrap px-4 py-2.5 text-sm transition-all"
            style={{
              fontWeight: tab === t ? 600 : 400,
              color: tab === t ? "var(--accent)" : "var(--text-secondary)",
            }}
          >
            {t}
            {tab === t && <div className="absolute inset-x-0 bottom-0 h-[2.5px] rounded-t-full" style={{ background: "var(--accent)" }} />}
          </button>
        ))}
      </div>

      {data && data.universe.building && (
        <p className="mb-4 text-xs" style={{ color: "var(--text-tertiary)" }}>
          Preparing screening data… {data.universe.done}/{data.universe.total} companies. Counts update as it progresses.
        </p>
      )}
      {error && <p className="mb-4 text-sm" style={{ color: "#f5a9a9" }}>Could not load screens: {error}</p>}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {shown.map((s) => (
          <button
            key={s.id}
            onClick={() => onOpen(s.id)}
            className="group rounded-xl border p-5 text-left transition-all hover:border-[var(--accent-border)]"
            style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-md)" }}
          >
            <h3 className="mb-3 pr-2 text-sm font-medium transition-colors group-hover:text-[var(--accent)]">{s.title}</h3>
            <p className="mb-4 text-xs leading-relaxed" style={{ color: "var(--text-tertiary)" }}>{s.description}</p>
            <div className="flex items-center justify-between text-xs">
              <span style={{ color: "var(--text-tertiary)" }}>
                {s.count == null ? "Preparing…" : `${s.count} stock${s.count === 1 ? "" : "s"}`}
              </span>
              <span style={{ color: "var(--accent)" }}>Open</span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
