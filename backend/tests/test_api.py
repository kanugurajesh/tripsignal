import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.gold import load_cases, load_documents, load_gold
from app.providers.offline import OracleProvider

OPS = {"X-Actor-Id": "priya", "X-Actor-Role": "operator"}
LEAD = {"X-Actor-Id": "arjun", "X-Actor-Role": "approver"}
LEAD2 = {"X-Actor-Id": "meera", "X-Actor-Role": "approver"}
VIEW = {"X-Actor-Id": "guest", "X-Actor-Role": "viewer"}


@pytest.fixture
def client() -> TestClient:
    s = Settings(_env_file=None, database_url="sqlite://", as_of_date="2026-10-20")  # type: ignore[call-arg]
    c = TestClient(create_app(s, provider=OracleProvider(load_gold())))
    for d in load_documents().values():
        assert c.post("/api/documents", json=d.model_dump(mode="json"), headers=OPS).status_code == 201
    return c


def case(cid: str) -> dict:
    return next(c for c in load_cases() if c["case_id"] == cid)


def audit(client: TestClient, cid: str, headers=OPS):  # type: ignore[no-untyped-def]
    c = case(cid)
    return client.post("/api/audits", json={"booking": c["booking"], "document_ids": c["document_ids"]}, headers=headers)


def first(category: str, route: str) -> str:
    return next(c["case_id"] for c in load_cases() if c["category"] == category and c["expected"]["route"] == route)


def test_health_reports_demo_mode(client):
    h = client.get("/api/health").json()
    assert h["provider"] == "oracle" and h["demo_mode"] is True


def test_full_lifecycle_with_approval_gate(client):
    r = audit(client, first("overcharge", "SUPPLIER_QUERY"))
    assert r.status_code == 201 and r.json()["route"] == "SUPPLIER_QUERY"
    cid = r.json()["case_id"]
    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["status"] == "OPEN" and detail["narrative"]["narrative"]["draft_body"]
    assert detail["result"]["nights"][0]["evidence"]["verified"] is True

    a = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS)
    assert a.status_code == 201
    aid = a.json()["id"]
    assert client.post(f"/api/actions/{aid}/execute", headers=OPS).status_code == 409  # not approved yet
    assert client.post(f"/api/actions/{aid}/approve", json={}, headers=OPS).status_code == 403  # operator can't approve
    assert client.post(f"/api/actions/{aid}/approve", json={"note": "ok"}, headers=LEAD).json()["status"] == "APPROVED"
    ex = client.post(f"/api/actions/{aid}/execute", headers=OPS).json()
    assert ex["status"] == "EXECUTED_SIMULATED" and ex["result"]["simulated"] is True
    assert client.post(f"/api/actions/{aid}/execute", headers=OPS).status_code == 409  # idempotent: no double send

    delta = detail["result"]["delta"]
    too_much = str(float(delta) + 1)
    assert client.post(f"/api/cases/{cid}/outcome", json={"outcome": "CREDIT_CONFIRMED", "amount": too_much},
                       headers=LEAD).status_code == 422
    assert client.post(f"/api/cases/{cid}/outcome", json={"outcome": "CREDIT_CONFIRMED", "amount": delta},
                       headers=OPS).status_code == 403
    o = client.post(f"/api/cases/{cid}/outcome", json={"outcome": "CREDIT_CONFIRMED", "amount": delta}, headers=LEAD)
    assert o.status_code == 200 and o.json()["status"] == "RESOLVED"
    events = [e["event"] for e in client.get(f"/api/cases/{cid}").json()["events"]]
    assert events == ["AUDITED", "ACTION_PROPOSED", "ACTION_APPROVED", "ACTION_EXECUTED_SIMULATED", "OUTCOME_RECORDED"]
    ov = client.get("/api/overview").json()
    assert ov["operator_reported_credits"] and "not verified" in ov["labels"]["operator_reported_credits"]


def test_segregation_of_duties(client):
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    aid = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=LEAD).json()["id"]
    assert client.post(f"/api/actions/{aid}/approve", json={}, headers=LEAD).json()["error"] == "SEGREGATION_OF_DUTIES"
    assert client.post(f"/api/actions/{aid}/approve", json={}, headers=LEAD2).status_code == 200


def test_reject_reopens_case(client):
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    aid = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS).json()["id"]
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS).status_code == 409
    assert client.post(f"/api/actions/{aid}/reject", json={"note": "wrong"}, headers=LEAD).json()["status"] == "REJECTED"
    assert client.get(f"/api/cases/{cid}").json()["status"] == "OPEN"
    assert client.post(f"/api/actions/{aid}/approve", json={}, headers=LEAD).status_code == 409


def test_viewer_cannot_mutate_and_bad_role_rejected(client):
    assert audit(client, "C001", headers=VIEW).status_code == 403
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=VIEW).status_code == 403
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"},
                       headers={"X-Actor-Role": "admin"}).status_code == 400


def test_duplicate_audit_is_idempotent(client):
    a, b = audit(client, "C002"), audit(client, "C002")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["case_id"] == b.json()["case_id"]
    assert len(client.get("/api/cases").json()) == 1


def test_action_must_fit_route_and_state(client):
    auto = audit(client, first("match", "AUTO_CLEAR")).json()["case_id"]
    r = client.post(f"/api/cases/{auto}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS)
    assert r.status_code == 422 and r.json()["error"] == "ACTION_NOT_ALLOWED"
    info = audit(client, first("missing_field", "REQUEST_INFO")).json()["case_id"]
    assert client.post(f"/api/cases/{info}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS).status_code == 422
    assert client.post(f"/api/cases/{info}/actions", json={"type": "DELETE_BOOKING"}, headers=OPS).status_code == 422
    assert client.post(f"/api/cases/{info}/actions", json={"type": "REQUEST_INFORMATION"}, headers=OPS).status_code == 201


def test_payload_validated_server_side(client):
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    r = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY",
                                                     "payload": {"subject": "x", "body": "y" * 6000}}, headers=OPS)
    assert r.status_code == 422


def test_injection_cases_are_never_auto_cleared(client):
    for c in load_cases():
        if c["category"] == "injection" and "SUSPECTED_INJECTION" in c["expected"]["codes"]:
            r = audit(client, c["case_id"]).json()
            assert r["route"] == "ESCALATE", c["case_id"]


def test_dismiss_requires_note_and_filters_work(client):
    cid = audit(client, first("undercharge", "ESCALATE")).json()["case_id"]
    assert client.post(f"/api/cases/{cid}/outcome", json={"outcome": "DISMISSED_FALSE_POSITIVE"}, headers=OPS).status_code == 422
    assert client.post(f"/api/cases/{cid}/outcome", json={"outcome": "DISMISSED_FALSE_POSITIVE",
                                                       "note": "Hotel promo rate agreed by email"}, headers=OPS).status_code == 200
    audit(client, "C001")
    assert all(c["route"] == "ESCALATE" for c in client.get("/api/cases?route=ESCALATE").json())
    assert len(client.get("/api/cases?q=" + case("C001")["booking"]["booking_id"]).json()) == 1


def test_unknown_document_ids_404(client):
    c = case("C001")
    r = client.post("/api/audits", json={"booking": c["booking"], "document_ids": ["NOPE"]}, headers=OPS)
    assert r.status_code == 404


def test_document_content_change_requires_new_id(client):
    d = next(iter(load_documents().values())).model_dump(mode="json")
    d["text"] += "\nchanged"
    assert client.post("/api/documents", json=d, headers=OPS).status_code == 409


def test_outcome_blocked_while_action_pending_and_stale_action_cannot_run(client):
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    aid = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS).json()["id"]
    dismiss = {"outcome": "DISMISSED_FALSE_POSITIVE", "note": "not a real overcharge"}
    assert client.post(f"/api/cases/{cid}/outcome", json=dismiss, headers=OPS).status_code == 409
    assert client.post(f"/api/actions/{aid}/reject", json={"note": "no"}, headers=LEAD).status_code == 200
    assert client.post(f"/api/cases/{cid}/outcome", json=dismiss, headers=OPS).json()["status"] == "DISMISSED"
    assert client.post(f"/api/actions/{aid}/approve", json={}, headers=LEAD2).status_code == 409
    assert client.get(f"/api/cases/{cid}").json()["status"] == "DISMISSED"


def test_non_finite_credit_amount_rejected(client):
    cid = audit(client, first("overcharge", "SUPPLIER_QUERY")).json()["case_id"]
    aid = client.post(f"/api/cases/{cid}/actions", json={"type": "SEND_SUPPLIER_QUERY"}, headers=OPS).json()["id"]
    client.post(f"/api/actions/{aid}/approve", json={}, headers=LEAD)
    client.post(f"/api/actions/{aid}/execute", headers=OPS)
    for amt in ("NaN", "Infinity", "sNaN"):
        r = client.post(f"/api/cases/{cid}/outcome", json={"outcome": "CREDIT_CONFIRMED", "amount": amt}, headers=LEAD)
        assert r.status_code == 422


def test_documents_from_another_hotel_rejected(client):
    cs = load_cases()
    a = cs[0]
    b = next(c for c in cs if c["booking"]["hotel_id"] != a["booking"]["hotel_id"])
    r = client.post("/api/audits", json={"booking": a["booking"], "document_ids": b["document_ids"]}, headers=OPS)
    assert r.status_code == 422 and r.json()["error"] == "DOCUMENT_HOTEL_MISMATCH"
