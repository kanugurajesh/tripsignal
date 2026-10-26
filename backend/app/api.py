"""FastAPI application.

Demo auth: callers identify with X-Actor-Id / X-Actor-Role headers. This is NOT
real authentication (see docs/LIMITATIONS.md); it exists so role checks and
segregation of duties are enforced server-side and testable.
"""


import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import service
from app.config import Settings, get_settings
from app.db import ActionRow, AuditEventRow, CaseRow, DocumentRow, ExtractionRow, make_sessionmaker
from app.domain import Booking, ContractDocument
from app.providers import build_provider
from app.providers.base import LLMProvider
from app.service import ActionPayload, Actor, OutcomeIn, ServiceError

RESULTS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "evals" / "results"


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    if provider is None:
        settings.validate_startup()  # fail fast with a clear message about missing keys
        provider = build_provider(settings)
    factory = make_sessionmaker(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        yield

    app = FastAPI(title="TripSignal Rate Assurance", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                       allow_headers=["*"])
    app.state.provider, app.state.factory, app.state.settings = provider, factory, settings

    @app.exception_handler(ServiceError)
    async def _svc_err(_: Request, e: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=e.status, content={"error": e.code, "message": e.message})

    def db() -> Iterator[Session]:
        with factory() as s:
            yield s

    def actor(x_actor_id: Annotated[str | None, Header()] = None,
              x_actor_role: Annotated[str | None, Header()] = None) -> Actor:
        role = (x_actor_role or "viewer").lower()
        if role not in ("viewer", "operator", "approver"):
            raise HTTPException(400, f"unknown role {role}")
        return Actor(id=(x_actor_id or "anonymous")[:64], role=role)  # type: ignore[arg-type]

    S = Annotated[Session, Depends(db)]
    A = Annotated[Actor, Depends(actor)]

    def as_of() -> date:
        return settings.as_of_date or date.today()

    def narrative_provider() -> LLMProvider | None:
        p = app.state.provider
        return p if settings.llm_narratives and p.supports_narrative else None

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        p = app.state.provider
        return {"status": "ok", "provider": p.name, "model": p.model, "narratives": narrative_provider() is not None,
                "fallback_provider": settings.fallback_provider, "as_of": as_of(),
                "demo_mode": p.name == "oracle"}

    @app.get("/api/overview")
    def get_overview(s: S) -> dict[str, Any]:
        return service.overview(s, as_of())

    # ------------------------------------------------------------- documents
    @app.get("/api/documents")
    def list_documents(s: S, hotel_id: str | None = None) -> list[dict[str, Any]]:
        q = select(DocumentRow).order_by(DocumentRow.hotel_id, DocumentRow.id)
        if hotel_id:
            q = q.where(DocumentRow.hotel_id == hotel_id)
        return [{"id": d.id, "hotel_id": d.hotel_id, "title": d.title, "received_on": d.received_on,
                 "sha256": d.sha256[:12]} for d in s.scalars(q)]

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: str, s: S) -> dict[str, Any]:
        d = s.get(DocumentRow, doc_id)
        if d is None:
            raise HTTPException(404, "document not found")
        ex = list(s.scalars(select(ExtractionRow).where(ExtractionRow.document_id == doc_id)))
        return {"id": d.id, "hotel_id": d.hotel_id, "title": d.title, "received_on": d.received_on, "text": d.text,
                "sha256": d.sha256, "extractions": [{"provider": e.provider, "model": e.model,
                                                     "prompt_version": e.prompt_version, "terms": e.terms,
                                                     "created_at": e.created_at} for e in ex]}

    @app.post("/api/documents", status_code=201)
    def add_document(doc: ContractDocument, s: S, who: A) -> dict[str, Any]:
        if who.role == "viewer":
            raise HTTPException(403, "viewers cannot upload documents")
        row = service.upsert_document(s, doc)
        s.commit()
        return {"id": row.id, "sha256": row.sha256}

    # ----------------------------------------------------------------- cases
    class AuditIn(BaseModel):
        booking: Booking
        document_ids: list[str] | None = None

    @app.post("/api/audits")
    def create_audit(body: AuditIn, s: S, who: A) -> JSONResponse:
        if who.role == "viewer":
            raise HTTPException(403, "viewers cannot start audits")
        case, created = service.audit_booking(s, body.booking, app.state.provider, document_ids=body.document_ids,
                                              narrative_provider=narrative_provider(), actor=who.id)
        return JSONResponse(status_code=201 if created else 200,
                            content={"case_id": case.id, "created": created, "route": case.route})

    @app.get("/api/cases")
    def list_cases(s: S, route: str | None = None, status: str | None = None, severity: str | None = None,
                   q: str | None = None, limit: int = Query(200, le=500)) -> list[dict[str, Any]]:
        stmt = select(CaseRow).order_by(CaseRow.created_at.desc(), CaseRow.id.desc()).limit(limit)
        if route:
            stmt = stmt.where(CaseRow.route == route)
        if status:
            stmt = stmt.where(CaseRow.status.in_(status.split(",")))
        if severity:
            stmt = stmt.where(CaseRow.severity == severity)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(CaseRow.id.ilike(like), CaseRow.booking_id.ilike(like), CaseRow.hotel_id.ilike(like)))
        today = as_of()
        return [{
            "id": c.id, "booking_id": c.booking_id, "hotel_id": c.hotel_id, "route": c.route, "status": c.status,
            "severity": c.severity, "codes": c.result["codes"], "kind": c.result["kind"],
            "traveller_events": c.result.get("traveller_events", []), "currency": c.currency,
            "delta": c.delta, "dispute_deadline": c.dispute_deadline,
            "days_to_deadline": (c.dispute_deadline - today).days if c.dispute_deadline else None,
            "guest_name": c.booking.get("guest_name"), "room_type": c.booking.get("room_type"),
            "check_in": c.booking.get("check_in"), "created_at": c.created_at,
        } for c in s.scalars(stmt)]

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, s: S) -> dict[str, Any]:
        c = s.get(CaseRow, case_id)
        if c is None:
            raise HTTPException(404, "case not found")
        docs = list(s.scalars(select(DocumentRow).where(DocumentRow.id.in_(c.document_ids))))
        actions = list(s.scalars(select(ActionRow).where(ActionRow.case_id == c.id).order_by(ActionRow.id)))
        events = list(s.scalars(select(AuditEventRow).where(AuditEventRow.case_id == c.id).order_by(AuditEventRow.id)))
        return {
            "id": c.id, "status": c.status, "route": c.route, "severity": c.severity, "provider": c.provider,
            "booking": c.booking, "result": c.result, "narrative": c.narrative, "injection": c.injection,
            "extraction_meta": c.extraction_meta, "usage": c.usage, "outcome": c.outcome,
            "dispute_deadline": c.dispute_deadline,
            "days_to_deadline": (c.dispute_deadline - as_of()).days if c.dispute_deadline else None,
            "documents": [{"id": d.id, "title": d.title, "text": d.text, "received_on": d.received_on,
                           "sha256": d.sha256[:12]} for d in docs],
            "actions": [{"id": a.id, "type": a.type, "status": a.status, "payload": a.payload,
                         "proposed_by": a.proposed_by, "proposed_at": a.proposed_at, "decided_by": a.decided_by,
                         "decided_at": a.decided_at, "decision_note": a.decision_note,
                         "executed_at": a.executed_at, "result": a.result} for a in actions],
            "events": [{"at": e.at, "actor": e.actor, "event": e.event, "detail": e.detail} for e in events],
        }

    class ProposeIn(BaseModel):
        type: str
        payload: ActionPayload | None = None

    @app.post("/api/cases/{case_id}/actions", status_code=201)
    def propose(case_id: str, body: ProposeIn, s: S, who: A) -> dict[str, Any]:
        a = service.propose_action(s, case_id, body.type, body.payload, who)
        return {"id": a.id, "status": a.status}

    class DecisionIn(BaseModel):
        note: str = ""

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: int, body: DecisionIn, s: S, who: A) -> dict[str, Any]:
        return {"id": action_id, "status": service.decide_action(s, action_id, True, who, body.note).status}

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: int, body: DecisionIn, s: S, who: A) -> dict[str, Any]:
        return {"id": action_id, "status": service.decide_action(s, action_id, False, who, body.note).status}

    @app.post("/api/actions/{action_id}/execute")
    def execute(action_id: int, s: S, who: A) -> dict[str, Any]:
        a = service.execute_action(s, action_id, who)
        return {"id": a.id, "status": a.status, "result": a.result}

    @app.post("/api/cases/{case_id}/outcome")
    def outcome(case_id: str, body: OutcomeIn, s: S, who: A) -> dict[str, Any]:
        c = service.record_outcome(s, case_id, body, who)
        return {"id": c.id, "status": c.status, "outcome": c.outcome}

    # ------------------------------------------------------------------ evals
    @app.get("/api/evals")
    def list_evals() -> list[dict[str, Any]]:
        out = []
        for p in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
            r = json.loads(p.read_text(encoding="utf-8"))
            out.append({"file": p.name, "meta": r["meta"], "summary": r["summary"], "by_category": r["by_category"]})
        return out

    @app.get("/api/evals/{name}")
    def get_eval(name: str) -> dict[str, Any]:
        p = RESULTS_DIR / name
        if p.parent != RESULTS_DIR or not p.is_file() or p.suffix != ".json":
            raise HTTPException(404, "not found")
        return json.loads(p.read_text(encoding="utf-8"))

    return app
