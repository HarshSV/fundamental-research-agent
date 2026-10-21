"use client";

import { useEffect, useState } from "react";
import { AUTH_EVENT, checkSession, login } from "@/lib/api";

type State = "checking" | "out" | "in";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>("checking");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const refresh = () => checkSession().then((ok) => setState(ok ? "in" : "out"));
    refresh();
    window.addEventListener(AUTH_EVENT, refresh);
    return () => window.removeEventListener(AUTH_EVENT, refresh);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(password);
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "in") return <>{children}</>;
  if (state === "checking") return <div className="flex-1" />;

  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-xl border p-6"
        style={{ background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-md)" }}
      >
        <h1 className="mb-1 text-xl font-bold">NAVRIST AI</h1>
        <p className="mb-5 text-xs" style={{ color: "var(--text-tertiary)" }}>
          Enter the site password to continue.
        </p>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          className="mb-3 h-11 w-full rounded-lg border px-3 text-sm outline-none"
          style={{ background: "var(--surface-0)", borderColor: "var(--border-default)" }}
        />
        {error && (
          <p className="mb-3 text-xs" style={{ color: "#f5a9a9" }}>
            {error}
          </p>
        )}
        <button
          disabled={busy || !password}
          className="h-11 w-full rounded-lg text-sm text-white disabled:opacity-50"
          style={{ background: "var(--btn-primary-bg)" }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
