from fastapi.testclient import TestClient


def test_operations_workspace_route_exists():
    from main import app
    client = TestClient(app)
    r = client.get("/operations")
    assert r.status_code == 200
    assert "Revenue Operations" in r.text
    assert "/static/ops-workspace.js" in r.text


def test_staff_dashboard_cards_link_to_real_workspaces():
    from main import app
    client = TestClient(app)
    r = client.get("/revenue-staff")
    assert r.status_code == 200
    for module in ["taxpayers","returns","assessments","compliance","payments","notices","cases","reports"]:
        assert f"/operations?module={module}" in r.text


def test_admin_dashboard_core_cards_link_to_same_operational_workspaces():
    from main import app
    client = TestClient(app)
    r = client.get("/revenue")
    assert r.status_code == 200
    for module in ["taxpayers","returns","assessments","compliance","payments","notices","cases","reports"]:
        assert f"/operations?module={module}" in r.text
