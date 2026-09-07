"""Production database compatibility layer for URA-PROMET.

The application historically used sqlite3 directly.  Railway production now
provides DATABASE_URL for PostgreSQL.  Python imports sitecustomize at startup,
so this shim transparently routes the app's tax_filing.db connections to
PostgreSQL while preserving the small sqlite-style API used by the existing
modules.  Local development/tests continue using real SQLite when DATABASE_URL
is absent.
"""
from __future__ import annotations

import os
import re
import sqlite3 as _sqlite3
from collections.abc import Mapping

_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_ORIGINAL_CONNECT = _sqlite3.connect


class _Row(Mapping):
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._map = dict(zip(self._columns, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._columns)

    def keys(self):
        return self._map.keys()


class _NoopCursor:
    rowcount = 0
    description = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def _columns(self):
        if not self._cur.description:
            return []
        return [d.name if hasattr(d, "name") else d[0] for d in self._cur.description]

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return _Row(self._columns(), row)

    def fetchall(self):
        cols = self._columns()
        return [_Row(cols, row) for row in self._cur.fetchall()]

    def __iter__(self):
        cols = self._columns()
        for row in self._cur:
            yield _Row(cols, row)

    def __getattr__(self, name):
        return getattr(self._cur, name)


_QMARK = re.compile(r"\?")


def _translate(sql: str) -> str | None:
    stripped = sql.strip()
    upper = stripped.upper()
    if upper.startswith("PRAGMA "):
        return None
    if upper == "BEGIN IMMEDIATE":
        return "BEGIN"
    # Existing PROMET SQL uses DB-API qmark placeholders, not literal '?'.
    return _QMARK.sub("%s", sql)


class _PgConnection:
    def __init__(self, url: str):
        import psycopg
        self._conn = psycopg.connect(url, autocommit=True)
        self.row_factory = _sqlite3.Row  # accepted for sqlite compatibility; rows are adapted below.

    def execute(self, sql, params=()):
        translated = _translate(sql)
        if translated is None:
            return _NoopCursor()
        cur = self._conn.cursor()
        try:
            cur.execute(translated, params or ())
            return _Cursor(cur)
        except Exception as exc:
            # Keep existing application exception handling intact.
            try:
                import psycopg
                if isinstance(exc, psycopg.IntegrityError):
                    raise _sqlite3.IntegrityError(str(exc)) from exc
            except _sqlite3.IntegrityError:
                raise
            except Exception:
                pass
            raise

    def close(self):
        self._conn.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _is_promet_db(database) -> bool:
    try:
        return os.path.basename(os.fspath(database)) == "tax_filing.db"
    except TypeError:
        return False


def _connect(database, *args, **kwargs):
    if _DATABASE_URL and _is_promet_db(database):
        return _PgConnection(_DATABASE_URL)
    return _ORIGINAL_CONNECT(database, *args, **kwargs)


if _DATABASE_URL:
    _sqlite3.connect = _connect
