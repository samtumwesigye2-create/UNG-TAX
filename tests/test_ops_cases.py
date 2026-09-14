from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-cases", "email": "cases@example.com", "role": "revenue_staff"}


def test_case_lifecycle_and_timeline_are_audited():
    import auth
    from main import app
    from ops_audit import list_audit_events
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    r = client.post("/ops/cases", json={"taxpayer_id":"tp-case","case_type":"compliance","title":"Late filer","description":"Review filing history","priority":"high","assigned_to":"staff-cases"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.patch(f"/ops/cases/{cid}", json={"status":"suspended","reason":"awaiting documents"}).status_code == 200
    assert client.patch(f"/ops/cases/{cid}", json={"status":"reopened","reason":"documents received"}).status_code == 200
    assert client.post(f"/ops/cases/{cid}/events", json={"event_type":"document_received","note":"Bank statement received","metadata":{"pages":4}}).status_code == 201
    assert client.patch(f"/ops/cases/{cid}", json={"status":"closed","reason":"review complete"}).status_code == 200
    events = list_audit_events(entity_type="case", entity_id=cid)
    assert any(e["action"] == "case.update" for e in events)
    app.dependency_overrides.clear()
