import importlib


def _prepare_auth(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store
    importlib.reload(auth_store)
    import auth
    return auth, auth_store


def test_registered_user_is_written_to_shared_store(monkeypatch, tmp_path):
    auth, auth_store = _prepare_auth(monkeypatch, tmp_path)
    result = auth.register(auth.RegisterIn(email="persist@example.com", password="StrongPass123"))
    assert result["status"] == "registered"
    c = auth_store.db()
    row = c.execute("SELECT email FROM auth_users WHERE email=?", ("persist@example.com",)).fetchone()
    c.close()
    assert row["email"] == "persist@example.com"


def test_admin_role_comes_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMET_ADMIN_EMAILS", "admin@example.com")
    auth, _ = _prepare_auth(monkeypatch, tmp_path)
    assert auth.role_for_email("ADMIN@example.com") == "revenue_admin"
