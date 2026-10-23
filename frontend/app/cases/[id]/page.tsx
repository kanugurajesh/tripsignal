"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, money, type CaseDetail, type Evidence } from "@/lib/api";
import { useActor } from "@/lib/actor";
import { Card, Code, ErrorBox, RouteBadge, Severity, Skeleton, StatusPill, Verified } from "@/components/ui";
import DocumentViewer from "@/components/DocumentViewer";
import ActionPanel from "@/components/ActionPanel";

export default function CasePage() {
  return (
    <Suspense fallback={<Skeleton rows={10} />}>
      <CaseView />
    </Suspense>
  );
}

function CaseView() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<CaseDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [focus, setFocus] = useState<Evidence | null>(null);
  const { actor } = useActor();

  const load = useCallback(() => {
    api<CaseDetail>(`/api/cases/${id}`).then(setC).catch((e) => setErr(e.message));
  }, [id]);
  useEffect(load, [load]);

  if (err) return <ErrorBox error={err} />;
  if (!c) return <Skeleton rows={10} />;

  const r = c.result;
  const cur = r.currency;
  const allEvidence: Evidence[] = [...r.nights.map((n) => n.evidence), ...r.findings.flatMap((f) => f.evidence)];
  const n = c.narrative?.narrative;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/" className="text-xs text-slate-500 hover:underline">← Exception queue</Link>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-lg font-semibold text-slate-900">
            {c.id} <span className="text-sm font-normal text-slate-500">booking {String(c.booking.booking_id)} · {String(c.booking.hotel_id)}</span>
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <RouteBadge route={c.route} /><Severity level={c.severity} /><StatusPill status={c.status} />
            {c.days_to_deadline !== null && (
              <span className={`text-xs ${c.days_to_deadline <= 7 ? "font-medium text-rose-700" : "text-slate-600"}`}>
                Dispute deadline {c.dispute_deadline} ({c.days_to_deadline < 0 ? `${-c.days_to_deadline}d overdue` : `${c.days_to_deadline}d left`})
              </span>
            )}
          </div>
        </div>
        <div className="text-right text-xs text-slate-500">
          Extraction: <span className="font-mono">{c.provider}</span>
          {c.provider.startsWith("oracle") && <div className="text-amber-700">Demo: replays ground-truth extraction</div>}
        </div>
      </div>

      {Object.keys(c.injection).length > 0 && (
        <div className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
          <strong>Possible prompt injection.</strong> Text in{" "}
          {Object.keys(c.injection).join(", ")} looks like instructions to an automated system. It was treated as data only,
          and this case cannot be auto-cleared.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-7">
          <Card title="Recommendation" right={<NarrativeSource c={c} />}>
            {n ? (
              <div className="space-y-2 text-sm">
                <p className="text-slate-800">{n.summary}</p>
                <p className="font-medium text-slate-900">Next step: <span className="font-normal">{n.next_step}</span></p>
              </div>
            ) : <p className="text-sm text-slate-500">No narrative generated.</p>}
          </Card>

          <Card title={r.kind === "cancellation" ? "Cancellation fee check" : "Rate check"}>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <Amount label="Charged (supplier invoice)" value={money(r.charged_amount, cur)} />
              <Amount label="Contracted (calculated)" value={money(r.expected_amount, cur)} />
              <Amount label="Difference" value={r.delta ? `${Number(r.delta) > 0 ? "+" : ""}${money(r.delta, cur)}` : "—"}
                tone={r.delta && Math.abs(Number(r.delta)) > 1 ? "bad" : undefined} />
            </div>
            {r.expected_amount === null && (
              <p className="mt-3 text-xs text-slate-600">No contracted amount was calculated. The evidence needed to price this booking safely is missing, conflicting, or unverified, so the system abstained.</p>
            )}
            {r.nights.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-500"><tr className="border-b border-slate-100">
                    <th className="py-1.5 pr-2 font-medium">Night</th><th className="py-1.5 pr-2 text-right font-medium">Rate</th>
                    <th className="py-1.5 pr-2 font-medium">Source</th><th className="py-1.5 font-medium">Evidence</th></tr></thead>
                  <tbody>
                    {r.nights.map((x) => (
                      <tr key={x.night} className="cursor-pointer border-b border-slate-50 align-top hover:bg-amber-50/50"
                        onClick={() => setFocus(x.evidence)}>
                        <td className="py-1.5 pr-2 font-mono">{x.night}</td>
                        <td className="py-1.5 pr-2 text-right font-mono">{money(x.rate)}</td>
                        <td className="py-1.5 pr-2 font-mono text-slate-600">{x.document_id}</td>
                        <td className="py-1.5"><span className="text-slate-700">“{x.evidence.quote.replace(/\|/g, " ").trim()}”</span> <Verified ok={x.evidence.verified} reason={x.evidence.reason} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {Number(c.booking.rooms) > 1 && <p className="mt-1 text-xs text-slate-500">× {String(c.booking.rooms)} rooms</p>}
              </div>
            )}
          </Card>

          <Card title="Findings">
            <ul className="space-y-3">
              {r.findings.map((f, i) => (
                <li key={i} className="text-sm">
                  <div className="flex items-center gap-2"><Code>{f.code}</Code></div>
                  <p className="mt-1 text-slate-700">{f.message}</p>
                  {f.evidence.map((e, j) => (
                    <button key={j} onClick={() => setFocus(e)} className="mt-1 block text-left text-xs text-slate-600 hover:text-slate-900">
                      <span className="font-mono">{e.document_id} · {e.section}</span> “{e.quote.replace(/\|/g, " ").trim().slice(0, 140)}” <Verified ok={e.verified} reason={e.reason} />
                    </button>
                  ))}
                </li>
              ))}
            </ul>
            <details className="mt-4 text-xs text-slate-600">
              <summary className="cursor-pointer text-slate-500">Assumptions & applied documents</summary>
              <ul className="mt-2 list-disc space-y-1 pl-4">
                {r.assumptions.map((a) => <li key={a}>{a}</li>)}
                <li>Documents considered in force: {r.applied_documents.join(", ") || "none"}</li>
                {c.extraction_meta.filter((m) => !m.ok).map((m) => <li key={m.document_id} className="text-rose-700">{m.document_id}: {m.error}</li>)}
              </ul>
            </details>
          </Card>

          <ActionPanel key={`${c.status}-${c.actions.length}`} c={c} actor={actor} onChange={load} />

          <Card title="Booking record">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
              {Object.entries(c.booking).filter(([k]) => k !== "notes" && !(c.booking.status === "CANCELLED" ? k === "invoiced_total" : k.startsWith("cancellation"))).map(([k, v]) => (
                <div key={k}><dt className="text-slate-500">{k.replace(/_/g, " ")}</dt>
                  <dd className={`font-mono ${v === null ? "text-rose-700" : "text-slate-800"}`}>{v === null ? "missing" : String(v)}</dd></div>
              ))}
            </dl>
            {c.booking.notes && (
              <div className={`mt-3 rounded border p-2 text-xs ${c.injection[`booking ${c.booking.booking_id} notes`] ? "border-rose-300 bg-rose-50 text-rose-900" : "border-slate-200 text-slate-700"}`}>
                <span className="font-medium">Notes (untrusted):</span> {String(c.booking.notes)}
              </div>
            )}
          </Card>

          <Card title="History">
            <ol className="space-y-2 border-l border-slate-200 pl-4 text-xs">
              {c.events.map((e, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-slate-400" />
                  <span className="font-medium text-slate-800">{e.event.replace(/_/g, " ").toLowerCase()}</span>
                  <span className="text-slate-500"> by {e.actor} · {new Date(e.at).toLocaleString()}</span>
                  {"note" in e.detail && e.detail.note ? <div className="text-slate-600">“{String(e.detail.note)}”</div> : null}
                  {"amount" in e.detail && e.detail.amount ? <div className="text-slate-600">Amount {String(e.detail.amount)} {String(e.detail.currency)} (operator-reported)</div> : null}
                </li>
              ))}
            </ol>
          </Card>
        </div>

        <div className="lg:col-span-5">
          <div className="lg:sticky lg:top-16">
            <DocumentViewer docs={c.documents} evidence={allEvidence} injection={c.injection} focus={focus} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Amount({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <div className="rounded border border-slate-100 bg-slate-50 p-2.5">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-0.5 font-mono text-sm font-semibold ${tone === "bad" ? "text-rose-700" : "text-slate-900"}`}>{value}</div>
    </div>
  );
}

function NarrativeSource({ c }: { c: CaseDetail }) {
  if (!c.narrative) return null;
  const llm = c.narrative.source !== "template";
  return (
    <span className="text-[11px] text-slate-500" title={c.narrative.rejected_reason ?? ""}>
      {llm ? `Written by ${c.narrative.source}, numbers checked against facts` : "Deterministic template"}
      {c.narrative.rejected_reason && <span className="ml-1 text-amber-700">(LLM draft rejected)</span>}
    </span>
  );
}
