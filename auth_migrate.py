"""Optional one-way import of surviving legacy SQLite auth users into PostgreSQL."""
import os, sqlite3
import auth_store


def migrate_sqlite_auth_to_postgres(sqlite_path=None):
    if auth_store.backend_name() != "postgresql":
        return {"status":"skipped","reason":"postgresql_not_active","users_imported":0}
    path=sqlite_path or os.getenv("PROMET_LEGACY_AUTH_DB",os.path.join(os.path.dirname(__file__),"tax_filing.db"))
    if not os.path.exists(path):
        return {"status":"skipped","reason":"legacy_database_missing","users_imported":0}
    src=sqlite3.connect(path); src.row_factory=sqlite3.Row
    try:
        rows=src.execute("SELECT id,email,password_hash,password_salt,mfa_secret,mfa_enabled,created_at FROM auth_users").fetchall()
    except sqlite3.OperationalError:
        src.close(); return {"status":"skipped","reason":"legacy_auth_table_missing","users_imported":0}
    dst=auth_store.db(); imported=0
    for r in rows:
        exists=dst.execute("SELECT id FROM auth_users WHERE email=?",(r["email"],)).fetchone()
        if exists: continue
        dst.execute("INSERT INTO auth_users(id,email,password_hash,password_salt,mfa_secret,mfa_enabled,created_at) VALUES(?,?,?,?,?,?,?)",tuple(r))
        imported+=1
    dst.close(); src.close()
    return {"status":"ok","users_imported":imported}
