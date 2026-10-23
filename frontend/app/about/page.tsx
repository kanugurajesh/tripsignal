import { Card } from "@/components/ui";

const STEPS = [
  ["Scan", "Contract text and booking notes are checked for instruction-like content. Any hit forces human review.", "deterministic"],
  ["Extract", "An LLM (Groq or OpenAI) reads each contract version into rate rows, an effective date, cancellation terms and a dispute window. Every value comes with a verbatim quote.", "LLM"],
  ["Verify", "Each quote has to appear verbatim in the source, and each extracted number has to appear in its own quote. Values that fail are kept but marked unverified, and are never used for pricing.", "deterministic"],
  ["Select version", "The terms in force are those of documents effective on or before the booking date. Amendments override only what they restate. Two amendments with the same date that disagree raise a conflict and are never resolved by guessing.", "deterministic"],
  ["Price & compare", "Each night is priced from the applicable season rate, then multiplied by the number of rooms. Cancellation fees follow the contract's free window and penalty. Charges within 1.00 count as rounding.", "deterministic"],
  ["Route", "Each case is routed to one of four outcomes. Auto-clear only happens when the amounts match and all evidence is verified. Overcharges get a supplier query. Missing or unreadable data gets an information request. Conflicts, undercharges, unverified evidence and suspected injection are escalated.", "deterministic"],
  ["Explain", "A template explanation is always produced. An LLM may rewrite it, but the rewrite is rejected if it mentions any number that isn't in the facts.", "LLM, checked"],
  ["Act", "Supplier messages need an operator to propose them and a different approver to approve them. Sending is simulated, and every step is written to the audit trail.", "human-gated"],
];

export default function About() {
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold text-slate-900">How it works</h1>
      <p className="text-sm text-slate-600">
        TripSignal audits hotel bookings and supplier invoices against the contract version in force for each booking.
        The language model only reads documents, and every decision about money is made by tested code.
        All data in this demo is synthetic.
      </p>
      <Card>
        <ol className="space-y-3">
          {STEPS.map(([t, d, k], i) => (
            <li key={t} className="flex gap-3 text-sm">
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-slate-900 text-[11px] text-white">{i + 1}</span>
              <div><span className="font-medium text-slate-900">{t}</span> <span className="text-xs text-slate-500">· {k}</span>
                <p className="text-slate-600">{d}</p></div>
            </li>
          ))}
        </ol>
      </Card>
      <p className="text-xs text-slate-500">The roles in the &quot;Acting as&quot; menu are a demo convenience. They are enforced server-side, but this is not real authentication.</p>
    </div>
  );
}
