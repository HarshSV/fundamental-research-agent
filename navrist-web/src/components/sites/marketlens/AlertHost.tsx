"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ALERTS_EVENT, fetchAlerts, type Alert } from "./alerts";

const SEEN = "navrist_alerts_seen";

/** Mounted once for the whole site: asks the server for fired alerts every 20 seconds and shows a plain message for new ones.
 *  (Telegram messages are sent by the server itself, whether or not this page is open.) */
export function AlertHost() {
  const [toasts, setToasts] = useState<Alert[]>([]);
  const busy = useRef(false);
  useEffect(() => {
    const run = async () => {
      if (busy.current) return;
      busy.current = true;
      try {
        const { alerts } = await fetchAlerts();
        let seen: string[] = [];
        try {
          seen = JSON.parse(localStorage.getItem(SEEN) ?? "[]");
        } catch {
          /* nothing seen yet */
        }
        const fresh = alerts.filter((a) => a.fired && Date.now() / 1000 - a.fired < 6 * 3600 && !seen.includes(a.id));
        if (fresh.length) {
          localStorage.setItem(SEEN, JSON.stringify([...seen, ...fresh.map((a) => a.id)].slice(-200)));
          setToasts((t) => [...t, ...fresh]);
          if (typeof Notification !== "undefined" && Notification.permission === "granted") {
            for (const a of fresh) new Notification("Navrist alert", { body: a.message });
          }
        }
      } catch {
        /* not signed in or the server is busy: try again at the next tick */
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
