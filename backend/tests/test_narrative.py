from decimal import Decimal

from app.pipeline.engine import audit
from app.pipeline.narrative import generate
from app.providers.base import ProviderUnavailable
from app.providers.offline import ScriptedProvider
from tests.conftest import booking


def _over(base_contract):  # type: ignore[no-untyped-def]
    b = booking(invoiced_total=Decimal("510.00"))
    return audit(b, [base_contract]), b


def test_template_always_available_and_grounded(base_contract):
    r, b = _over(base_contract)
    n = generate(r, b, None)
    assert n.source == "template" and "75.00" in (n.narrative.draft_body or "")
    assert "510.00" in n.narrative.draft_body and "435.00" in n.narrative.draft_body


def test_llm_narrative_accepted_when_numbers_are_grounded(base_contract):
    r, b = _over(base_contract)
    p = ScriptedProvider([{"summary": "Invoice is 75.00 EUR above the contracted 435.00.", "next_step": "Send query",
                           "draft_subject": "Rate query BK-1", "draft_body": "Charged 510.00, contracted 435.00."}])
    n = generate(r, b, p)
    assert n.source == "scripted" and n.rejected_reason is None


def test_llm_narrative_with_invented_number_is_rejected(base_contract):
    r, b = _over(base_contract)
    p = ScriptedProvider([{"summary": "Overcharged by 80.00 EUR; a 10% penalty applies.", "next_step": "x",
                           "draft_subject": None, "draft_body": None}])
    n = generate(r, b, p)
    assert n.source == "template" and "unsupported numbers" in (n.rejected_reason or "")


def test_provider_failure_falls_back_to_template(base_contract):
    r, b = _over(base_contract)
    n = generate(r, b, ScriptedProvider([ProviderUnavailable("x", "down")]))
    assert n.source == "template" and "generation failed" in (n.rejected_reason or "")


def test_auto_clear_skips_llm(base_contract):
    b = booking()
    p = ScriptedProvider([])
    assert generate(audit(b, [base_contract]), b, p).source == "template" and p.calls == []
