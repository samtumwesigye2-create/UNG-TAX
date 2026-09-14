import time
from fastapi.testclient import TestClient


def _staff():
    return {"id": "staff-reports", "email": "reports@example.com", "role": "revenue_staff"}


def test_summary_reports_counts_and_totals_with_filters():
    import auth
    from main import app
    from ops_store import get_ops_db
    now = time.time()
    suffix = str(int(now * 1000))
    with get_ops_db() as db:
        db.execute("INSERT INTO return_reviews(id,taxpayer_id,filing_id,return_type,period,state,reviewer_id,reviewer_notes,reason,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("ret-r-"+suffix,"tp-report",None,"income_tax","2026","submitted",None,None,None,"{}",now,now))
        db.execute("INSERT INTO assessments(id,taxpayer_id,return_id,status,principal,penalty,interest,total,reason,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("ass-r-"+suffix,"tp-report",None,"issued",1000,100,50,1150,None,"staff-reports",now,now))
        db.execute("INSERT INTO liabilities(id,taxpayer_id,assessment_id,description,original_amount,status,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   ("lia-r-"+suffix,"tp-report",None,"Report liability",1150,"open","2026-10-01",now,now))
        db.execute("INSERT INTO payment_allocations(id,taxpayer_id,liability_id,amount,payment_reference,reversal_of,reason,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   ("pay-r-"+suffix,"tp-report","lia-r-"+suffix,300,"RPT",None,None,"staff-reports",now))
        db.execute("INSERT INTO cases(id,taxpayer_id,case_type,title,description,priority,status,assigned_to,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   ("case-r-"+suffix,"tp-report","compliance","Report case",None,"normal","open",None,"staff-reports",now,now))
    app.dependency_overrides[auth.require_auth] = _staff
    client = TestClient(app)
    r = client.get("/ops/reports/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["returns"]["count"] >= 1
    assert body["assessments"]["total"] >= 1150
    assert body["payments"]["total"] >= 300
    assert body["cases"]["count"] >= 1
    filtered = client.get("/ops/reports/summary", params={"status":"issued"})
    assert filtered.status_code == 200
    assert filtered.json()["assessments"]["count"] >= 1
    app.dependency_overrides.clear()
