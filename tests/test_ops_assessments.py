import secrets
from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-assess", "email": "assess@example.com", "role": "revenue_staff"}


def test_assessment_total_is_server_calculated_and_audited():
    import auth
    from main import app
    from ops_audit import list_audit_events
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    taxpayer_id = "tp-" + secrets.token_hex(4)
    r = client.post("/ops/assessments", json={
        "taxpayer_id": taxpayer_id,
        "principal": 1000,
        "penalty": 100,
        "interest": 50,
        "adjustments": [{"line_type":"adjustment","amount":-25,"reason":"verified credit"}]
    })
    assert r.status_code == 201
    body = r.json()
    assert body["total"] == 1125
    events = list_audit_events(entity_type="assessment", entity_id=body["id"])
    assert events and events[0]["action"] == "assessment.create"
    app.dependency_overrides.clear()


def test_adjustment_reason_required():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    r = client.post("/ops/assessments", json={
        "taxpayer_id":"tp-adjust",
        "principal":100,
        "adjustments":[{"line_type":"adjustment","amount":-10}]
    })
    app.dependency_overrides.clear()
    assert r.status_code == 422


def test_assessment_state_validation():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    created = client.post("/ops/assessments", json={"taxpayer_id":"tp-state","principal":100}).json()
    assert client.patch(f"/ops/assessments/{created['id']}", json={"status":"nonsense"}).status_code == 422
    assert client.patch(f"/ops/assessments/{created['id']}", json={"status":"issued"}).status_code == 200
    app.dependency_overrides.clear()
