"""Deterministic audit engine: version selection, nightly pricing, comparison, routing.

No LLM calls happen here. Every amount is derived from verified contract rows
and booking fields, and every blocking condition produces a typed finding.

Version rule (see docs/DECISIONS.md D3): the terms in force for a booking are
those of documents whose effective_from <= booking_date. For each night, the
newest such document that prices the room/meal/occupancy for that night wins
(amendments override only what they restate). Two documents with the same
effective date that disagree are a VERSION_CONFLICT; we never pick one.

Traveller flow (D12): a booking can end as a stay (possibly with an early
departure, an extension, or a room change), a cancellation, or a no-show. Each
is priced night by night from the contract clause that governs it; if that
clause is missing, conflicting or unverified, the engine abstains.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.domain import (
    ESCALATE_CODES,
    REQUEST_INFO_CODES,
    AuditResult,
    Booking,
    Code,
    ContractTerms,
    Finding,
    NightBasis,
    NightCharge,
    RateRow,
    Route,
    TravellerEvent,
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
        self.clauses: list[VerifiedEvidence] = []  # verified policy clauses the result relies on

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


def _matching_rows(c: ContractTerms, b: Booking, room: str | None, night: date) -> list[RateRow]:
    return [
        r
        for r in c.rates
        if norm(r.room_type) == norm(room)
        and norm(r.meal_plan) == norm(b.meal_plan)
        and norm(r.occupancy) == norm(b.occupancy)
        and r.season_start <= night <= r.season_end
    ]


def _price_nights(
    b: Booking, nights: list[date], groups: list[list[ContractTerms]], issues: _Issues, *,
    room: str | None = None, basis: NightBasis = "stay",
) -> list[NightCharge]:
    room = room or b.room_type
    charges: list[NightCharge] = []
    currency = norm(b.currency)
    for night in nights:
        chosen: tuple[RateRow, str] | None = None
        for group in groups:
            hits = [(r, c.document_id) for c in group for r in _matching_rows(c, b, room, night)]
            if not hits:
                continue
            distinct = {r.nightly_rate for r, _ in hits}
            docs = {d for _, d in hits}
            evid = [r.evidence for r, _ in hits]
            if len(distinct) > 1:
                code = Code.VERSION_CONFLICT if len(docs) > 1 else Code.AMBIGUOUS_RATE
                issues.add(
                    code,
                    f"{night}: {len(hits)} conflicting rates for {room}/{b.meal_plan}/{b.occupancy} "
                    f"in {', '.join(sorted(docs))}",
                    evid,
                )
            else:
                chosen = hits[0]
            break
        if chosen is None:
            if not any(_matching_rows(c, b, room, night) for g in groups for c in g):
                issues.add(
                    Code.RATE_NOT_FOUND,
                    f"no contracted rate for {room}/{b.meal_plan}/{b.occupancy} on {night}",
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
        charges.append(NightCharge(night=night, basis=basis, room_type=row.room_type, rate=row.nightly_rate,
                                   document_id=doc_id, evidence=row.evidence))
    return charges


def _policy(groups: list[list[ContractTerms]], attr: str, label: str, missing: Code, issues: _Issues) -> Any:
    """The clause `attr` from the newest version that states it. Adds a finding and
    returns None if no version states it, same-date versions disagree, or its quote
    is unverified."""
    for group in groups:
        found = [(getattr(c, attr), c.document_id) for c in group if getattr(c, attr) is not None]
        if not found:
            continue
        if len({p.model_dump_json(exclude={"evidence"}) for p, _ in found}) > 1:
            issues.add(Code.VERSION_CONFLICT, f"conflicting {label} terms in " + ", ".join(d for _, d in found),
                       [p.evidence for p, _ in found])
            return None
        p = found[0][0]
        if not p.evidence.verified:
            issues.add(Code.UNVERIFIED_EVIDENCE, f"{label} clause quote not found in source", [p.evidence])
            return None
        if p.evidence not in issues.clauses:
            issues.clauses.append(p.evidence)
        return p
    issues.add(missing, f"{label} terms not found in applicable contract")
    return None


def _missing_fields(b: Booking) -> list[str]:
    required = ["booking_date", "check_in", "check_out", "room_type", "meal_plan", "occupancy", "rooms", "currency"]
    required += ["cancellation_date", "cancellation_fee_charged"] if b.status == "CANCELLED" else ["invoiced_total"]
    missing = [f for f in required if getattr(b, f) in (None, "")]
    if b.check_in and b.check_out and b.check_out <= b.check_in:
        missing.append("check_out (not after check_in)")
    if b.rooms is not None and b.rooms < 1:
        missing.append("rooms (must be >= 1)")
    if b.status != "CONFIRMED":
        for f in ("actual_check_out", "extension_booked_on", "stayed_room_type"):
            if getattr(b, f) is not None:
                missing.append(f"{f} (set on a {b.status.lower()} booking)")
        return missing
    if b.actual_check_out and b.check_in and b.actual_check_out <= b.check_in:
        missing.append("actual_check_out (not after check_in)")
    if b.actual_check_out and b.check_out and b.actual_check_out > b.check_out:
        if b.extension_booked_on is None:
            missing.append("extension_booked_on (needed to price extension nights)")
        elif b.booking_date and b.extension_booked_on < b.booking_date:
            missing.append("extension_booked_on (before booking_date)")
    if b.stayed_room_type and norm(b.stayed_room_type) != norm(b.room_type) and b.upgrade_reason is None:
        missing.append("upgrade_reason (room changed without a recorded reason)")
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


def traveller_events(b: Booking) -> list[TravellerEvent]:
    if b.status == "CANCELLED":
        return ["cancellation"]
    if b.status == "NO_SHOW":
        return ["no_show"]
    events: list[TravellerEvent] = []
    if b.actual_check_out and b.check_out and b.actual_check_out < b.check_out:
        events.append("early_departure")
    if b.actual_check_out and b.check_out and b.actual_check_out > b.check_out:
        events.append("extension")
    if b.stayed_room_type and norm(b.stayed_room_type) != norm(b.room_type):
        events.append("guest_upgrade" if b.upgrade_reason == "GUEST_REQUEST" else "hotel_upgrade")
    return events


def _billable_room(b: Booking, groups: list[list[ContractTerms]], events: list[TravellerEvent],
                   issues: _Issues, assumptions: list[str]) -> str | None:
    """The room category whose contracted rate applies, after any room change."""
    if "guest_upgrade" in events:
        assumptions.append(f"Guest requested the change to {b.stayed_room_type}, so its contracted rate applies.")
        return b.stayed_room_type
    if "hotel_upgrade" not in events:
        return b.room_type
    policy = _policy(groups, "upgrade", "hotel-initiated upgrade", Code.MISSING_POLICY_TERMS, issues)
    if policy is None:
        return None
    if policy.complimentary:
        assumptions.append(f"Hotel moved the guest to {b.stayed_room_type}; the contract makes such upgrades "
                           f"complimentary, so the booked {b.room_type} rate applies.")
        return b.room_type
    assumptions.append(f"Hotel moved the guest to {b.stayed_room_type}; the contract bills the room occupied.")
    return b.stayed_room_type


def _stay_charges(b: Booking, contracts: list[ContractTerms], groups: list[list[ContractTerms]],
                  events: list[TravellerEvent], issues: _Issues, assumptions: list[str]) -> list[NightCharge] | None:
    """Nights the supplier may bill for a stay, or None if any of them cannot be priced."""
    assert b.check_in and b.check_out
    room = _billable_room(b, groups, events, issues, assumptions)
    if room is None:
        return None
    departure = b.actual_check_out or b.check_out
    booked = _nights(b.check_in, b.check_out)
    stayed = [n for n in booked if n < departure]
    wanted = list(stayed)
    charges = _price_nights(b, stayed, groups, issues, room=room)
    if "early_departure" in events:
        policy = _policy(groups, "early_departure", "early-departure", Code.MISSING_POLICY_TERMS, issues)
        if policy is None:
            return None
        unused = booked[len(stayed):]
        penalised = unused[: policy.penalty_nights]
        assumptions.append(f"Guest left after {len(stayed)} of {len(booked)} booked night(s); the contract charges "
                           f"{policy.penalty_nights} unused night(s), so {len(penalised)} penalty night(s) apply.")
        wanted += penalised
        charges += _price_nights(b, penalised, groups, issues, room=room, basis="early_departure_penalty")
    if "extension" in events:
        assert b.extension_booked_on
        ext_groups = _applicable_groups(b.extension_booked_on, contracts, issues)
        extra = _nights(b.check_out, departure)
        assumptions.append(f"{len(extra)} extension night(s) agreed on {b.extension_booked_on} are priced at the "
                           "terms in force on that date, not the original booking date.")
        if not ext_groups:
            issues.add(Code.NO_APPLICABLE_CONTRACT, f"no contract version in force on extension date {b.extension_booked_on}")
            return None
        wanted += extra
        charges += _price_nights(b, extra, ext_groups, issues, room=room, basis="extension")
    return charges if len(charges) == len(wanted) else None


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

    kind = {"CANCELLED": "cancellation", "NO_SHOW": "no_show"}.get(b.status, "stay")
    events = traveller_events(b)
    result = dict(booking_id=b.booking_id, kind=kind, traveller_events=events, currency=b.currency,
                  assumptions=assumptions)

    def finish(**extra) -> AuditResult:  # type: ignore[no-untyped-def]
        findings = issues.findings()
        codes = [f.code for f in findings]
        route = route_for(codes)
        return AuditResult(
            **result, **extra, findings=findings, codes=codes, route=route, clauses=issues.clauses,
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
        stay = _stay_charges(b, contracts, groups, events, issues, assumptions)
        if stay is None:
            return finish(applied_documents=applied, charged_amount=charged)
        charges = stay
    elif kind == "no_show":
        charged = b.invoiced_total
        ns = _policy(groups, "no_show", "no-show", Code.MISSING_POLICY_TERMS, issues)
        if ns is None:
            return finish(applied_documents=applied, charged_amount=charged)
        if not ns.full_stay and ns.penalty_nights is None:
            issues.add(Code.MISSING_POLICY_TERMS, "no-show clause states neither a night count nor the full stay",
                       [ns.evidence])
            return finish(applied_documents=applied, charged_amount=charged)
        penalised = nights if ns.full_stay else nights[: ns.penalty_nights]
        assumptions.append("Guest did not arrive; the contract charges "
                           + ("the full booked stay." if ns.full_stay else f"{ns.penalty_nights} night(s) per room."))
        charges = _price_nights(b, penalised, groups, issues, basis="no_show_penalty")
        if len(charges) != len(penalised):
            return finish(nights=charges, applied_documents=applied, charged_amount=charged)
    else:
        charged = b.cancellation_fee_charged
        assert b.cancellation_date
        terms = _policy(groups, "cancellation", "cancellation", Code.MISSING_CANCELLATION_TERMS, issues)
        if terms is None:
            return finish(applied_documents=applied, charged_amount=charged)
        if terms.free_cancellation_days is None or terms.penalty_nights is None:
            issues.add(Code.MISSING_CANCELLATION_TERMS, "cancellation terms not found in applicable contract")
            return finish(applied_documents=applied, charged_amount=charged)
        days_before = (b.check_in - b.cancellation_date).days
        assumptions.append(
            f"Cancelled {days_before} day(s) before arrival; free cancellation requires "
            f"{terms.free_cancellation_days}; late penalty = {terms.penalty_nights} night(s)."
        )
        if days_before >= terms.free_cancellation_days:
            charges = []
        else:
            penalised = nights[: terms.penalty_nights]
            charges = _price_nights(b, penalised, groups, issues, basis="cancellation_penalty")
            if len(charges) != len(penalised):
                return finish(nights=charges, applied_documents=applied, charged_amount=charged)

    expected = sum((n.rate for n in charges), Decimal("0")) * b.rooms
    assert charged is not None
    delta = charged - expected
    cited = [*issues.clauses, *[n.evidence for n in charges][:3]]
    if abs(delta) <= TOLERANCE:
        issues.add(Code.MATCH, f"charged {charged} vs contracted {expected} {b.currency}")
    elif delta > 0:
        issues.add(Code.OVERCHARGE, f"charged {charged} vs contracted {expected} {b.currency} (+{delta})", cited)
    else:
        issues.add(Code.UNDERCHARGE, f"charged {charged} vs contracted {expected} {b.currency} ({delta}); "
                   "possible later re-bill or wrong rate code", cited)
    return finish(
        nights=charges, applied_documents=applied, expected_amount=expected, charged_amount=charged,
        delta=delta, dispute_deadline=dispute_deadline,
    )
