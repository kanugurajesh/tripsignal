"""Orchestrates one audit: scan -> extract (cached per document) -> engine -> narrative."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.domain import AuditResult, Booking, ContractDocument
from app.pipeline import engine, injection
from app.pipeline.extraction import PROMPT_VERSION, ExtractionOutcome, extract_contract
from app.pipeline.narrative import NarrativeOut, generate
from app.providers.base import LLMProvider


def doc_hash(doc: ContractDocument) -> str:
    return hashlib.sha256(doc.text.encode()).hexdigest()


class ExtractionCache:
    """Keyed by (document hash, provider, model, prompt version): re-auditing never
    re-bills extraction of an unchanged document."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str, str, str], ExtractionOutcome] = {}

    def get_or_extract(self, doc: ContractDocument, provider: LLMProvider) -> tuple[ExtractionOutcome, bool]:
        key = (doc_hash(doc), provider.name, provider.model, PROMPT_VERSION)
        if key in self._d:
            return self._d[key], True
        out = extract_contract(doc, provider)
        if out.terms is not None:  # don't cache failures, so a retry can succeed
            self._d[key] = out
        return out, False


@dataclass
class CaseRun:
    result: AuditResult
    narrative: NarrativeOut | None
    extractions: list[ExtractionOutcome]
    injection_hits: dict[str, list[str]]
    usage: list[dict[str, Any]] = field(default_factory=list)


def run_audit(booking: Booking, docs: list[ContractDocument], provider: LLMProvider, *,
              cache: ExtractionCache | None = None, narrative_provider: LLMProvider | None = None,
              with_narrative: bool = True) -> CaseRun:
    cache = cache or ExtractionCache()
    hits: dict[str, list[str]] = {}
    for d in docs:
        if h := injection.scan(d.text):
            hits[d.document_id] = h
    if h := injection.scan(booking.notes):
        hits[f"booking {booking.booking_id} notes"] = h

    outcomes, usage, failed, terms = [], [], [], []
    for d in docs:
        out, cached = cache.get_or_extract(d, provider)
        outcomes.append(out)
        if not cached:
            usage += [dict(u, stage="extraction", document_id=d.document_id) for u in out.usage]
        if out.terms is None or out.terms.schema_errors:
            failed.append(d.document_id)
        if out.terms is not None:
            terms.append(out.terms)

    result = engine.audit(booking, terms, injection_hits=hits, failed_documents=failed)
    narrative = None
    if with_narrative:
        narrative = generate(result, booking, narrative_provider)
        if narrative.usage:
            usage.append(dict(narrative.usage, stage="narrative"))
    return CaseRun(result=result, narrative=narrative, extractions=outcomes, injection_hits=hits, usage=usage)
