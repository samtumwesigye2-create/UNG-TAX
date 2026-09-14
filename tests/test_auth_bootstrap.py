import importlib


def test_main_runs_legacy_auth_migration_on_startup(monkeypatch):
    import auth_migrate

    calls = []

    def fake_migrate():
        calls.append(True)
        return {"status": "ok", "users_imported": 1}

    monkeypatch.setattr(auth_migrate, "migrate_sqlite_auth_to_postgres", fake_migrate)

    import main
    importlib.reload(main)

    assert calls, "main startup must invoke legacy auth migration"
