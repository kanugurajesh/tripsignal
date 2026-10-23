"use client";

import { useEffect, useRef, useState } from "react";
import type { CaseDetail, Evidence } from "@/lib/api";

const norm = (s: string) => s.replace(/[|–—]/g, " ").replace(/\s+/g, " ").trim().toLowerCase();

type Doc = CaseDetail["documents"][number];

export default function DocumentViewer({ docs, evidence, injection, focus }: {
  docs: Doc[]; evidence: Evidence[]; injection: Record<string, string[]>; focus: Evidence | null;
}) {
  const [active, setActive] = useState((docs.find((d) => evidence.some((e) => e.document_id === d.id)) ?? docs[0])?.id);
  const [prevFocus, setPrevFocus] = useState<Evidence | null>(null);
  const focusRef = useRef<HTMLElement | null>(null);

  // Switch to the focused evidence's document during render (no effect needed).
  if (focus !== prevFocus) {
    setPrevFocus(focus);
    if (focus && docs.some((d) => d.id === focus.document_id)) setActive(focus.document_id);
  }
  useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus, active]);

  const doc = docs.find((d) => d.id === active);
  if (!doc) return <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">No source documents.</div>;

  const quotes = evidence.filter((e) => e.document_id === doc.id);
  const inj = (injection[doc.id] ?? []).map(norm);

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <header className="border-b border-slate-100 px-3 pt-2.5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Source documents</h2>
          <span className="text-[11px] text-slate-500">highlight = cited evidence</span>
        </div>
        <div className="mt-2 flex gap-1 overflow-x-auto">
          {docs.map((d) => (
            <button key={d.id} onClick={() => setActive(d.id)}
              className={`whitespace-nowrap border-b-2 px-2 pb-1.5 font-mono text-[11px] ${d.id === active ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {d.id}
            </button>
          ))}
        </div>
      </header>
      <div className="px-3 py-2 text-[11px] text-slate-500">
        Received {doc.received_on} · sha256 {doc.sha256}… · treated as untrusted data
      </div>
      <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap px-3 pb-3 font-mono text-[11.5px] leading-5 text-slate-800">
        {doc.text.split("\n").map((line, i) => {
          const nl = norm(line);
          const hit = nl.length > 8 ? quotes.find((q) => { const nq = norm(q.quote); return nq.length > 8 && (nl.includes(nq) || nq.includes(nl)); }) : undefined;
          const isInj = nl.length > 8 && inj.some((s) => s.includes(nl.slice(0, 40)) || nl.includes(s.slice(0, 40)));
          const isFocus = !!(focus && hit && norm(focus.quote) === norm(hit.quote));
          if (!hit && !isInj) return <span key={i}>{line}{"\n"}</span>;
          return (
            <span key={i} ref={isFocus ? (el) => { focusRef.current = el; } : undefined}>
              <mark className={`ev ${isInj ? "ev-inj" : hit && !hit.verified ? "ev-bad" : ""} ${isFocus ? "outline outline-2 outline-amber-500" : ""}`}
                title={isInj ? "Instruction-like text (ignored)" : hit?.verified ? "Verified evidence" : hit?.reason ?? ""}>
                {line}
              </mark>{"\n"}
            </span>
          );
        })}
      </pre>
    </section>
  );
}
