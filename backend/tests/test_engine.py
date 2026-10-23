from datetime import date
from decimal import Decimal

from app.domain import Code, Route
from app.pipeline.engine import audit
from tests.conftest import booking, row, terms


def codes(r):  # type: ignore[no-untyped-def]
    return {c.value for c in r.codes}


def test_exact_match_auto_clears(base_contract):
    r = audit(booking(), [base_contract])
    assert r.route == Route.AUTO_CLEAR and codes(r) == {"MATCH"}
    assert r.expected_amount == Decimal("435.00") and r.delta == 0
    assert [n.rate for n in r.nights] == [Decimal("145.00")] * 3
    assert r.dispute_deadline == date(2026, 6, 12)


def test_overcharge_routes_to_supplier_query_with_exact_delta(base_contract):
    r = audit(booking(invoiced_total=Decimal("510.00")), [base_contract])
    assert r.route == Route.SUPPLIER_QUERY and r.delta == Decimal("75.00")
    assert r.findings[0].evidence, "overcharge must cite contract evidence"


def test_within_tolerance_is_match_but_just_outside_is_not(base_contract):
    assert audit(booking(invoiced_total=Decimal("436.00")), [base_contract]).route == Route.AUTO_CLEAR
    assert audit(booking(invoiced_total=Decimal("436.01")), [base_contract]).route == Route.SUPPLIER_QUERY


def test_undercharge_escalates(base_contract):
    r = audit(booking(invoiced_total=Decimal("400.00")), [base_contract])
    assert r.route == Route.ESCALATE and codes(r) == {"UNDERCHARGE"}


def test_season_straddle_prices_each_night_and_checkout_day_is_free(base_contract):
    r = audit(booking(check_in=date(2026, 6, 29), check_out=date(2026, 7, 2), invoiced_total=Decimal("485.00")),
              [base_contract])
    assert [n.rate for n in r.nights] == [Decimal("145.00"), Decimal("145.00"), Decimal("195.00")]
    assert r.route == Route.AUTO_CLEAR
    # last night of season, checkout first day of next: one night at old rate
    r = audit(booking(check_in=date(2026, 6, 30), check_out=date(2026, 7, 1), invoiced_total=Decimal("145.00")),
              [base_contract])
    assert r.route == Route.AUTO_CLEAR


def test_multi_room_multiplies(base_contract):
    r = audit(booking(rooms=2, invoiced_total=Decimal("870.00")), [base_contract])
    assert r.route == Route.AUTO_CLEAR and r.expected_amount == Decimal("870.00")


def test_amendment_applies_by_booking_date_and_falls_back_for_unlisted_rows(base_contract):
    amend = terms("DOC-2", "2026-06-01", [row("Deluxe", "2026-07-01", "2026-09-30", "180.00", doc="DOC-2")],
                  cancel=None, dispute=None)
    stay = dict(check_in=date(2026, 7, 10), check_out=date(2026, 7, 12))
    after = audit(booking(booking_date=date(2026, 6, 1), invoiced_total=Decimal("360.00"), **stay), [base_contract, amend])
    assert after.route == Route.AUTO_CLEAR and {n.document_id for n in after.nights} == {"DOC-2"}
    before = audit(booking(booking_date=date(2026, 5, 31), invoiced_total=Decimal("390.00"), **stay), [base_contract, amend])
    assert before.route == Route.AUTO_CLEAR and {n.document_id for n in before.nights} == {"DOC-1"}
    # amendment has no April rate -> base contract still prices April nights
    april = audit(booking(booking_date=date(2026, 6, 2), invoiced_total=Decimal("435.00")), [base_contract, amend])
    assert april.route == Route.AUTO_CLEAR


def test_same_date_conflicting_amendments_are_never_resolved_silently(base_contract):
    a = terms("DOC-2", "2026-06-01", [row("Deluxe", "2026-07-01", "2026-09-30", "180.00", doc="DOC-2")], cancel=None)
    b = terms("DOC-3", "2026-06-01", [row("Deluxe", "2026-07-01", "2026-09-30", "170.00", doc="DOC-3")], cancel=None)
    r = audit(booking(booking_date=date(2026, 6, 5), check_in=date(2026, 7, 10), check_out=date(2026, 7, 11),
                      invoiced_total=Decimal("180.00")), [base_contract, a, b])
    assert r.route == Route.ESCALATE and Code.VERSION_CONFLICT in r.codes and r.delta is None


def test_duplicate_rows_with_different_rates_in_one_doc_is_ambiguous():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00"),
                                      row("Deluxe", "2026-05-01", "2026-05-31", "150.00")])
    r = audit(booking(), [t])
    assert r.route == Route.ESCALATE and Code.AMBIGUOUS_RATE in r.codes


def test_unreadable_rate_requests_info():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", None)])
    r = audit(booking(), [t])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"UNREADABLE_RATE"} and r.expected_amount is None


def test_unverified_evidence_escalates_and_is_not_priced():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00", verified=False)])
    r = audit(booking(), [t])
    assert r.route == Route.ESCALATE and Code.UNVERIFIED_EVIDENCE in r.codes and r.expected_amount is None


def test_currency_mismatch_does_not_invent_fx(base_contract):
    r = audit(booking(currency="USD"), [base_contract])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"CURRENCY_MISMATCH"} and r.delta is None


def test_rate_not_found_and_no_applicable_contract(base_contract):
    assert codes(audit(booking(room_type="Suite"), [base_contract])) == {"RATE_NOT_FOUND"}
    assert codes(audit(booking(check_in=date(2027, 1, 1), check_out=date(2027, 1, 2)), [base_contract])) == {"RATE_NOT_FOUND"}
    r = audit(booking(booking_date=date(2025, 12, 31)), [base_contract])
    assert r.route == Route.REQUEST_INFO and codes(r) == {"NO_APPLICABLE_CONTRACT"}


def test_missing_and_invalid_booking_fields(base_contract):
    for kw in ({"meal_plan": None}, {"invoiced_total": None}, {"booking_date": None},
               {"check_out": date(2026, 5, 9)}, {"rooms": 0}):
        r = audit(booking(**kw), [base_contract])
        assert r.route == Route.REQUEST_INFO and codes(r) == {"MISSING_BOOKING_FIELD"}, kw


def test_room_type_matching_is_whitespace_and_case_insensitive(base_contract):
    assert audit(booking(room_type="  deluxe "), [base_contract]).route == Route.AUTO_CLEAR


def test_cancellation_free_window_boundary_and_penalty(base_contract):
    cx = dict(status="CANCELLED", invoiced_total=None, check_in=date(2026, 5, 20), check_out=date(2026, 5, 23))
    free = audit(booking(cancellation_date=date(2026, 5, 6), cancellation_fee_charged=Decimal("0"), **cx), [base_contract])
    assert free.route == Route.AUTO_CLEAR and free.expected_amount == 0  # exactly 14 days before = free
    charged_in_free = audit(booking(cancellation_date=date(2026, 5, 6), cancellation_fee_charged=Decimal("145.00"), **cx),
                            [base_contract])
    assert charged_in_free.route == Route.SUPPLIER_QUERY and charged_in_free.delta == Decimal("145.00")
    late = audit(booking(cancellation_date=date(2026, 5, 7), cancellation_fee_charged=Decimal("145.00"), **cx), [base_contract])
    assert late.route == Route.AUTO_CLEAR and late.expected_amount == Decimal("145.00")
    full = audit(booking(cancellation_date=date(2026, 5, 7), cancellation_fee_charged=Decimal("435.00"), **cx), [base_contract])
    assert full.route == Route.SUPPLIER_QUERY and full.delta == Decimal("290.00")


def test_cancellation_without_terms_requests_info():
    t = terms("DOC-1", "2026-01-01", [row("Deluxe", "2026-04-01", "2026-06-30", "145.00")], cancel=None)
    r = audit(booking(status="CANCELLED", cancellation_date=date(2026, 5, 9), cancellation_fee_charged=Decimal("145")), [t])
    assert codes(r) == {"MISSING_CANCELLATION_TERMS"} and r.route == Route.REQUEST_INFO


def test_injection_forces_escalation_even_when_amounts_match(base_contract):
    r = audit(booking(), [base_contract], injection_hits={"DOC-1": ["ignore previous instructions"]})
    assert r.route == Route.ESCALATE and codes(r) == {"MATCH", "SUSPECTED_INJECTION"} and r.severity == "high"


def test_extraction_failure_escalates_without_pricing(base_contract):
    r = audit(booking(), [base_contract], failed_documents=["DOC-2"])
    assert r.route == Route.ESCALATE and codes(r) == {"EXTRACTION_FAILED"} and r.expected_amount is None


def test_severity_scales_with_exposure(base_contract):
    assert audit(booking(invoiced_total=Decimal("480")), [base_contract]).severity == "low"
    assert audit(booking(invoiced_total=Decimal("600")), [base_contract]).severity == "medium"
    assert audit(booking(invoiced_total=Decimal("1000")), [base_contract]).severity == "high"
