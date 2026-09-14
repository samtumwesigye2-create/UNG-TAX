"""Persistence helpers for URA-PROMET operational workflows.

Uses PostgreSQL when DATABASE_URL is configured, otherwise a SQLite file for
local development and tests. The API layer uses this module rather than
embedding database-specific SQL handling in routes.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - psycopg may be absent in minimal local tooling
    psycopg = None
    dict_row = None

BASE_DIR = Path(__file__).resolve().parent


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def _sqlite_path() -> str:
    return os.getenv("PROMET_OPS_DB", str(BASE_DIR / "ura_promet_ops.db"))


class OpsDB:
    def __init__(self):
        self.postgres = bool(_database_url())
        if self.postgres:
            if psycopg is None:
                raise RuntimeError("DATABASE_URL is set but psycopg is unavailable")
            self.conn = psycopg.connect(_database_url(), row_factory=dict_row)
        else:
            self.conn = sqlite3.connect(_sqlite_path(), timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=30000")

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.postgres else statement

    def execute(self, statement: str, params: Iterable[Any] = ()):
        return self.conn.execute(self._sql(statement), tuple(params))

    def fetchone(self, statement: str, params: Iterable[Any] = ()) -> dict | None:
        cur = self.execute(statement, params)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self, statement: str, params: Iterable[Any] = ()) -> list[dict]:
        cur = self.execute(statement, params)
        return [dict(row) for row in cur.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_ops_db() -> OpsDB:
    return OpsDB()


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS taxpayer_profiles(
        id TEXT PRIMARY KEY, account_id TEXT UNIQUE, tin TEXT UNIQUE,
        name TEXT NOT NULL, email TEXT, phone TEXT, address TEXT,
        status TEXT NOT NULL DEFAULT 'active', metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS taxpayer_notes(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, note TEXT NOT NULL,
        actor_id TEXT NOT NULL, created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS return_reviews(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, filing_id TEXT,
        return_type TEXT, period TEXT, state TEXT NOT NULL DEFAULT 'submitted',
        reviewer_id TEXT, reviewer_notes TEXT, reason TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS assessments(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, return_id TEXT,
        status TEXT NOT NULL DEFAULT 'draft', principal REAL NOT NULL DEFAULT 0,
        penalty REAL NOT NULL DEFAULT 0, interest REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0, reason TEXT, created_by TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS assessment_lines(
        id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL, line_type TEXT NOT NULL,
        amount REAL NOT NULL, reason TEXT, created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS liabilities(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, assessment_id TEXT,
        description TEXT, original_amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        due_date TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS payment_allocations(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, liability_id TEXT NOT NULL,
        amount REAL NOT NULL, payment_reference TEXT, reversal_of TEXT,
        reason TEXT, actor_id TEXT NOT NULL, created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS installment_plans(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, liability_id TEXT,
        total_amount REAL NOT NULL, installment_count INTEGER NOT NULL,
        frequency TEXT NOT NULL, start_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', created_by TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS compliance_records(
        taxpayer_id TEXT PRIMARY KEY, filing_compliance TEXT NOT NULL DEFAULT 'unknown',
        payment_compliance TEXT NOT NULL DEFAULT 'unknown', risk_flags_json TEXT NOT NULL DEFAULT '[]',
        notes TEXT, next_action_date TEXT, updated_by TEXT NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS notices(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, notice_type TEXT NOT NULL,
        subject TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
        related_entity_type TEXT, related_entity_id TEXT, supersedes_notice_id TEXT,
        issued_at REAL, issued_by TEXT, created_by TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS cases(
        id TEXT PRIMARY KEY, taxpayer_id TEXT NOT NULL, case_type TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT, priority TEXT NOT NULL DEFAULT 'normal',
        status TEXT NOT NULL DEFAULT 'open', assigned_to TEXT,
        created_by TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS case_events(
        id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_type TEXT NOT NULL,
        note TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', actor_id TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log(
        id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL,
        action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
        taxpayer_id TEXT, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
        reason TEXT, correlation_id TEXT, created_at REAL NOT NULL
    )""",
]


def init_ops_schema() -> None:
    with get_ops_db() as db:
        for statement in SCHEMA:
            db.execute(statement)


init_ops_schema()
