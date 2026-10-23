"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ACTORS, api, type Health } from "@/lib/api";
import { useActor } from "@/lib/actor";

const NAV = [
  { href: "/", label: "Exception queue" },
  { href: "/evals", label: "Evaluation" },
  { href: "/about", label: "How it works" },
];

function NavLinks() {
  const path = usePathname();
  return (
    <>
      {NAV.map((n) => {
        const active = n.href === "/" ? path === "/" || path.startsWith("/cases") : path.startsWith(n.href);
        return (
          <Link key={n.href} href={n.href}
            className={`rounded px-2.5 py-1 text-sm ${active ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}>
            {n.label}
          </Link>
        );
      })}
    </>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const { actor, setActor } = useActor();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    api<Health>("/api/health").then(setHealth).catch(() => setDown(true));
  }, []);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded bg-slate-900 text-[11px] font-bold text-white">TS</span>
            <span className="text-sm font-semibold text-slate-900">TripSignal</span>
            <span className="hidden text-xs text-slate-500 sm:inline">Contract rate assurance</span>
          </Link>
          <nav className="flex gap-1">
            <Suspense fallback={NAV.map((n) => <Link key={n.href} href={n.href} className="rounded px-2.5 py-1 text-sm text-slate-600">{n.label}</Link>)}>
              <NavLinks />
            </Suspense>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {health && (
              <span className="text-slate-500" title={health.demo_mode ? "Oracle mode replays ground-truth extractions from the synthetic dataset; no model is called." : ""}>
                {health.demo_mode ? (
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-900">Demo · oracle extraction</span>
                ) : (
                  <span className="font-mono">{health.provider}:{health.model}</span>
                )}
              </span>
            )}
            {down && <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-800">API offline</span>}
            <label className="flex items-center gap-1.5 text-slate-500">
              Acting as
              <select value={actor.id} onChange={(e) => setActor(ACTORS.find((a) => a.id === e.target.value)!)}
                className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-900">
                {ACTORS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              </select>
            </label>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-5">{children}</main>
    </div>
  );
}
