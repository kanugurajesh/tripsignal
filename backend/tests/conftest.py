from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest

# Tests must never pick up real keys or a developer's .env.
for k in ("OPENAI_API_KEY", "GROQ_API_KEY", "AI_PROVIDER", "FALLBACK_PROVIDER"):
    os.environ.pop(k, None)

from app.domain import (  # noqa: E402
    Booking,
    Cancellation,
    ContractTerms,
    EarlyDeparturePolicy,
    NoShowPolicy,
    RateRow,
    UpgradePolicy,
    VerifiedEvidence,
)


def ev(doc: str = "DOC-1", quote: str = "q", verified: bool = True) -> VerifiedEvidence:
    return VerifiedEvidence(document_id=doc, section="3. ROOM RATES", quote=quote, verified=verified,
                            reason=None if verified else "quote not found verbatim in source document")


def row(room: str, start: str, end: str, rate: str | None, *, meal: str = "BB", occ: str = "DBL",
        cur: str = "EUR", doc: str = "DOC-1", verified: bool = True) -> RateRow:
    return RateRow(room_type=room, meal_plan=meal, occupancy=occ, season_start=date.fromisoformat(start),
                   season_end=date.fromisoformat(end), nightly_rate=Decimal(rate) if rate else None, currency=cur,
                   evidence=ev(doc, f"{room} {rate}", verified))


def terms(doc: str, effective: str, rates: list[RateRow], *, cancel: tuple[int, int] | None = (14, 1),
          dispute: int | None = 30, no_show: int | str | None = 1, early_departure: int | None = 1,
          upgrade_complimentary: bool | None = True) -> ContractTerms:
    """no_show: nights charged, or "full" for the whole stay; None = clause absent."""
    return ContractTerms(
        document_id=doc, hotel_name="Test Hotel", is_amendment=False, effective_from=date.fromisoformat(effective),
        effective_evidence=ev(doc, "effective"), rates=rates,
        cancellation=Cancellation(free_cancellation_days=cancel[0], penalty_nights=cancel[1], evidence=ev(doc, "cx"))
        if cancel else None,
        no_show=None if no_show is None else NoShowPolicy(
            penalty_nights=None if no_show == "full" else int(no_show), full_stay=no_show == "full",
            evidence=ev(doc, "no-show")),
        early_departure=None if early_departure is None else EarlyDeparturePolicy(
            penalty_nights=early_departure, evidence=ev(doc, "early departure")),
        upgrade=None if upgrade_complimentary is None else UpgradePolicy(
            complimentary=upgrade_complimentary, evidence=ev(doc, "upgrade")),
        dispute_window_days=dispute, dispute_evidence=ev(doc, "dispute") if dispute else None,
    )


@pytest.fixture
def base_contract() -> ContractTerms:
    return terms("DOC-1", "2026-01-01", [
        row("Deluxe", "2026-04-01", "2026-06-30", "145.00"),
        row("Deluxe", "2026-07-01", "2026-09-30", "195.00"),
    ])


def booking(**kw) -> Booking:  # type: ignore[no-untyped-def]
    base = dict(booking_id="BK-1", hotel_id="H1", booking_date=date(2026, 3, 1), check_in=date(2026, 5, 10),
                check_out=date(2026, 5, 13), room_type="Deluxe", meal_plan="BB", occupancy="DBL", rooms=1,
                currency="EUR", invoiced_total=Decimal("435.00"), invoice_id="INV-1", invoice_date=date(2026, 5, 13))
    base.update(kw)
    return Booking(**base)
