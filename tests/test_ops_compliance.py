from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-compliance", "email": "compliance@example.com", "role": "revenue_staff"}


def _taxpayer():
    return {"id": "tp-user", "email": "tp@example.com", "role": "taxpayer"}


def test_staff_can_update_compliance_and_audit():
    import auth
    from main import app
    from ops_audit import list_audit_events
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    taxpayer_id = "tp-compliance"
    r = client.patch(f"/ops/compliance/{taxpayer_id}", json={
        "filing_compliance":"late",
        "payment_compliance":"current",
        "risk_flags":["late_filing"],
        "notes":"Follow up next week",
        "next_action_date":"2026-09-20"
    })
    assert r.status_code == 200
    assert r.json()["risk_flags"] == ["late_filing"]
    events = list_audit_events(entity_type="compliance", entity_id=taxpayer_id)
    assert events and events[0]["action"] == "compliance.update"
    app.dependency_overrides.clear()


def test_taxpayer_cannot_view_compliance():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _taxpayer
    client = TestClient(app)
    r = client.get("/ops/compliance/tp-compliance")
    app.dependency_overrides.clear()
    assert r.status_code == 403
