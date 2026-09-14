import importlib


def test_sqlite_is_fallback_without_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store
    importlib.reload(auth_store)
    assert auth_store.backend_name() == "sqlite"


def test_auth_schema_contains_all_four_tables(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store
    importlib.reload(auth_store)
    auth_store.init_schema()
    c = auth_store.db()
    names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    assert {"auth_users", "auth_sessions", "auth_email_otp", "auth_password_resets"} <= names
