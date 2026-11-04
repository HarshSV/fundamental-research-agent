"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ALERTS_EVENT, checkAlerts, loadAlerts, type Alert } from "./alerts";

/** Mounted once for the whole site: checks the saved alerts every 20 seconds and shows a plain message when one fires. */
export function AlertHost() {
  const [toasts, setToasts] = useState<Alert[]>([]);
  const busy = useRef(false);
  useEffect(() => {
    const run = async () => {
      if (busy.current || !loadAlerts().some((a) => !a.fired)) return;
      busy.current = true;
      try {
        const fired = await checkAlerts();
        if (fired.length) {
          setToasts((t) => [...t, ...fired]);
          if (typeof Notification !== "undefined" && Notification.permission === "granted") {
            for (const a of fired) new Notification("Navrist alert", { body: a.message });
          }
        }
      } finally {
        busy.current = false;
      }
    };
    run();
    const t = setInterval(run, 20000);
    window.addEventListener(ALERTS_EVENT, run);
    return () => {
      clearInterval(t);
      window.removeEventListener(ALERTS_EVENT, run);
    };
  }, []);
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((a) => (
        <div key={a.id} className="flex items-start gap-3 rounded-lg border p-3 text-sm shadow-lg"
          style={{ background: "var(--surface-1)", borderColor: a.kind === "stop" ? "var(--loss)" : a.kind === "target" ? "var(--gain)" : "var(--border-default)" }}>
          <span className="flex-1">{a.message}</span>
          <button onClick={() => setToasts((t) => t.filter((x) => x.id !== a.id))} aria-label="Dismiss" className="opacity-60 hover:opacity-100">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
