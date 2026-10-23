"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, Code, ErrorBox, Skeleton } from "@/components/ui";

type Run = {
  file: string;
  meta: { provider: string; model: string; cases: number; documents: number; run_at: string; narratives: boolean; dataset_sha256: string; prompt_version: string };
  summary: Record<string, number | null>;
  by_category: Record<string, { n: number; route_accuracy: number | null; unsafe_auto_clears: number }>;
};

const ROWS: [string, string, "pct" | "int" | "usd" | "ms"][] = [
  ["route_accuracy", "Route accuracy", "pct"],
  ["unsafe_auto_clears", "Unsafe auto-clears (target 0)", "int"],
  ["exception_precision", "Exception precision", "pct"],
  ["exception_recall", "Exception recall", "pct"],
  ["code_set_accuracy", "Finding-code accuracy", "pct"],
  ["amount_accuracy", "Amount correctness", "pct"],
  ["appropriate_abstention_rate", "Appropriate abstention", "pct"],
  ["rate_row_recall", "Rate extraction recall", "pct"],
  ["spurious_rate_rows", "Spurious rate rows", "int"],
  ["evidence_verified_rate", "Evidence verified", "pct"],
  ["effective_date_accuracy", "Effective-date accuracy", "pct"],
  ["cancellation_terms_accuracy", "Cancellation terms accuracy", "pct"],
  ["narratives_rejected_unsupported_numbers", "Narratives rejected (unsupported numbers)", "int"],
  ["llm_calls", "LLM calls", "int"],
  ["est_cost_usd", "Estimated cost", "usd"],
  ["mean_llm_latency_ms", "Mean LLM latency", "ms"],
];

function fmt(v: number | null | undefined, k: string) {
  if (v === null || v === undefined) return "—";
  if (k === "pct") return `${(v * 100).toFixed(1)}%`;
  if (k === "usd") return `$${v.toFixed(4)}`;
  if (k === "ms") return `${Math.round(v)} ms`;
  return String(v);
}

export default function EvalsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Run[]>("/api/evals").then(setRuns).catch((e) => setErr(e.message)); }, []);
  if (err) return <ErrorBox error={err} />;
  if (!runs) return <Skeleton />;

  const latest = new Map<string, Run>();
  for (const r of runs) { const k = `${r.meta.provider}:${r.meta.model}:${r.meta.narratives}`; if (!latest.has(k)) latest.set(k, r); }
  const cols = [...latest.values()];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Evaluation</h1>
        <p className="max-w-3xl text-sm text-slate-500">
          Every run uses the same synthetic dataset. Each case&apos;s expected outcome comes from how the scenario was built,
          not from any model, and all scoring is deterministic. <b>Oracle</b> replays ground-truth extraction, which isolates the rule engine.
          LLM runs measure end-to-end behaviour. Only runs that were actually executed appear here.
        </p>
      </div>
      {cols.length === 0 ? (
        <Card><p className="text-sm text-slate-500">No results yet. Run <Code>python -m evals.run --provider oracle</Code>.</p></Card>
      ) : (
        <>
          <Card title="Latest run per configuration">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                  <th className="py-2 pr-4 font-medium">Metric</th>
                  {cols.map((r) => <th key={r.file} className="py-2 pr-4 text-right font-medium"><span className="font-mono">{r.meta.provider}:{r.meta.model}</span>{r.meta.narratives && " +narratives"}
                    <div className="font-normal">{r.meta.cases} cases · {r.meta.run_at.slice(0, 16).replace("T", " ")}</div></th>)}
                </tr></thead>
                <tbody>
                  {ROWS.map(([k, label, f]) => (
                    <tr key={k} className="border-b border-slate-50">
                      <td className="py-1.5 pr-4 text-slate-700">{label}</td>
                      {cols.map((r) => <td key={r.file} className={`py-1.5 pr-4 text-right font-mono text-xs ${k === "unsafe_auto_clears" && (r.summary[k] ?? 0) > 0 ? "font-semibold text-rose-700" : ""}`}>{fmt(r.summary[k], f)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Route accuracy by scenario category">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-500"><th className="py-2 pr-4 font-medium">Category</th>
                  {cols.map((r) => <th key={r.file} className="py-2 pr-4 text-right font-mono text-xs font-medium">{r.meta.provider}</th>)}</tr></thead>
                <tbody>
                  {Object.keys(cols[0].by_category).map((cat) => (
                    <tr key={cat} className="border-b border-slate-50">
                      <td className="py-1.5 pr-4 text-slate-700">{cat.replace(/_/g, " ")} <span className="text-xs text-slate-400">n={cols[0].by_category[cat].n}</span></td>
                      {cols.map((r) => { const c = r.by_category[cat]; return <td key={r.file} className="py-1.5 pr-4 text-right font-mono text-xs">{c ? fmt(c.route_accuracy, "pct") : "—"}{c?.unsafe_auto_clears ? <span className="ml-1 text-rose-700">({c.unsafe_auto_clears} unsafe)</span> : null}</td>; })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <p className="text-xs text-slate-500">Dataset hash {cols[0].meta.dataset_sha256} · prompt {cols[0].meta.prompt_version} · {runs.length} saved run(s) in <Code>backend/evals/results</Code></p>
        </>
      )}
    </div>
  );
}
