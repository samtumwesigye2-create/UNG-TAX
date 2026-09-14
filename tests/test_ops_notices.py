from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-notices", "email": "notices@example.com", "role": "revenue_staff"}


def test_issued_notice_content_is_immutable_and_replacement_supported():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    r = client.post("/ops/notices", json={"taxpayer_id":"tp-notice","notice_type":"assessment","subject":"Assessment issued","content":"Original notice"})
    assert r.status_code == 201
    nid = r.json()["id"]
    assert client.patch(f"/ops/notices/{nid}", json={"status":"approved"}).status_code == 200
    issued = client.patch(f"/ops/notices/{nid}", json={"status":"issued"})
    assert issued.status_code == 200
    assert issued.json()["issued_at"] is not None
    assert issued.json()["issued_by"] == "staff-notices"
    assert client.patch(f"/ops/notices/{nid}", json={"content":"Changed after issue"}).status_code == 409
    replacement = client.post("/ops/notices", json={"taxpayer_id":"tp-notice","notice_type":"assessment_correction","subject":"Replacement","content":"Corrected notice","supersedes_notice_id":nid})
    assert replacement.status_code == 201
    assert replacement.json()["supersedes_notice_id"] == nid
    app.dependency_overrides.clear()
