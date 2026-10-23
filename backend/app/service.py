"""Case lifecycle: idempotent audit, gated actions, outcomes, audit trail.

All state transitions are enforced here (not in the UI). External side effects
are SIMULATED: nothing is sent to any supplier, and the result says so.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import ActionRow, AuditEventRow, CaseRow, DocumentRow, ExtractionRow, utcnow
from app.domain import Booking, ContractDocument, ContractTerms, Route
from app.pipeline.extraction import PROMPT_VERSION, ExtractionOutcome
from app.pipeline.run import ExtractionCache, doc_hash, run_audit
from app.providers.base import LLMProvider

Role = Literal["viewer", "operator", "approver"]


class Actor(BaseModel):
    id: str
    role: Role


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


ACTION_TYPES = {
    "SEND_SUPPLIER_QUERY": {Route.SUPPLIER_QUERY, Route.ESCALATE},
    "REQUEST_INFORMATION": {Route.REQUEST_INFO, Route.ESCALATE},
}
OUTCOMES = {"CREDIT_CONFIRMED", "SUPPLIER_DISPUTED", "INFO_RECEIVED", "DISMISSED_FALSE_POSITIVE"}


class ActionPayload(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)


class OutcomeIn(BaseModel):
    outcome: str
    amount: str | None = None
    note: str = Field("", max_length=2000)


def _event(s: Session, case_id: str, actor: str, event: str, **detail: Any) -> None:
    s.add(AuditEventRow(case_id=case_id, actor=actor, event=event, detail=json.loads(json.dumps(detail, default=str))))


def _require(actor: Actor, *roles: Role) -> None:
    if actor.role not in roles:
        raise ServiceError(403, "FORBIDDEN", f"role '{actor.role}' cannot perform this action (needs {'/'.join(roles)})")


# ----------------------------------------------------------------- documents
def upsert_document(s: Session, doc: ContractDocument) -> DocumentRow:
    row = s.get(DocumentRow, doc.document_id)
    h = doc_hash(doc)
    if row is None:
        row = DocumentRow(id=doc.document_id, hotel_id=doc.hotel_id, title=doc.title, received_on=doc.received_on,
                          text=doc.text, sha256=h)
        s.add(row)
    elif row.sha256 != h:
        raise ServiceError(409, "DOCUMENT_CHANGED",
                           f"{doc.document_id} already exists with different content; upload a new version id")
    return row


def _to_doc(r: DocumentRow) -> ContractDocument:
    return ContractDocument(document_id=r.id, hotel_id=r.hotel_id, title=r.title, received_on=r.received_on,
                            text=r.text)


class DbExtractionCache(ExtractionCache):
    """Extraction cache backed by the extractions table (survives restarts)."""

    def __init__(self, s: Session):
        super().__init__()
        self.s = s

    def get_or_extract(self, doc: ContractDocument, provider: LLMProvider) -> tuple[ExtractionOutcome, bool]:
        h = doc_hash(doc)
        row = self.s.scalar(select(ExtractionRow).where(
            ExtractionRow.sha256 == h, ExtractionRow.provider == provider.name,
            ExtractionRow.model == provider.model, ExtractionRow.prompt_version == PROMPT_VERSION))
        if row is not None:
            return ExtractionOutcome(doc.document_id, ContractTerms.model_validate(row.terms), row.usage), True
        out, cached = super().get_or_extract(doc, provider)
        if out.terms is not None and not cached:
            self.s.add(ExtractionRow(document_id=doc.document_id, sha256=h, provider=provider.name,
                                     model=provider.model, prompt_version=PROMPT_VERSION,
                                     terms=out.terms.model_dump(mode="json"), usage=out.usage))
        return out, cached


# --------------------------------------------------------------------- audit
def input_hash(booking: Booking, docs: list[ContractDocument], provider: LLMProvider) -> str:
    payload = json.dumps({"b": booking.model_dump(mode="json"), "d": sorted(doc_hash(d) for d in docs),
                          "p": [provider.name, provider.model, PROMPT_VERSION]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_booking(s: Session, booking: Booking, provider: LLMProvider, *, document_ids: list[str] | None = None,
                  narrative_provider: LLMProvider | None = None, actor: str = "system") -> tuple[CaseRow, bool]:
    """Returns (case, created). Same booking + same documents + same model => same case (idempotent)."""
    q = select(DocumentRow).where(DocumentRow.hotel_id == booking.hotel_id)
    if document_ids:
        q = select(DocumentRow).where(DocumentRow.id.in_(document_ids))
    doc_rows = list(s.scalars(q.order_by(DocumentRow.id)))
    if document_ids and len(doc_rows) != len(set(document_ids)):
        raise ServiceError(404, "DOCUMENT_NOT_FOUND", "one or more document_ids do not exist")
    if any(r.hotel_id != booking.hotel_id for r in doc_rows):
        raise ServiceError(422, "DOCUMENT_HOTEL_MISMATCH", f"all documents must belong to hotel {booking.hotel_id}")
    docs = [_to_doc(r) for r in doc_rows]
    h = input_hash(booking, docs, provider)
    existing = s.scalar(select(CaseRow).where(CaseRow.input_hash == h))
    if existing is not None:
        return existing, False

    run = run_audit(booking, docs, provider, cache=DbExtractionCache(s), narrative_provider=narrative_provider)
    r = run.result
    seq = 1001 + (s.scalar(select(func.count(CaseRow.id))) or 0)
    case = CaseRow(
        id=f"CASE-{seq}", input_hash=h, booking_id=booking.booking_id, hotel_id=booking.hotel_id,
        booking=booking.model_dump(mode="json"), document_ids=[d.document_id for d in docs],
        result=r.model_dump(mode="json"), narrative=run.narrative.model_dump(mode="json") if run.narrative else None,
        extraction_meta=[{"document_id": e.document_id, "ok": e.terms is not None, "error": e.error,
                          "usage": e.usage} for e in run.extractions],
        injection=run.injection_hits, usage=run.usage, route=r.route.value, severity=r.severity,
        status="AUTO_CLEARED" if r.route == Route.AUTO_CLEAR else "OPEN", currency=r.currency,
        delta=str(r.delta) if r.delta is not None else None, dispute_deadline=r.dispute_deadline,
        provider=f"{provider.name}:{provider.model}",
    )
    s.add(case)
    s.flush()
    _event(s, case.id, actor, "AUDITED", route=r.route.value, codes=[c.value for c in r.codes],
           provider=case.provider, documents=case.document_ids)
    if case.status == "AUTO_CLEARED":
        _event(s, case.id, "system", "AUTO_CLEARED", reason="charge matches contract within tolerance; evidence verified")
    s.commit()
    return case, True


# ------------------------------------------------------------------- actions
def _case(s: Session, case_id: str) -> CaseRow:
    c = s.get(CaseRow, case_id)
    if c is None:
        raise ServiceError(404, "NOT_FOUND", f"case {case_id} not found")
    return c


def _action(s: Session, action_id: int) -> ActionRow:
    a = s.get(ActionRow, action_id)
    if a is None:
        raise ServiceError(404, "NOT_FOUND", f"action {action_id} not found")
    return a


def propose_action(s: Session, case_id: str, action_type: str, payload: ActionPayload | None, actor: Actor) -> ActionRow:
    _require(actor, "operator", "approver")
    c = _case(s, case_id)
    if action_type not in ACTION_TYPES:
        raise ServiceError(422, "INVALID_ACTION", f"unknown action type {action_type}")
    if Route(c.route) not in ACTION_TYPES[action_type]:
        raise ServiceError(422, "ACTION_NOT_ALLOWED", f"{action_type} is not allowed for route {c.route}")
    if c.status != "OPEN":
        raise ServiceError(409, "INVALID_STATE", f"case is {c.status}; actions can only be proposed on OPEN cases")
    if payload is None:
        n = (c.narrative or {}).get("narrative") or {}
        if not n.get("draft_subject") or not n.get("draft_body"):
            raise ServiceError(422, "PAYLOAD_REQUIRED", "no draft available; provide subject and body")
        payload = ActionPayload(subject=n["draft_subject"], body=n["draft_body"])
    a = ActionRow(case_id=c.id, type=action_type, status="PROPOSED",
                  payload={**payload.model_dump(), "recipient": f"billing@{c.hotel_id.lower()}.example (simulated)"},
                  proposed_by=actor.id)
    s.add(a)
    c.status = "AWAITING_APPROVAL"
    s.flush()
    _event(s, c.id, actor.id, "ACTION_PROPOSED", action_id=a.id, type=action_type)
    s.commit()
    return a


def decide_action(s: Session, action_id: int, approve: bool, actor: Actor, note: str = "") -> ActionRow:
    _require(actor, "approver")
    a = _action(s, action_id)
    if a.status != "PROPOSED":
        raise ServiceError(409, "INVALID_STATE", f"action is {a.status}; only PROPOSED actions can be decided")
    if approve and a.proposed_by == actor.id:
        raise ServiceError(403, "SEGREGATION_OF_DUTIES", "the proposer cannot approve their own action")
    c = _case(s, a.case_id)
    if c.status != "AWAITING_APPROVAL":
        raise ServiceError(409, "INVALID_STATE", f"case is {c.status}; its pending action can no longer be decided")
    a.status, a.decided_by, a.decided_at, a.decision_note = ("APPROVED" if approve else "REJECTED"), actor.id, utcnow(), note
    if not approve:
        c.status = "OPEN"
    _event(s, c.id, actor.id, "ACTION_APPROVED" if approve else "ACTION_REJECTED", action_id=a.id, note=note)
    s.commit()
    return a


def execute_action(s: Session, action_id: int, actor: Actor) -> ActionRow:
    _require(actor, "operator", "approver")
    a = _action(s, action_id)
    if a.status != "APPROVED":
        raise ServiceError(409, "INVALID_STATE", f"action is {a.status}; only APPROVED actions can be executed")
    c = _case(s, a.case_id)
    if c.status != "AWAITING_APPROVAL":
        raise ServiceError(409, "INVALID_STATE", f"case is {c.status}; the action can no longer be executed")
    a.status, a.executed_at = "EXECUTED_SIMULATED", utcnow()
    a.result = {"simulated": True, "message": "No email was sent. This MVP has no supplier integration; "
                "the message was recorded as if sent."}
    c.status = "ACTION_EXECUTED"
    _event(s, c.id, actor.id, "ACTION_EXECUTED_SIMULATED", action_id=a.id, type=a.type)
    s.commit()
    return a


def record_outcome(s: Session, case_id: str, body: OutcomeIn, actor: Actor) -> CaseRow:
    _require(actor, "operator", "approver")
    c = _case(s, case_id)
    if body.outcome not in OUTCOMES:
        raise ServiceError(422, "INVALID_OUTCOME", f"outcome must be one of {sorted(OUTCOMES)}")
    if c.status in ("RESOLVED", "DISMISSED", "AUTO_CLEARED"):
        raise ServiceError(409, "INVALID_STATE", f"case is already {c.status}")
    if c.status == "AWAITING_APPROVAL":
        raise ServiceError(409, "INVALID_STATE", "an action is pending; approve or reject it before recording an outcome")
    if body.outcome == "CREDIT_CONFIRMED":
        _require(actor, "approver")
        if c.status != "ACTION_EXECUTED":
            raise ServiceError(409, "INVALID_STATE", "a credit can only be recorded after the supplier query was sent")
        try:
            amt = Decimal(body.amount or "")
        except InvalidOperation:
            raise ServiceError(422, "INVALID_AMOUNT", "amount is required for CREDIT_CONFIRMED") from None
        if not amt.is_finite() or amt <= 0 or c.delta is None or amt > Decimal(c.delta):
            raise ServiceError(422, "INVALID_AMOUNT", f"credit must be > 0 and <= detected difference {c.delta}")
    if body.outcome == "DISMISSED_FALSE_POSITIVE" and len(body.note.strip()) < 5:
        raise ServiceError(422, "NOTE_REQUIRED", "explain why this is a false positive")
    c.outcome = {"outcome": body.outcome, "amount": body.amount if body.outcome == "CREDIT_CONFIRMED" else None,
                 "currency": c.currency, "note": body.note, "recorded_by": actor.id, "recorded_at": str(utcnow()),
                 "basis": "operator-reported; not verified against a supplier credit note"}
    c.status = "DISMISSED" if body.outcome == "DISMISSED_FALSE_POSITIVE" else "RESOLVED"
    _event(s, c.id, actor.id, "OUTCOME_RECORDED", **c.outcome)
    s.commit()
    return c


def overview(s: Session, as_of: date) -> dict[str, Any]:
    cases = list(s.scalars(select(CaseRow)))
    by_route: dict[str, int] = {}
    by_status: dict[str, int] = {}
    open_exposure: dict[str, Decimal] = {}
    recovered: dict[str, Decimal] = {}
    due_soon = 0
    for c in cases:
        by_route[c.route] = by_route.get(c.route, 0) + 1
        by_status[c.status] = by_status.get(c.status, 0) + 1
        active = c.status in ("OPEN", "AWAITING_APPROVAL", "ACTION_EXECUTED")
        if active and c.delta and Decimal(c.delta) > 0 and "OVERCHARGE" in c.result["codes"]:
            open_exposure[c.currency or "?"] = open_exposure.get(c.currency or "?", Decimal(0)) + Decimal(c.delta)
        if c.outcome and c.outcome.get("amount"):
            recovered[c.currency or "?"] = recovered.get(c.currency or "?", Decimal(0)) + Decimal(c.outcome["amount"])
        if active and c.dispute_deadline and (c.dispute_deadline - as_of).days <= 7:
            due_soon += 1
    return {
        "as_of": as_of, "total_cases": len(cases), "by_route": by_route, "by_status": by_status,
        "open_overcharge_exposure": {k: str(v) for k, v in open_exposure.items()},
        "operator_reported_credits": {k: str(v) for k, v in recovered.items()},
        "disputes_due_within_7_days": due_soon,
        "labels": {"open_overcharge_exposure": "Detected (calculated) overcharges on open cases; not yet confirmed by suppliers",
                   "operator_reported_credits": "Credits recorded by operators; not verified against credit notes"},
    }
