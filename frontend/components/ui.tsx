import type { Route, TravellerEvent } from "@/lib/api";
import { EVENT_LABEL, ROUTE_LABEL, STATUS_LABEL } from "@/lib/api";

const ROUTE_STYLE: Record<Route, string> = {
  AUTO_CLEAR: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  SUPPLIER_QUERY: "bg-sky-50 text-sky-800 ring-sky-200",
  REQUEST_INFO: "bg-amber-50 text-amber-800 ring-amber-200",
  ESCALATE: "bg-rose-50 text-rose-800 ring-rose-200",
};

export function RouteBadge({ route }: { route: Route }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${ROUTE_STYLE[route]}`}>
      {ROUTE_LABEL[route]}
    </span>
  );
}

export function EventTag({ event }: { event: TravellerEvent }) {
  return <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800 ring-1 ring-sky-200">{EVENT_LABEL[event] ?? event}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const done = ["RESOLVED", "DISMISSED", "AUTO_CLEARED"].includes(status);
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${done ? "text-slate-500" : "text-slate-800"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${done ? "bg-slate-300" : status === "AWAITING_APPROVAL" ? "bg-violet-500" : "bg-slate-700"}`} />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Severity({ level }: { level: string }) {
  const s = { high: "bg-rose-600", medium: "bg-amber-500", low: "bg-slate-300" }[level] ?? "bg-slate-300";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs capitalize text-slate-700">
      <span className={`h-2 w-2 rounded-sm ${s}`} />
      {level}
    </span>
  );
}

export function Code({ children }: { children: React.ReactNode }) {
  return <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{children}</span>;
}

export function Card({ title, right, children, className = "" }: { title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white ${className}`}>
      {title && (
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>;
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  );
}

export function Verified({ ok, reason }: { ok: boolean; reason?: string | null }) {
  return ok ? (
    <span className="text-[11px] font-medium text-emerald-700" title="Quote found verbatim in the source document">✓ verified</span>
  ) : (
    <span className="text-[11px] font-medium text-rose-700" title={reason ?? ""}>✗ unverified</span>
  );
}
