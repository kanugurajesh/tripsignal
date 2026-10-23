"""Deterministic audit engine: version selection, nightly pricing, comparison, routing.

No LLM calls happen here. Every amount is derived from verified contract rows
and booking fields, and every blocking condition produces a typed finding.

Version rule (see docs/DECISIONS.md D3): the terms in force for a booking are
those of documents whose effective_from <= booking_date. For each night, the
newest such document that prices the room/meal/occupancy for that night wins
(amendments override only what they restate). Two documents with the same
effective date that disagree are a VERSION_CONFLICT; we never pick one.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from app.domain import (
    ESCALATE_CODES,
    REQUEST_INFO_CODES,
    AuditResult,
    Booking,
    Cancellation,
    Code,
    ContractTerms,
    Finding,
    NightCharge,
    RateRow,
    Route,
    VerifiedEvidence,
)

TOLERANCE = Decimal("1.00")  # rounding tolerance per booking, in booking currency
HIGH_EXPOSURE = Decimal("500")
MEDIUM_EXPOSURE = Decimal("100")


def norm(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


class _Issues:
    def __init__(self) -> None:
        self._by_code: dict[Code, list[str]] = defaultdict(list)
        self._evidence: dict[Code, list[VerifiedEvidence]] = defaultdict(list)

    def add(self, code: Code, msg: str, evidence: list[VerifiedEvidence] | None = None) -> None:
        if msg not in self._by_code[code]:
            self._by_code[code].append(msg)
        for e in evidence or []:
            if e not in self._evidence[code]:
                self._evidence[code].append(e)

    def __bool__(self) -> bool:
        return bool(self._by_code)

    def findings(self) -> list[Finding]:
        return [
            Finding(code=c, message="; ".join(msgs), evidence=self._evidence[c])
            for c, msgs in self._by_code.items()
        ]


def _nights(check_in: date, check_out: date) -> list[date]:
    return [check_in + timedelta(days=i) for i in range((check_out - check_in).days)]


def _applicable_groups(
    booking_date: date, contracts: list[ContractTerms], issues: _Issues
) -> list[list[ContractTerms]]:
    """Documents in force at booking_date, grouped by effective date, newest first."""
    groups: dict[date, list[ContractTerms]] = defaultdict(list)
    for c in contracts:
        if c.effective_from is None:
            issues.add(
                Code.VERSION_CONFLICT,
                f"{c.document_id}: effective date could not be determined, so versions cannot be ordered",
            )
            continue
        if c.effective_evidence is not None and not c.effective_evidence.verified:
            issues.add(
                Code.UNVERIFIED_EVIDENCE,
                f"{c.document_id}: effective date quote not found in source",
                [c.effective_evidence],
            )
        if c.effective_from <= booking_date:
            groups[c.effective_from].append(c)
    return [groups[d] for d in sorted(groups, reverse=True)]


def _matching_rows(c: ContractTerms, b: Booking, night: date) -> list[RateRow]:
    return [
        r
        for r in c.rates
        if norm(r.room_type) == norm(b.room_type)
        and norm(r.meal_plan) == norm(b.meal_plan)
        and norm(r.occupancy) == norm(b.occupancy)
        and r.season_start <= night <= r.season_end
    ]


def _price_nights(
    b: Booking, nights: list[date], groups: list[list[ContractTerms]], issues: _Issues
) -> list[NightCharge]:
    charges: list[NightCharge] = []
    currency = norm(b.currency)
    for night in nights:
        chosen: tuple[RateRow, str] | None = None
        for group in groups:
            hits = [(r, c.document_id) for c in group for r in _matching_rows(c, b, night)]
            if not hits:
                continue
            distinct = {r.nightly_rate for r, _ in hits}
            docs = {d for _, d in hits}
            evid = [r.evidence for r, _ in hits]
            if len(distinct) > 1:
                code = Code.VERSION_CONFLICT if len(docs) > 1 else Code.AMBIGUOUS_RATE
                issues.add(
                    code,
                    f"{night}: {len(hits)} conflicting rates for {b.room_type}/{b.meal_plan}/{b.occupancy} "
                    f"in {', '.join(sorted(docs))}",
                    evid,
                )
            else:
                chosen = hits[0]
            break
        if chosen is None:
            if not any(_matching_rows(c, b, night) for g in groups for c in g):
                issues.add(
                    Code.RATE_NOT_FOUND,
                    f"no contracted rate for {b.room_type}/{b.meal_plan}/{b.occupancy} on {night}",
                )
            continue
        row, doc_id = chosen
        if row.nightly_rate is None:
            issues.add(Code.UNREADABLE_RATE, f"{night}: rate in {doc_id} is illegible or not stated", [row.evidence])
            continue
        if not row.evidence.verified:
            issues.add(
                Code.UNVERIFIED_EVIDENCE,
                f"{night}: rate {row.nightly_rate} could not be verified against {doc_id} ({row.evidence.reason})",
                [row.evidence],
            )
            continue
        if row.currency and norm(row.currency) != currency:
            issues.add(
                Code.CURRENCY_MISMATCH,
                f"contract rate is in {row.currency}, booking/invoice in {b.currency}; no FX rate is supplied",
                [row.evidence],
            )
            continue
        charges.append(NightCharge(night=night, rate=row.nightly_rate, document_id=doc_id, evidence=row.evidence))
    return charges


def _cancellation_terms(groups: list[list[ContractTerms]], issues: _Issues) -> tuple[Cancellation | None, bool]:
    """Returns (terms, conflict)."""
    for group in groups:
        terms = [(c.cancellation, c.document_id) for c in group if c.cancellation is not None]
        if not terms:
            continue
        distinct = {(t.free_cancellation_days, t.penalty_nights) for t, _ in terms}
        if len(distinct) > 1:
            issues.add(
                Code.VERSION_CONFLICT,
                "conflicting cancellation terms in " + ", ".join(d for _, d in terms),
                [t.evidence for t, _ in terms],
            )
            return None, True
        return terms[0][0], False
    return None, False


def _missing_fields(b: Booking) -> list[str]:
    required = ["booking_date", "check_in", "check_out", "room_type", "meal_plan", "occupancy", "rooms", "currency"]
    required += ["cancellation_date", "cancellation_fee_charged"] if b.status == "CANCELLED" else ["invoiced_total"]
    missing = [f for f in required if getattr(b, f) in (None, "")]
    if b.check_in and b.check_out and b.check_out <= b.check_in:
        missing.append("check_out (not after check_in)")
    if b.rooms is not None and b.rooms < 1:
        missing.append("rooms (must be >= 1)")
    return missing


def route_for(codes: list[Code]) -> Route:
    s = set(codes)
    if s & ESCALATE_CODES:
        return Route.ESCALATE
    if s & REQUEST_INFO_CODES:
        return Route.REQUEST_INFO
    if Code.OVERCHARGE in s:
        return Route.SUPPLIER_QUERY
    return Route.AUTO_CLEAR


def _severity(route: Route, codes: list[Code], delta: Decimal | None) -> str:
    if Code.SUSPECTED_INJECTION in codes or Code.VERSION_CONFLICT in codes:
        return "high"
    if Code.OVERCHARGE in codes and delta is not None:
        return "high" if delta >= HIGH_EXPOSURE else "medium" if delta >= MEDIUM_EXPOSURE else "low"
    if route in (Route.ESCALATE, Route.REQUEST_INFO):
        return "medium"
    return "low"


def audit(
    booking: Booking,
    contracts: list[ContractTerms],
    *,
    injection_hits: dict[str, list[str]] | None = None,
    failed_documents: list[str] | None = None,
) -> AuditResult:
    b = booking
    issues = _Issues()
    assumptions = [
        "Terms in force = latest contract version effective on or before the booking date.",
        f"Amounts within {TOLERANCE} {b.currency or ''} are treated as rounding differences.".replace("  ", " "),
    ]
    for source, hits in (injection_hits or {}).items():
        if hits:
            issues.add(Code.SUSPECTED_INJECTION, f"instruction-like text in {source}: “{hits[0][:160]}”")

    kind = "cancellation" if b.status == "CANCELLED" else "stay"
    result = dict(booking_id=b.booking_id, kind=kind, currency=b.currency, assumptions=assumptions)

    def finish(**extra) -> AuditResult:  # type: ignore[no-untyped-def]
        findings = issues.findings()
        codes = [f.code for f in findings]
        route = route_for(codes)
        return AuditResult(
            **result, **extra, findings=findings, codes=codes, route=route,
            severity=_severity(route, codes, extra.get("delta")),
        )

    if failed_documents:
        issues.add(Code.EXTRACTION_FAILED, "could not extract valid terms from: " + ", ".join(failed_documents))
        return finish()
    missing = _missing_fields(b)
    if missing:
        issues.add(Code.MISSING_BOOKING_FIELD, "missing or invalid booking fields: " + ", ".join(missing))
        return finish()
    assert b.booking_date and b.check_in and b.check_out and b.rooms

    groups = _applicable_groups(b.booking_date, contracts, issues)
    if not groups:
        issues.add(Code.NO_APPLICABLE_CONTRACT, f"no contract version in force on booking date {b.booking_date}")
        return finish()
    applied = [c.document_id for g in groups for c in g]

    dispute_deadline = None
    for c in (c for g in groups for c in g):
        if c.dispute_window_days is not None and b.invoice_date:
            dispute_deadline = b.invoice_date + timedelta(days=c.dispute_window_days)
            break

    nights = _nights(b.check_in, b.check_out)
    if kind == "stay":
        charged = b.invoiced_total
        charges = _price_nights(b, nights, groups, issues)
        if len(charges) != len(nights):
            return finish(nights=charges, applied_documents=applied, charged_amount=charged)
        expected = sum((n.rate for n in charges), Decimal("0")) * b.rooms
    else:
        charged = b.cancellation_fee_charged
        assert b.cancellation_date
        terms, conflict = _cancellation_terms(groups, issues)
        if terms is None or terms.free_cancellation_days is None or terms.penalty_nights is None:
            if not conflict:
                issues.add(Code.MISSING_CANCELLATION_TERMS, "cancellation terms not found in applicable contract")
            return finish(applied_documents=applied, charged_amount=charged)
        if not terms.evidence.verified:
            issues.add(Code.UNVERIFIED_EVIDENCE, "cancellation clause quote not found in source", [terms.evidence])
            return finish(applied_documents=applied, charged_amount=charged)
        days_before = (b.check_in - b.cancellation_date).days
        assumptions.append(
            f"Cancelled {days_before} day(s) before arrival; free cancellation requires "
            f"{terms.free_cancellation_days}; late penalty = {terms.penalty_nights} night(s)."
        )
        if days_before >= terms.free_cancellation_days:
            charges, expected = [], Decimal("0")
        else:
            penalised = nights[: terms.penalty_nights]
            charges = _price_nights(b, penalised, groups, issues)
            if len(charges) != len(penalised):
                return finish(nights=charges, applied_documents=applied, charged_amount=charged)
            expected = sum((n.rate for n in charges), Decimal("0")) * b.rooms

    assert charged is not None
    delta = charged - expected
    if abs(delta) <= TOLERANCE:
        issues.add(Code.MATCH, f"charged {charged} vs contracted {expected} {b.currency}")
    elif delta > 0:
        issues.add(Code.OVERCHARGE, f"charged {charged} vs contracted {expected} {b.currency} (+{delta})",
                   [n.evidence for n in charges][:3])
    else:
        issues.add(Code.UNDERCHARGE, f"charged {charged} vs contracted {expected} {b.currency} ({delta}); "
                   "possible later re-bill or wrong rate code", [n.evidence for n in charges][:3])
    return finish(
        nights=charges, applied_documents=applied, expected_amount=expected, charged_amount=charged,
        delta=delta, dispute_deadline=dispute_deadline,
    )
