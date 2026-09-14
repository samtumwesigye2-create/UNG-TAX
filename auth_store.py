"""Shared persistent authentication storage for URA-PROMET."""
from contextlib import contextmanager
import os
import sqlite3

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("PROMET_AUTH_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tax_filing.db"))


def backend_name() -> str:
    return "postgresql" if DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"


class Connection:
    def __init__(self, raw, postgres=False):
        self.raw = raw
        self.postgres = postgres
    def _sql(self, sql):
        return sql.replace("?", "%s") if self.postgres else sql
    def execute(self, sql, params=()):
        return self.raw.execute(self._sql(sql), params)
    def close(self):
        self.raw.close()
    def commit(self):
        self.raw.commit()
    def rollback(self):
        self.raw.rollback()


def db():
    if backend_name() == "postgresql":
        import psycopg
        from psycopg.rows import dict_row
        return Connection(psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row), True)
    raw = sqlite3.connect(SQLITE_PATH, timeout=30, isolation_level=None)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA busy_timeout=30000")
    return Connection(raw)


@contextmanager
def transaction(c):
    if c.postgres:
        with c.raw.transaction():
            yield c
    else:
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def init_schema() -> None:
    c = db()
    stmts = [
        """CREATE TABLE IF NOT EXISTS auth_users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,password_salt TEXT NOT NULL,mfa_secret TEXT NOT NULL,mfa_enabled INTEGER NOT NULL DEFAULT 0,created_at DOUBLE PRECISION NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS auth_sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES auth_users(id),mfa_verified INTEGER NOT NULL DEFAULT 0,created_at DOUBLE PRECISION NOT NULL,expires_at DOUBLE PRECISION NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS auth_email_otp(session_token TEXT PRIMARY KEY,user_id TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at DOUBLE PRECISION NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,created_at DOUBLE PRECISION NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS auth_password_resets(reset_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at DOUBLE PRECISION NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,created_at DOUBLE PRECISION NOT NULL)""",
    ]
    for stmt in stmts:
        c.execute(stmt)
    c.close()


init_schema()
