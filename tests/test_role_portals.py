import os
os.environ.setdefault("PROMET_STAFF_EMAILS", "revenue.staff@example.gov")

from fastapi.testclient import TestClient
import auth
from main import app

client = TestClient(app)


def test_role_for_email_defaults_to_taxpayer():
    assert auth.role_for_email("citizen@example.com") == "taxpayer"


def test_role_for_email_allows_configured_revenue_staff():
    assert auth.role_for_email("Revenue.Staff@example.gov") == "revenue_staff"


def test_taxpayer_portal_route_exists():
    response = client.get("/taxpayer")
    assert response.status_code == 200
    assert "Taxpayer Portal" in response.text
    assert "Returns" in response.text
    assert "PAYE" in response.text
    assert "NSSF" in response.text


def test_revenue_portal_route_exists():
    response = client.get("/revenue")
    assert response.status_code == 200
    assert "Revenue Operations" in response.text
    assert "Taxpayer Search" in response.text
    assert "Assessments" in response.text
    assert "Compliance" in response.text


def test_health_advertises_role_portals():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["role_portals"] == ["taxpayer", "revenue_staff"]
