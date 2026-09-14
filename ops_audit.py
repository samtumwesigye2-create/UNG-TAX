"""Append-only audit support for URA-PROMET operations."""
from __future__ import annotations

import json
import secrets
import time

from ops_store import get_ops_db


def write_audit_event(*, actor_id: str, actor_role: str, action: str,
                      entity_type: str, entity_id: str, taxpayer_id: str | None,
                      before: dict | list | None, after: dict | list | None,
                      reason: str | None = None, correlation_id: str | None = None) -> str:
    event_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO audit_log(id,actor_id,actor_role,action,entity_type,entity_id,taxpayer_id,before_json,after_json,reason,correlation_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, actor_id, actor_role, action, entity_type, entity_id,
                taxpayer_id, json.dumps(before or {}, sort_keys=True),
                json.dumps(after or {}, sort_keys=True), reason, correlation_id, now,
            ),
        )
    return event_id


def list_audit_events(*, entity_type: str | None = None, entity_id: str | None = None,
                      taxpayer_id: str | None = None, limit: int = 200) -> list[dict]:
    clauses = []
    params = []
    if entity_type:
        clauses.append("entity_type=?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id=?")
        params.append(entity_id)
    if taxpayer_id:
        clauses.append("taxpayer_id=?")
        params.append(taxpayer_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(limit, 1000)))
    with get_ops_db() as db:
        rows = db.fetchall(
            f"SELECT * FROM audit_log{where} ORDER BY created_at DESC LIMIT ?", params
        )
    for row in rows:
        row["before"] = json.loads(row.pop("before_json") or "{}")
        row["after"] = json.loads(row.pop("after_json") or "{}")
    return rows
