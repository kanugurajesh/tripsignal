"""Traveller flow beyond 'stayed as booked': no-shows, early departures,
extensions, and room changes. Base contract: Deluxe BB DBL 145 (Apr-Jun) /
195 (Jul-Sep); default booking is 3 nights from 10 May (435.00)."""

from datetime import date
from decimal import Decimal

from app.domain import Code, ContractDocument, ContractExtractionLLM, Route
from app.pipeline.engine import audit
from app.pipeline.extraction import to_terms
from app.pipeline.narrative import template
from tests.conftest import booking, ev, row, terms


def codes(r):  # type: ignore[no-untyped-def]
    return {c.value for c in r.codes}


def with_suite(**kw):  # type: ignore[no-untyped-def]
    return terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00"),
                                         row("Suite", "2026-04-01", "2026-06-30", "220.00")], **kw)


# ------------------------------------------------------------------ no-show
def test_no_show_is_charged_the_contracted_penalty_nights(base_contract):
    ok = audit(booking(status="NO_SHOW", invoiced_total=Decimal("145.00")), [base_contract])
    assert ok.route == Route.AUTO_CLEAR and ok.kind == "no_show" and ok.traveller_events == ["no_show"]
    assert [(n.night, n.basis) for n in ok.nights] == [(date(2026, 5, 10), "no_show_penalty")]
    full = audit(booking(status="NO_SHOW", invoiced_total=Decimal("435.00")), [base_contract])
    assert full.route == Route.SUPPLIER_QUERY and full.delta == Decimal("290.00")


def test_full_stay_no_show_clause_charges_every_booked_night():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], no_show="full")
    r = audit(booking(status="NO_SHOW", invoiced_total=Decimal("435.00"), rooms=1), [t])
    assert r.route == Route.AUTO_CLEAR and r.expected_amount == Decimal("435.00")


def test_no_show_without_clause_requests_info_and_is_not_inferred_from_cancellation():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], no_show=None)
    r = audit(booking(status="NO_SHOW", invoiced_total=Decimal("145.00")), [t])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"MISSING_POLICY_TERMS"} and r.expected_amount is None


def test_unverified_no_show_clause_escalates(base_contract):
    base_contract.no_show.evidence = ev("DOC-1", "no-show", verified=False)  # type: ignore[union-attr]
    r = audit(booking(status="NO_SHOW", invoiced_total=Decimal("145.00")), [base_contract])
    assert r.route == Route.ESCALATE and Code.UNVERIFIED_EVIDENCE in r.codes


def test_amended_no_show_clause_applies_by_booking_date(base_contract):
    amend = terms("DOC-2", "2026-04-01", [], cancel=None, dispute=None, no_show=2, early_departure=None,
                  upgrade_complimentary=None)
    ns = dict(status="NO_SHOW", invoiced_total=Decimal("290.00"))
    after = audit(booking(booking_date=date(2026, 4, 2), **ns), [base_contract, amend])
    assert after.route == Route.AUTO_CLEAR
    before = audit(booking(booking_date=date(2026, 3, 1), **ns), [base_contract, amend])
    assert before.route == Route.SUPPLIER_QUERY and before.delta == Decimal("145.00")


def test_no_show_with_stay_details_is_contradictory(base_contract):
    r = audit(booking(status="NO_SHOW", actual_check_out=date(2026, 5, 12)), [base_contract])
    assert codes(r) == {"MISSING_BOOKING_FIELD"} and "no_show" in r.findings[0].message


# ---------------------------------------------------------- early departure
def test_early_departure_bills_stayed_nights_plus_penalty(base_contract):
    r = audit(booking(actual_check_out=date(2026, 5, 11), invoiced_total=Decimal("290.00")), [base_contract])
    assert r.route == Route.AUTO_CLEAR and r.traveller_events == ["early_departure"]
    assert [n.basis for n in r.nights] == ["stay", "early_departure_penalty"]
    # supplier billed the full booked stay: the second unused night is an overcharge
    r = audit(booking(actual_check_out=date(2026, 5, 11), invoiced_total=Decimal("435.00")), [base_contract])
    assert r.route == Route.SUPPLIER_QUERY and r.delta == Decimal("145.00")


def test_early_departure_penalty_is_capped_at_unused_nights():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], early_departure=3)
    r = audit(booking(actual_check_out=date(2026, 5, 12), invoiced_total=Decimal("435.00")), [t])
    assert r.route == Route.AUTO_CLEAR and len(r.nights) == 3


def test_zero_penalty_early_departure_and_missing_clause():
    zero = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], early_departure=0)
    r = audit(booking(actual_check_out=date(2026, 5, 12), invoiced_total=Decimal("290.00")), [zero])
    assert r.route == Route.AUTO_CLEAR and r.expected_amount == Decimal("290.00")
    none = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], early_departure=None)
    r = audit(booking(actual_check_out=date(2026, 5, 12), invoiced_total=Decimal("290.00")), [none])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"MISSING_POLICY_TERMS"}


# ---------------------------------------------------------------- extension
def test_extension_nights_use_terms_in_force_when_extension_was_agreed(base_contract):
    amend = terms("DOC-2", "2026-05-11", [row("Deluxe", "2026-04-01", "2026-06-30", "160.00", doc="DOC-2")],
                  cancel=None, dispute=None, no_show=None, early_departure=None, upgrade_complimentary=None)
    ext = dict(actual_check_out=date(2026, 5, 15), extension_booked_on=date(2026, 5, 12))
    r = audit(booking(invoiced_total=Decimal("755.00"), **ext), [base_contract, amend])
    assert r.route == Route.AUTO_CLEAR and r.traveller_events == ["extension"]
    assert [(n.basis, n.document_id, n.rate) for n in r.nights[3:]] == [("extension", "DOC-2", Decimal("160.00"))] * 2
    # original nights stay on the booking-date version even though a newer one now exists
    assert {n.document_id for n in r.nights[:3]} == {"DOC-1"}
    old_rate = audit(booking(invoiced_total=Decimal("725.00"), **ext), [base_contract, amend])
    assert old_rate.route == Route.ESCALATE and codes(old_rate) == {"UNDERCHARGE"}


def test_extension_requires_a_valid_agreement_date(base_contract):
    r = audit(booking(actual_check_out=date(2026, 5, 15)), [base_contract])
    assert codes(r) == {"MISSING_BOOKING_FIELD"} and "extension_booked_on" in r.findings[0].message
    r = audit(booking(actual_check_out=date(2026, 5, 15), extension_booked_on=date(2026, 2, 1)), [base_contract])
    assert codes(r) == {"MISSING_BOOKING_FIELD"}


def test_departure_on_or_before_arrival_is_invalid(base_contract):
    r = audit(booking(actual_check_out=date(2026, 5, 10)), [base_contract])
    assert codes(r) == {"MISSING_BOOKING_FIELD"}


# -------------------------------------------------------------- room change
def test_complimentary_hotel_upgrade_is_billed_at_booked_room():
    up = dict(stayed_room_type="Suite", upgrade_reason="HOTEL")
    ok = audit(booking(invoiced_total=Decimal("435.00"), **up), [with_suite()])
    assert ok.route == Route.AUTO_CLEAR and ok.traveller_events == ["hotel_upgrade"]
    assert {n.room_type for n in ok.nights} == {"Deluxe"}
    billed_suite = audit(booking(invoiced_total=Decimal("660.00"), **up), [with_suite()])
    assert billed_suite.route == Route.SUPPLIER_QUERY and billed_suite.delta == Decimal("225.00")


def test_upgrade_billed_at_room_occupied_when_contract_or_guest_says_so():
    up = dict(stayed_room_type="Suite", invoiced_total=Decimal("660.00"))
    paid = audit(booking(upgrade_reason="HOTEL", **up), [with_suite(upgrade_complimentary=False)])
    assert paid.route == Route.AUTO_CLEAR and {n.room_type for n in paid.nights} == {"Suite"}
    guest = audit(booking(upgrade_reason="GUEST_REQUEST", **up), [with_suite()])
    assert guest.route == Route.AUTO_CLEAR and guest.traveller_events == ["guest_upgrade"]


def test_room_change_without_reason_or_clause_abstains():
    r = audit(booking(stayed_room_type="Suite"), [with_suite()])
    assert codes(r) == {"MISSING_BOOKING_FIELD"}
    r = audit(booking(stayed_room_type="Suite", upgrade_reason="HOTEL"), [with_suite(upgrade_complimentary=None)])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"MISSING_POLICY_TERMS"}


def test_same_room_with_different_spelling_is_not_a_room_change(base_contract):
    r = audit(booking(stayed_room_type=" deluxe "), [base_contract])
    assert r.route == Route.AUTO_CLEAR and r.traveller_events == []


def test_combined_upgrade_and_early_departure():
    r = audit(booking(stayed_room_type="Suite", upgrade_reason="HOTEL", actual_check_out=date(2026, 5, 11),
                      invoiced_total=Decimal("660.00")), [with_suite()])
    assert r.traveller_events == ["early_departure", "hotel_upgrade"]
    assert r.expected_amount == Decimal("290.00") and r.delta == Decimal("370.00")


def test_supplier_email_explains_traveller_events(base_contract):
    b = booking(actual_check_out=date(2026, 5, 11), invoiced_total=Decimal("435.00"))
    r = audit(b, [base_contract])
    body = template(r, b).draft_body or ""
    assert "left before the booked check-out" in body and "(early-departure penalty)" in body
    # the clause that made the extra night billable is cited, not just the nightly rate
    assert r.clauses == [base_contract.early_departure.evidence]  # type: ignore[union-attr]
    assert "Contract terms applied:" in body and "early departure" in body
    assert base_contract.early_departure.evidence in r.findings[0].evidence  # type: ignore[union-attr]


# --------------------------------------------------------------- extraction
DOC = ContractDocument(document_id="D1", hotel_id="H", title="t", received_on=date(2026, 1, 1), text=(
    "4. CANCELLATION\nCancellations received 14 days or more before arrival are free of charge; later "
    "cancellations and no-shows are charged 1 night per room.\n5. STAY CHANGES\n"
    "Guests departing before the booked departure date are charged for nights stayed only."))


def _extract(**kw):  # type: ignore[no-untyped-def]
    base = dict(hotel_name="H", is_amendment=False, effective=None, rates=[], cancellation=None, no_show=None,
                early_departure=None, upgrade=None, dispute_window=None, unreadable_notes=[])
    return to_terms(DOC, ContractExtractionLLM.model_validate({**base, **kw}))


def test_stay_change_clauses_are_verified_against_source():
    shared = "later cancellations and no-shows are charged 1 night per room."
    t = _extract(no_show={"penalty_nights": 1, "full_stay": False, "evidence": {"section": "4", "quote": shared}},
                 early_departure={"penalty_nights": 0, "evidence": {"section": "5", "quote":
                                  "Guests departing before the booked departure date are charged for nights stayed only."}})
    assert t.no_show and t.no_show.evidence.verified and t.early_departure and t.early_departure.evidence.verified
    wrong = _extract(no_show={"penalty_nights": 2, "full_stay": False, "evidence": {"section": "4", "quote": shared}},
                     upgrade={"complimentary": True, "evidence": {"section": "5", "quote": "Upgrades are free of charge."}})
    assert wrong.no_show and not wrong.no_show.evidence.verified  # 2 is not in the quote
    assert wrong.upgrade and not wrong.upgrade.evidence.verified  # quote is not in the document
