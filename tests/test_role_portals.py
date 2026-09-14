import os
os.environ.setdefault("PROMET_STAFF_EMAILS", "revenue.staff@example.gov")
os.environ.setdefault("PROMET_ADMIN_EMAILS", "revenue.admin@example.gov")

from fastapi.testclient import TestClient
import auth
from main import app

client = TestClient(app)


def test_role_for_email_defaults_to_taxpayer():
    assert auth.role_for_email("citizen@example.com") == "taxpayer"


def test_role_for_email_allows_configured_revenue_staff():
    assert auth.role_for_email("Revenue.Staff@example.gov") == "revenue_staff"


def test_role_for_email_allows_configured_revenue_admin():
    assert auth.role_for_email("Revenue.Admin@example.gov") == "revenue_admin"


def test_taxpayer_portal_uses_ura_promet_brand():
    response = client.get("/taxpayer")
    assert response.status_code == 200
    assert "URA-PROMET" in response.text
    assert "Taxpayer Portal" in response.text


def test_revenue_staff_workspace_exists():
    response = client.get("/revenue-staff")
    assert response.status_code == 200
    assert "Revenue Staff" in response.text
    assert "Return Review" in response.text
    assert "Compliance" in response.text


def test_revenue_admin_workspace_has_admin_functions():
    response = client.get("/revenue")
    assert response.status_code == 200
    assert "URA-PROMET" in response.text
    assert "Revenue Admin" in response.text
    assert "Staff Management" in response.text
    assert "Role & Permission Management" in response.text
    assert "System Settings" in response.text
    assert "Audit Log" in response.text


def test_health_advertises_three_roles_and_ura_promet():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "ura-promet"
    assert body["role_portals"] == ["taxpayer", "revenue_staff", "revenue_admin"]
