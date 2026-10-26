"""Load synthetic demo data: all dataset documents + a sample of bookings, audited
with the configured provider (default: oracle, no network). Also walks a few cases
through the action lifecycle so the history views are populated.

    python -m app.seed [--reset] [--limit N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app import service
from app.config import get_settings
from app.db import make_sessionmaker
from app.domain import Booking
from app.gold import load_cases, load_documents
from app.providers import build_provider
from app.service import ActionPayload, Actor, OutcomeIn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--limit", type=int, help="seed only the first N dataset cases (default: all)")
    args = ap.parse_args()
    settings = get_settings()
    settings.validate_startup()
    if args.reset and settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).unlink(missing_ok=True)
    provider = build_provider(settings)
    narr = provider if settings.llm_narratives and provider.supports_narrative else None
    factory = make_sessionmaker(settings.database_url)
    with factory() as s:
        for d in load_documents().values():
            service.upsert_document(s, d)
        s.commit()
        created = 0
        for c in load_cases()[: args.limit]:
            _, new = service.audit_booking(s, Booking.model_validate(c["booking"]), provider,
                                           document_ids=c["document_ids"], narrative_provider=narr, actor="seed")
            created += new
        # Demonstrate the lifecycle on a few supplier-query cases.
        from sqlalchemy import select

        from app.db import CaseRow

        op, ap_ = Actor(id="priya.ops", role="operator"), Actor(id="arjun.lead", role="approver")
        sq = list(s.scalars(select(CaseRow).where(CaseRow.route == "SUPPLIER_QUERY", CaseRow.status == "OPEN")
                            .order_by(CaseRow.id)))
        if len(sq) >= 3 and created:
            a1 = service.propose_action(s, sq[0].id, "SEND_SUPPLIER_QUERY", None, op)
            service.decide_action(s, a1.id, True, ap_, "Evidence checked against contract")
            service.execute_action(s, a1.id, op)
            service.record_outcome(s, sq[0].id, OutcomeIn(outcome="CREDIT_CONFIRMED", amount=sq[0].delta,
                                                         note="Hotel confirmed credit note by email (demo)"), ap_)
            a2 = service.propose_action(s, sq[1].id, "SEND_SUPPLIER_QUERY", None, op)
            service.decide_action(s, a2.id, True, ap_, "")
            service.execute_action(s, a2.id, op)
            service.propose_action(s, sq[2].id, "SEND_SUPPLIER_QUERY",
                                   ActionPayload(subject=f"Rate query: booking {sq[2].booking_id}",
                                                 body=(sq[2].narrative or {})["narrative"]["draft_body"]), op)
    print(f"seeded {created} new cases with provider {provider.name}:{provider.model} into {settings.database_url}")


if __name__ == "__main__":
    main()
