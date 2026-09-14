import secrets
from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-1", "email": "staff@example.com", "role": "revenue_staff"}


def _taxpayer():
    return {"id": "tax-actor", "email": "taxpayer@example.com", "role": "taxpayer"}


def _seed_taxpayer():
    from ops_store import get_ops_db
    now = 1_700_000_000.0
    taxpayer_id = "tp-" + secrets.token_hex(4)
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO taxpayer_profiles(id,account_id,tin,name,email,phone,address,status,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (taxpayer_id, "ACC-" + taxpayer_id, "TIN-" + taxpayer_id, "Amina Test", "amina@example.com", "+256700000000", "Kampala", "active", "{}", now, now),
        )
    return taxpayer_id


def test_taxpayer_role_cannot_search(monkeypatch):
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _taxpayer
    client = TestClient(app)
    r = client.get("/ops/taxpayers")
    app.dependency_overrides.clear()
    assert r.status_code == 403


def test_staff_can_search_update_and_audit(monkeypatch):
    import auth
    from main import app
    from ops_audit import list_audit_events
    taxpayer_id = _seed_taxpayer()
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)

    r = client.get("/ops/taxpayers", params={"q": "Amina"})
    assert r.status_code == 200
    assert any(x["id"] == taxpayer_id for x in r.json()["items"])

    r = client.patch(f"/ops/taxpayers/{taxpayer_id}", json={"phone": "+256711111111", "status": "suspended", "reason": "identity review"})
    assert r.status_code == 200
    assert r.json()["phone"] == "+256711111111"
    assert r.json()["status"] == "suspended"

    events = list_audit_events(entity_type="taxpayer", entity_id=taxpayer_id)
    assert events and events[0]["action"] == "taxpayer.update"
    assert events[0]["before"]["status"] == "active"
    assert events[0]["after"]["status"] == "suspended"
    app.dependency_overrides.clear()


def test_unknown_taxpayer_is_404():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    r = client.get("/ops/taxpayers/does-not-exist")
    app.dependency_overrides.clear()
    assert r.status_code == 404
