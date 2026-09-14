import secrets
from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-payments", "email": "payments@example.com", "role": "revenue_staff"}


def _seed_liability(amount=500):
    from ops_store import get_ops_db
    lid = "liab-" + secrets.token_hex(4)
    now = 1_700_000_000.0
    with get_ops_db() as db:
        db.execute("INSERT INTO liabilities(id,taxpayer_id,assessment_id,description,original_amount,status,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (lid,"tp-pay",None,"Test liability",amount,"open","2026-10-01",now,now))
    return lid


def test_allocation_cannot_exceed_open_balance_and_reversal_is_append_only():
    import auth
    from main import app
    from ops_store import get_ops_db
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    lid = _seed_liability(500)
    assert client.post("/ops/payments/allocations", json={"taxpayer_id":"tp-pay","liability_id":lid,"amount":600}).status_code == 409
    r = client.post("/ops/payments/allocations", json={"taxpayer_id":"tp-pay","liability_id":lid,"amount":200,"payment_reference":"RCPT-1"})
    assert r.status_code == 201
    allocation_id = r.json()["id"]
    assert client.post(f"/ops/payments/{allocation_id}/reverse", json={"reason":"wrong liability"}).status_code == 201
    with get_ops_db() as db:
        rows = db.fetchall("SELECT * FROM payment_allocations WHERE liability_id=? ORDER BY created_at", (lid,))
    assert len(rows) == 2
    assert rows[0]["amount"] == 200
    assert rows[1]["amount"] == -200
    assert rows[1]["reversal_of"] == allocation_id
    app.dependency_overrides.clear()


def test_reversal_requires_reason_and_installment_total_is_preserved():
    import auth
    from main import app
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    lid = _seed_liability(1000)
    r = client.post("/ops/payments/allocations", json={"taxpayer_id":"tp-pay","liability_id":lid,"amount":100})
    allocation_id = r.json()["id"]
    assert client.post(f"/ops/payments/{allocation_id}/reverse", json={"reason":""}).status_code == 422
    r = client.post("/ops/installments", json={"taxpayer_id":"tp-pay","liability_id":lid,"total_amount":900,"installment_count":3,"frequency":"monthly","start_date":"2026-10-01"})
    assert r.status_code == 201
    body = r.json()
    assert body["total_amount"] == 900
    assert body["installment_count"] == 3
    app.dependency_overrides.clear()
