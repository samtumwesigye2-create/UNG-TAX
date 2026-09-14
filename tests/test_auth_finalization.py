from pathlib import Path
import main


def test_health_reports_auth_storage_backend():
    payload = main.health()
    assert payload["auth_storage"] in {"sqlite", "postgresql"}


def test_revenue_operations_exposes_password_recovery():
    html = Path("static/ops-workspace.html").read_text(encoding="utf-8")
    js = Path("static/ops-workspace.js").read_text(encoding="utf-8")
    assert "forgotPasswordBtn" in html
    assert "resetPanel" in html
    assert "/auth/password/request" in js
    assert "/auth/password/confirm" in js


def test_migration_helper_is_available():
    import auth_migrate
    assert callable(auth_migrate.migrate_sqlite_auth_to_postgres)
