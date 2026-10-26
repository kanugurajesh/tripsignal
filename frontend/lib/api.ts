export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Role = "viewer" | "operator" | "approver";
export type Actor = { id: string; role: Role; label: string };

export const ACTORS: Actor[] = [
  { id: "priya.ops", role: "operator", label: "Priya (Operator)" },
  { id: "arjun.lead", role: "approver", label: "Arjun (Approver)" },
  { id: "meera.fin", role: "approver", label: "Meera (Finance approver)" },
  { id: "guest", role: "viewer", label: "Guest (Read-only)" },
];

export type Route = "AUTO_CLEAR" | "SUPPLIER_QUERY" | "REQUEST_INFO" | "ESCALATE";

export type TravellerEvent = "cancellation" | "no_show" | "early_departure" | "extension" | "hotel_upgrade" | "guest_upgrade";

export const EVENT_LABEL: Record<TravellerEvent, string> = {
  cancellation: "Cancellation",
  no_show: "No-show",
  early_departure: "Early departure",
  extension: "Extension",
  hotel_upgrade: "Hotel upgrade",
  guest_upgrade: "Guest upgrade",
};

export const BASIS_LABEL: Record<string, string> = {
  stay: "Stayed",
  extension: "Extension",
  early_departure_penalty: "Early-departure penalty",
  no_show_penalty: "No-show penalty",
  cancellation_penalty: "Cancellation penalty",
};

export type CaseRow = {
  id: string;
  booking_id: string;
  hotel_id: string;
  route: Route;
  status: string;
  severity: "low" | "medium" | "high";
  codes: string[];
  kind: "stay" | "cancellation" | "no_show";
  traveller_events: TravellerEvent[];
  currency: string | null;
  delta: string | null;
  dispute_deadline: string | null;
  days_to_deadline: number | null;
  guest_name: string;
  room_type: string | null;
  check_in: string | null;
  created_at: string;
};

export type Evidence = { document_id: string; section: string; quote: string; verified: boolean; reason: string | null };

export type CaseDetail = {
  id: string;
  status: string;
  route: Route;
  severity: string;
  provider: string;
  booking: Record<string, string | number | null>;
  result: {
    codes: string[];
    kind: string;
    traveller_events: TravellerEvent[];
    currency: string | null;
    expected_amount: string | null;
    charged_amount: string | null;
    delta: string | null;
    nights: { night: string; basis: string; room_type: string | null; rate: string; document_id: string; evidence: Evidence }[];
    clauses?: Evidence[];
    findings: { code: string; message: string; evidence: Evidence[] }[];
    applied_documents: string[];
    assumptions: string[];
  };
  narrative: {
    source: string;
    rejected_reason: string | null;
    narrative: { summary: string; next_step: string; draft_subject: string | null; draft_body: string | null };
  } | null;
  injection: Record<string, string[]>;
  extraction_meta: { document_id: string; ok: boolean; error: string | null }[];
  usage: Record<string, unknown>[];
  outcome: Record<string, string | null> | null;
  dispute_deadline: string | null;
  days_to_deadline: number | null;
  documents: { id: string; title: string; text: string; received_on: string; sha256: string }[];
  actions: {
    id: number;
    type: string;
    status: string;
    payload: { subject: string; body: string; recipient: string };
    proposed_by: string;
    proposed_at: string;
    decided_by: string | null;
    decision_note: string | null;
    executed_at: string | null;
    result: { simulated: boolean; message: string } | null;
  }[];
  events: { at: string; actor: string; event: string; detail: Record<string, unknown> }[];
};

export type Overview = {
  as_of: string;
  total_cases: number;
  by_route: Record<string, number>;
  by_status: Record<string, number>;
  open_overcharge_exposure: Record<string, string>;
  operator_reported_credits: Record<string, string>;
  disputes_due_within_7_days: number;
  labels: Record<string, string>;
};

export type Health = { provider: string; model: string; narratives: boolean; demo_mode: boolean; as_of: string };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; actor?: Actor } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.actor) {
    headers["X-Actor-Id"] = opts.actor.id;
    headers["X-Actor-Role"] = opts.actor.role;
  }
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NETWORK", `Cannot reach the API at ${API}. Is the backend running?`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.message ?? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data));
    throw new ApiError(res.status, data.error ?? String(res.status), msg);
  }
  return data as T;
}

export const ROUTE_LABEL: Record<Route, string> = {
  AUTO_CLEAR: "Auto-cleared",
  SUPPLIER_QUERY: "Supplier query",
  REQUEST_INFO: "Needs info",
  ESCALATE: "Escalated",
};

export const STATUS_LABEL: Record<string, string> = {
  OPEN: "Open",
  AWAITING_APPROVAL: "Awaiting approval",
  ACTION_EXECUTED: "Query sent (simulated)",
  RESOLVED: "Resolved",
  DISMISSED: "Dismissed",
  AUTO_CLEARED: "Cleared",
};

export function money(v: string | null | undefined, cur?: string | null): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const s = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return cur ? `${cur} ${s}` : s;
}
