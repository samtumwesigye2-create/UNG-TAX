import secrets
from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-returns", "email": "returns@example.com", "role": "revenue_staff"}


def _seed_return(state="submitted"):
    from ops_store import get_ops_db
    rid = "ret-" + secrets.token_hex(4)
    now = 1_700_000_000.0
    with get_ops_db() as db:
        db.execute("INSERT INTO return_reviews(id,taxpayer_id,filing_id,return_type,period,state,reviewer_id,reviewer_notes,reason,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (rid,"tp-return","filing-1","income_tax","2026",state,None,None,None,"{}",now,now))
    return rid


def test_staff_can_review_submitted_return():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    rid = _seed_return("submitted")
    r = client.patch(f"/ops/returns/{rid}/review", json={"state":"under_review","reviewer_notes":"checking documents"})
    assert r.status_code == 200 and r.json()["state"] == "under_review"
    r = client.patch(f"/ops/returns/{rid}/review", json={"state":"accepted","reviewer_notes":"verified"})
    assert r.status_code == 200 and r.json()["state"] == "accepted"
    app.dependency_overrides.clear()


def test_rejection_and_void_require_reason():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    rid = _seed_return("under_review")
    assert client.patch(f"/ops/returns/{rid}/review", json={"state":"rejected"}).status_code == 422
    rid2 = _seed_return("submitted")
    assert client.patch(f"/ops/returns/{rid2}/review", json={"state":"voided"}).status_code == 422
    app.dependency_overrides.clear()


def test_invalid_transition_returns_409_and_valid_transition_is_audited():
    import auth
    from main import app
    from ops_audit import list_audit_events
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    rid = _seed_return("accepted")
    assert client.patch(f"/ops/returns/{rid}/review", json={"state":"under_review"}).status_code == 409
    rid2 = _seed_return("submitted")
    assert client.patch(f"/ops/returns/{rid2}/review", json={"state":"under_review"}).status_code == 200
    events = list_audit_events(entity_type="return", entity_id=rid2)
    assert events and events[0]["action"] == "return.review.transition"
    app.dependency_overrides.clear()
