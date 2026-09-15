import importlib


def _reload_modules(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store, auth, password_reset
    importlib.reload(auth_store)
    importlib.reload(auth)
    importlib.reload(password_reset)
    return auth_store, auth, password_reset


def test_reset_confirmation_invalidates_all_sessions(monkeypatch, tmp_path):
    auth_store, auth, password_reset = _reload_modules(monkeypatch, tmp_path)
    c = auth_store.db()
    uid = "user-1"
    pw_hash, salt = auth.hash_password("OldStrongPass123")
    c.execute(
        "INSERT INTO auth_users(id,email,password_hash,password_salt,mfa_secret,mfa_enabled,created_at) VALUES(?,?,?,?,?,0,?)",
        (uid, "person@example.com", pw_hash, salt, auth.generate_mfa_secret(), 1.0),
    )
    c.execute(
        "INSERT INTO auth_sessions(token,user_id,mfa_verified,created_at,expires_at) VALUES(?,?,?,?,?)",
        ("session-1", uid, 1, 1.0, 9999999999.0),
    )
    code = "123456"
    import hashlib, time
    c.execute(
        "INSERT INTO auth_password_resets(reset_id,user_id,code_hash,expires_at,attempts,created_at) VALUES(?,?,?,?,0,?)",
        ("reset-1", uid, hashlib.sha256(code.encode()).hexdigest(), time.time() + 900, time.time()),
    )
    c.close()

    password_reset.confirm_reset(password_reset.ResetConfirmIn(reset_id="reset-1", code=code, new_password="NewStrongPass123"))

    c = auth_store.db()
    assert c.execute("SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=?", (uid,)).fetchone()["n"] == 0
    assert c.execute("SELECT COUNT(*) AS n FROM auth_password_resets WHERE user_id=?", (uid,)).fetchone()["n"] == 0
    c.close()


def test_unknown_email_remains_generic(monkeypatch, tmp_path):
    auth_store, auth, password_reset = _reload_modules(monkeypatch, tmp_path)
    monkeypatch.setattr(password_reset, "_resend_ready", lambda: True)
    result = password_reset.request_reset(password_reset.ResetRequestIn(email="missing@example.com"))
    assert result == {"sent": True, "message": "If that account exists, a reset code has been sent."}
