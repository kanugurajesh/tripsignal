"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, money, ROUTE_LABEL, type CaseRow, type Overview, type Route } from "@/lib/api";
import { Code, ErrorBox, RouteBadge, Severity, Skeleton, StatusPill } from "@/components/ui";

const ACTIVE = ["OPEN", "AWAITING_APPROVAL", "ACTION_EXECUTED"];
const SEV_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };
type Scope = "active" | "closed" | "all";

export default function QueuePage() {
  const [cases, setCases] = useState<CaseRow[] | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [route, setRoute] = useState<Route | "ALL">("ALL");
  const [scope, setScope] = useState<Scope>("active");
  const [sev, setSev] = useState<string>("");
  const [q, setQ] = useState("");

  useEffect(() => {
    Promise.all([api<CaseRow[]>("/api/cases?limit=500"), api<Overview>("/api/overview")])
      .then(([c, o]) => { setCases(c); setOv(o); })
      .catch((e) => setErr(e.message));
  }, []);

  const rows = useMemo(() => {
    if (!cases) return [];
    const needle = q.trim().toLowerCase();
    return cases
      .filter((c) => route === "ALL" || c.route === route)
      .filter((c) => scope === "all" || (scope === "active" ? ACTIVE.includes(c.status) : !ACTIVE.includes(c.status)))
      .filter((c) => !sev || c.severity === sev)
      .filter((c) => !needle || [c.id, c.booking_id, c.hotel_id, c.guest_name, c.room_type, ...c.codes]
        .some((v) => (v ?? "").toLowerCase().includes(needle)))
      .sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity]
        || (a.days_to_deadline ?? 9999) - (b.days_to_deadline ?? 9999) || a.id.localeCompare(b.id));
  }, [cases, route, scope, sev, q]);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of cases ?? []) if (scope === "all" || (scope === "active") === ACTIVE.includes(c.status)) m[c.route] = (m[c.route] ?? 0) + 1;
    return m;
  }, [cases, scope]);

  if (err) return <ErrorBox error={err} />;

  const activeCount = cases?.filter((c) => ACTIVE.includes(c.status)).length ?? 0;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Exception queue</h1>
          <p className="text-sm text-slate-500">Each booking and supplier invoice is checked against the contract version in force on the booking date.</p>
        </div>
        {ov && <p className="text-xs text-slate-500">As of {ov.as_of} · {ov.total_cases} bookings audited</p>}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Open exceptions" value={cases ? String(activeCount) : "…"}
          sub={ov ? `${ov.by_status.AWAITING_APPROVAL ?? 0} awaiting approval` : ""} />
        <Kpi label="Detected overcharges (open)"
          value={ov ? Object.entries(ov.open_overcharge_exposure).map(([c, v]) => money(v, c)).join(" · ") || "None" : "…"}
          sub="Calculated from contracts, not yet confirmed by suppliers" small />
        <Kpi label="Disputes overdue or due ≤ 7 days" value={ov ? String(ov.disputes_due_within_7_days) : "…"}
          sub="Based on each contract's billing-dispute window" warn={!!ov && ov.disputes_due_within_7_days > 0} />
        <Kpi label="Credits recorded"
          value={ov ? Object.entries(ov.operator_reported_credits).map(([c, v]) => money(v, c)).join(" · ") || "None" : "…"}
          sub="Reported by operators; not checked against credit notes" small />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <div className="flex flex-wrap gap-1" role="tablist">
            {(["ALL", "ESCALATE", "SUPPLIER_QUERY", "REQUEST_INFO", "AUTO_CLEAR"] as const).map((r) => (
              <button key={r} role="tab" aria-selected={route === r} onClick={() => setRoute(r)}
                className={`rounded px-2.5 py-1 text-xs ${route === r ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {r === "ALL" ? "All" : ROUTE_LABEL[r]}
                <span className="ml-1 opacity-60">{r === "ALL" ? Object.values(counts).reduce((a, b) => a + b, 0) : counts[r] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value as Scope)}
              className="rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="active">Active</option><option value="closed">Closed / cleared</option><option value="all">All statuses</option>
            </select>
            <select aria-label="Severity" value={sev} onChange={(e) => setSev(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="">Any severity</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
            </select>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search booking, hotel, code…"
              className="w-56 rounded border border-slate-300 px-2 py-1 text-xs" />
          </div>
        </div>

        {!cases ? <div className="p-4"><Skeleton /></div> : rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-500">
            {cases.length === 0 ? <>No bookings have been audited yet. Run <Code>python -m app.seed</Code> to load demo data.</> : "No cases match these filters."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="px-3 py-2 font-medium">Case</th>
                  <th className="px-3 py-2 font-medium">Severity</th>
                  <th className="px-3 py-2 font-medium">Recommended route</th>
                  <th className="px-3 py-2 font-medium">Findings</th>
                  <th className="px-3 py-2 font-medium">Hotel · room</th>
                  <th className="px-3 py-2 text-right font-medium">Difference</th>
                  <th className="px-3 py-2 font-medium">Dispute by</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <Link href={`/cases/${c.id}`} className="font-medium text-slate-900 hover:underline">{c.id}</Link>
                      <div className="text-xs text-slate-500">{c.booking_id}{c.kind === "cancellation" && " · cancellation"}</div>
                    </td>
                    <td className="px-3 py-2"><Severity level={c.severity} /></td>
                    <td className="px-3 py-2"><RouteBadge route={c.route} /></td>
                    <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{c.codes.map((x) => <Code key={x}>{x}</Code>)}</div></td>
                    <td className="px-3 py-2 text-xs text-slate-700">{c.hotel_id}<div className="text-slate-500">{c.room_type ?? "—"} · {c.check_in ?? "—"}</div></td>
                    <td className={`px-3 py-2 text-right font-mono text-xs ${c.delta && Number(c.delta) > 1 ? "text-rose-700" : "text-slate-600"}`}>
                      {c.delta ? `${Number(c.delta) > 0 ? "+" : ""}${money(c.delta, c.currency)}` : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {c.dispute_deadline ? (
                        <span className={c.days_to_deadline !== null && c.days_to_deadline <= 7 && ACTIVE.includes(c.status) ? "font-medium text-rose-700" : "text-slate-600"}>
                          {c.dispute_deadline}
                          <div className="text-slate-500">{c.days_to_deadline! < 0 ? `${-c.days_to_deadline!}d overdue` : `${c.days_to_deadline}d left`}</div>
                        </span>
                      ) : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2"><StatusPill status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, warn, small }: { label: string; value: string; sub?: string; warn?: boolean; small?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 font-semibold tabular-nums ${small ? "text-base" : "text-2xl"} ${warn ? "text-rose-700" : "text-slate-900"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-snug text-slate-500">{sub}</div>}
    </div>
  );
}
