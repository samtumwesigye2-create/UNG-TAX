from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_taxpayer_portal_uses_ura_promet_brand():
    r=client.get("/taxpayer"); assert r.status_code==200; assert "URA-PROMET" in r.text; assert "Taxpayer Portal" in r.text

def test_revenue_staff_workspace_exists():
    r=client.get("/revenue-staff"); assert r.status_code==200; assert "Revenue Staff" in r.text; assert "Return Review" in r.text; assert "Compliance" in r.text

def test_revenue_admin_workspace_has_admin_functions():
    r=client.get("/revenue"); assert r.status_code==200; assert "URA-PROMET" in r.text; assert "Revenue Admin" in r.text; assert "Staff Management" in r.text; assert "Role &amp; Permission Management" in r.text; assert "System Settings" in r.text; assert "Audit Log" in r.text

def test_health_reports_direct_access():
    r=client.get("/health"); assert r.status_code==200; b=r.json(); assert b["service"]=="URA-PROMET"; assert b["access"]=="direct"

def test_auth_routes_are_absent():
    assert client.post("/auth/login", json={}).status_code == 404
