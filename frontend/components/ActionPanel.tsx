"use client";

import { useState } from "react";
import { api, ApiError, type Actor, type CaseDetail } from "@/lib/api";
import { Card, ErrorBox } from "./ui";

const ACTION_FOR_ROUTE: Record<string, { type: string; label: string }[]> = {
  SUPPLIER_QUERY: [{ type: "SEND_SUPPLIER_QUERY", label: "Propose supplier rate query" }],
  REQUEST_INFO: [{ type: "REQUEST_INFORMATION", label: "Propose information request" }],
  ESCALATE: [
    { type: "SEND_SUPPLIER_QUERY", label: "Propose supplier query (after review)" },
    { type: "REQUEST_INFORMATION", label: "Propose information request" },
  ],
};

export default function ActionPanel({ c, actor, onChange }: { c: CaseDetail; actor: Actor; onChange: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const n = c.narrative?.narrative;
  const [subject, setSubject] = useState(n?.draft_subject ?? `Booking ${c.booking.booking_id}: review required`);
  const [body, setBody] = useState(n?.draft_body ?? "");
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState(c.result.delta ?? "");
  const pending = c.actions.find((a) => a.status === "PROPOSED");
  const approved = c.actions.find((a) => a.status === "APPROVED");

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null);
    try { await fn(); onChange(); } catch (e) { setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); }
    finally { setBusy(false); }
  }
  const post = (path: string, b?: unknown) => run(() => api(path, { method: "POST", body: b ?? {}, actor }));

  const btn = "rounded px-3 py-1.5 text-xs font-medium disabled:opacity-40";
  const primary = `${btn} bg-slate-900 text-white hover:bg-slate-800`;
  const secondary = `${btn} border border-slate-300 bg-white text-slate-800 hover:bg-slate-50`;
  const canWrite = actor.role !== "viewer";

  return (
    <Card title="Action" right={<span className="text-[11px] text-slate-500">Sends are simulated · approval required</span>}>
      {err && <div className="mb-3"><ErrorBox error={err} /></div>}

      {c.status === "AUTO_CLEARED" && <p className="text-sm text-slate-600">The charge matches the contract within tolerance and every piece of evidence was verified, so no action is needed.</p>}

      {c.status === "OPEN" && ACTION_FOR_ROUTE[c.route] && (
        <div className="space-y-2">
          {c.route === "ESCALATE" && <p className="text-xs text-amber-800">Escalated: review the evidence before proposing anything. Automated resolution was not considered safe.</p>}
          <label className="block text-xs text-slate-600">Subject
            <input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!canWrite}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm" /></label>
          <label className="block text-xs text-slate-600">Message
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={10} disabled={!canWrite}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs" /></label>
          <div className="flex flex-wrap gap-2">
            {ACTION_FOR_ROUTE[c.route].map((a) => (
              <button key={a.type} disabled={busy || !canWrite} className={primary}
                onClick={() => post(`/api/cases/${c.id}/actions`, { type: a.type, payload: { subject, body } })}>{a.label}</button>
            ))}
            <DismissButton disabled={busy || !canWrite} onDismiss={(why) => post(`/api/cases/${c.id}/outcome`, { outcome: "DISMISSED_FALSE_POSITIVE", note: why })} />
          </div>
          {!canWrite && <p className="text-xs text-slate-500">Read-only role. Switch to an operator to propose an action.</p>}
        </div>
      )}

      {pending && (
        <div className="space-y-2">
          <ActionPreview a={pending} />
          <p className="text-xs text-slate-600">Proposed by <b>{pending.proposed_by}</b>. It needs approval from a different person with the approver role.</p>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Decision note (optional)"
            className="w-full rounded border border-slate-300 px-2 py-1 text-xs" />
          <div className="flex gap-2">
            <button disabled={busy || actor.role !== "approver" || actor.id === pending.proposed_by} className={primary}
              onClick={() => post(`/api/actions/${pending.id}/approve`, { note })}>Approve</button>
            <button disabled={busy || actor.role !== "approver"} className={secondary}
              onClick={() => post(`/api/actions/${pending.id}/reject`, { note })}>Reject</button>
          </div>
          {actor.id === pending.proposed_by && <p className="text-xs text-slate-500">You proposed this action, so you can&apos;t approve it.</p>}
        </div>
      )}

      {approved && (
        <div className="space-y-2">
          <ActionPreview a={approved} />
          <p className="text-xs text-slate-600">Approved by <b>{approved.decided_by}</b>.</p>
          <button disabled={busy || !canWrite} className={primary} onClick={() => post(`/api/actions/${approved.id}/execute`)}>
            Send (simulated)
          </button>
        </div>
      )}

      {c.status === "ACTION_EXECUTED" && (
        <div className="space-y-3">
          {c.actions.filter((a) => a.status === "EXECUTED_SIMULATED").map((a) => (
            <div key={a.id} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              <b>Simulated.</b> {a.result?.message}
            </div>
          ))}
          <div className="text-xs font-medium text-slate-700">Record outcome</div>
          <div className="flex flex-wrap items-end gap-2">
            {c.route !== "REQUEST_INFO" && c.result.delta && (
              <>
                <label className="text-xs text-slate-600">Credit amount ({c.result.currency})
                  <input value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 block w-28 rounded border border-slate-300 px-2 py-1 font-mono text-xs" /></label>
                <button disabled={busy || actor.role !== "approver"} className={primary}
                  onClick={() => post(`/api/cases/${c.id}/outcome`, { outcome: "CREDIT_CONFIRMED", amount, note })}>Credit confirmed</button>
              </>
            )}
            <button disabled={busy || !canWrite} className={secondary}
              onClick={() => post(`/api/cases/${c.id}/outcome`, { outcome: c.route === "REQUEST_INFO" ? "INFO_RECEIVED" : "SUPPLIER_DISPUTED", note })}>
              {c.route === "REQUEST_INFO" ? "Info received" : "Supplier disputes"}
            </button>
          </div>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (e.g. credit note reference)"
            className="w-full rounded border border-slate-300 px-2 py-1 text-xs" />
          <p className="text-[11px] text-slate-500">Recorded credits are labelled as operator-reported. Only approvers can record a credit.</p>
        </div>
      )}

      {(c.status === "RESOLVED" || c.status === "DISMISSED") && c.outcome && (
        <div className="text-sm text-slate-700">
          <b>{c.outcome.outcome?.replace(/_/g, " ").toLowerCase()}</b>
          {c.outcome.amount && <> · {c.outcome.amount} {c.outcome.currency}</>} · by {c.outcome.recorded_by}
          {c.outcome.note && <div className="text-xs text-slate-600">“{c.outcome.note}”</div>}
          <div className="text-[11px] text-slate-500">{c.outcome.basis}</div>
        </div>
      )}

      {c.actions.filter((a) => a.status === "REJECTED").map((a) => (
        <p key={a.id} className="mt-3 text-xs text-slate-500">Earlier proposal #{a.id} was rejected by {a.decided_by}{a.decision_note ? `: “${a.decision_note}”` : ""}.</p>
      ))}
    </Card>
  );
}

function ActionPreview({ a }: { a: CaseDetail["actions"][number] }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="text-slate-500">{a.type.replace(/_/g, " ").toLowerCase()} → {a.payload.recipient}</div>
      <div className="mt-1 font-medium text-slate-900">{a.payload.subject}</div>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-700">{a.payload.body}</pre>
    </div>
  );
}

function DismissButton({ disabled, onDismiss }: { disabled: boolean; onDismiss: (why: string) => void }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  if (!open) return <button disabled={disabled} onClick={() => setOpen(true)} className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40">Dismiss as false positive…</button>;
  return (
    <span className="flex items-center gap-1">
      <input autoFocus value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Reason (required)" className="rounded border border-slate-300 px-2 py-1 text-xs" />
      <button disabled={disabled || why.trim().length < 5} onClick={() => onDismiss(why)} className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-40">Dismiss</button>
    </span>
  );
}
