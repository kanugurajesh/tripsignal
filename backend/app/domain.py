"""Domain schemas shared by the pipeline, API, and evaluation harness.

Money is always Decimal. Dates are always datetime.date. The LLM only produces
`ContractExtractionLLM`; everything downstream is computed deterministically.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

MealPlan = Literal["RO", "BB", "HB", "FB", "AI"]
Occupancy = Literal["SGL", "DBL", "TPL"]


# ---------------------------------------------------------------- LLM output
class Evidence(BaseModel):
    section: str = Field(description="Section heading or number where the text appears")
    quote: str = Field(description="Exact, verbatim excerpt from the document supporting the value")


class RateRowLLM(BaseModel):
    room_type: str = Field(description="Room category name exactly as written in the contract")
    meal_plan: MealPlan
    occupancy: Occupancy
    season_start: str = Field(description="First night the rate applies, YYYY-MM-DD")
    season_end: str = Field(description="Last night the rate applies (inclusive), YYYY-MM-DD")
    nightly_rate: str | None = Field(
        description="Per room per night amount as a plain decimal string, e.g. '145.00'. "
        "null if the amount is illegible or not stated."
    )
    currency: str | None = Field(description="ISO 4217 code, null if not stated")
    evidence: Evidence


class CancellationLLM(BaseModel):
    free_cancellation_days: int | None = Field(
        description="Cancellations at least this many days before arrival are free"
    )
    penalty_nights: int | None = Field(description="Nights charged for late cancellation")
    evidence: Evidence


class EffectiveLLM(BaseModel):
    effective_from: str = Field(description="Date from which this document's terms apply to new bookings, YYYY-MM-DD")
    evidence: Evidence


class NoShowLLM(BaseModel):
    penalty_nights: int | None = Field(description="Nights charged per room when the guest does not arrive")
    full_stay: bool = Field(description="True if a no-show is charged the entire booked stay")
    evidence: Evidence


class EarlyDepartureLLM(BaseModel):
    penalty_nights: int = Field(
        description="Unused nights charged per room when the guest leaves before the booked departure; "
        "0 if only nights stayed are charged"
    )
    evidence: Evidence


class UpgradeLLM(BaseModel):
    complimentary: bool = Field(
        description="True if upgrades made at the hotel's discretion are invoiced at the booked room's rate"
    )
    evidence: Evidence


class DisputeWindowLLM(BaseModel):
    days: int
    evidence: Evidence


class ContractExtractionLLM(BaseModel):
    hotel_name: str | None
    is_amendment: bool
    effective: EffectiveLLM | None
    rates: list[RateRowLLM]
    cancellation: CancellationLLM | None
    no_show: NoShowLLM | None
    early_departure: EarlyDepartureLLM | None
    upgrade: UpgradeLLM | None
    dispute_window: DisputeWindowLLM | None
    unreadable_notes: list[str] = Field(description="Values you could not read or that are ambiguous")


# ---------------------------------------------------------- verified records
class VerifiedEvidence(BaseModel):
    document_id: str
    section: str
    quote: str
    verified: bool
    reason: str | None = None


class RateRow(BaseModel):
    room_type: str
    meal_plan: str
    occupancy: str
    season_start: date
    season_end: date
    nightly_rate: Decimal | None
    currency: str | None
    evidence: VerifiedEvidence


class Cancellation(BaseModel):
    free_cancellation_days: int | None
    penalty_nights: int | None
    evidence: VerifiedEvidence


class NoShowPolicy(BaseModel):
    penalty_nights: int | None
    full_stay: bool
    evidence: VerifiedEvidence


class EarlyDeparturePolicy(BaseModel):
    penalty_nights: int
    evidence: VerifiedEvidence


class UpgradePolicy(BaseModel):
    complimentary: bool
    evidence: VerifiedEvidence


class ContractTerms(BaseModel):
    """A validated, evidence-checked extraction of one contract document."""

    document_id: str
    hotel_name: str | None
    is_amendment: bool
    effective_from: date | None
    effective_evidence: VerifiedEvidence | None
    rates: list[RateRow]
    cancellation: Cancellation | None
    no_show: NoShowPolicy | None = None
    early_departure: EarlyDeparturePolicy | None = None
    upgrade: UpgradePolicy | None = None
    dispute_window_days: int | None
    dispute_evidence: VerifiedEvidence | None
    unreadable_notes: list[str] = []
    schema_errors: list[str] = []


class ContractDocument(BaseModel):
    document_id: str
    hotel_id: str
    title: str
    received_on: date
    text: str


class Booking(BaseModel):
    booking_id: str
    hotel_id: str
    booking_date: date | None
    check_in: date | None
    check_out: date | None
    room_type: str | None
    meal_plan: str | None
    occupancy: str | None
    rooms: int | None = 1
    currency: str | None
    status: Literal["CONFIRMED", "CANCELLED", "NO_SHOW"] = "CONFIRMED"
    invoice_id: str | None = None
    invoice_date: date | None = None
    invoiced_total: Decimal | None = None
    cancellation_date: date | None = None
    cancellation_fee_charged: Decimal | None = None
    # What actually happened during the stay (None = as booked).
    actual_check_out: date | None = Field(None, description="Earlier = early departure, later = extension")
    extension_booked_on: date | None = Field(None, description="When the extension nights were agreed")
    stayed_room_type: str | None = Field(None, description="Room actually occupied, if different from booked")
    upgrade_reason: Literal["HOTEL", "GUEST_REQUEST"] | None = None
    guest_name: str = ""
    notes: str = Field("", description="Free text from the booking system; untrusted")


# ------------------------------------------------------------------ results
class Code(StrEnum):
    MATCH = "MATCH"
    OVERCHARGE = "OVERCHARGE"
    UNDERCHARGE = "UNDERCHARGE"
    MISSING_BOOKING_FIELD = "MISSING_BOOKING_FIELD"
    NO_APPLICABLE_CONTRACT = "NO_APPLICABLE_CONTRACT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    RATE_NOT_FOUND = "RATE_NOT_FOUND"
    AMBIGUOUS_RATE = "AMBIGUOUS_RATE"
    UNREADABLE_RATE = "UNREADABLE_RATE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    SUSPECTED_INJECTION = "SUSPECTED_INJECTION"
    MISSING_CANCELLATION_TERMS = "MISSING_CANCELLATION_TERMS"
    MISSING_POLICY_TERMS = "MISSING_POLICY_TERMS"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class Route(StrEnum):
    AUTO_CLEAR = "AUTO_CLEAR"
    SUPPLIER_QUERY = "SUPPLIER_QUERY"
    REQUEST_INFO = "REQUEST_INFO"
    ESCALATE = "ESCALATE"


ESCALATE_CODES = {
    Code.SUSPECTED_INJECTION,
    Code.VERSION_CONFLICT,
    Code.AMBIGUOUS_RATE,
    Code.UNVERIFIED_EVIDENCE,
    Code.UNDERCHARGE,
    Code.EXTRACTION_FAILED,
}
REQUEST_INFO_CODES = {
    Code.MISSING_BOOKING_FIELD,
    Code.NO_APPLICABLE_CONTRACT,
    Code.RATE_NOT_FOUND,
    Code.UNREADABLE_RATE,
    Code.CURRENCY_MISMATCH,
    Code.MISSING_CANCELLATION_TERMS,
    Code.MISSING_POLICY_TERMS,
}


class Finding(BaseModel):
    code: Code
    message: str
    evidence: list[VerifiedEvidence] = []


NightBasis = Literal["stay", "extension", "early_departure_penalty", "no_show_penalty", "cancellation_penalty"]
TravellerEvent = Literal["cancellation", "no_show", "early_departure", "extension", "hotel_upgrade", "guest_upgrade"]


class NightCharge(BaseModel):
    night: date
    basis: NightBasis = "stay"
    room_type: str | None = None
    rate: Decimal
    document_id: str
    evidence: VerifiedEvidence


class AuditResult(BaseModel):
    booking_id: str
    route: Route
    severity: Literal["low", "medium", "high"]
    codes: list[Code]
    findings: list[Finding]
    kind: Literal["stay", "cancellation", "no_show"]
    traveller_events: list[TravellerEvent] = []
    currency: str | None
    expected_amount: Decimal | None = Field(None, description="Calculated from contract terms")
    charged_amount: Decimal | None = Field(None, description="From supplier invoice (as received)")
    delta: Decimal | None = Field(None, description="charged - expected; positive = overcharge")
    nights: list[NightCharge] = []
    clauses: list[VerifiedEvidence] = Field([], description="Cancellation / no-show / early-departure / upgrade "
                                            "clauses that determined which nights are billable")
    applied_documents: list[str] = []
    dispute_deadline: date | None = None
    assumptions: list[str] = []
