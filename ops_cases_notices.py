"""Notices and case/audit workflows for URA-PROMET Block 1."""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException

import auth
from ops_audit import write_audit_event
from ops_auth import require_revenue_user
from ops_models import CaseCreate, CaseEventIn, CasePatch, NoticeCreate, NoticePatch, NOTICE_STATES
from ops_store import get_ops_db

router = APIRouter(prefix="/ops", tags=["revenue-operations"])

NOTICE_TRANSITIONS = {
    "draft": {"approved", "cancelled", "archived"},
    "approved": {"issued", "cancelled", "archived"},
    "issued": {"cancelled", "archived"},
    "cancelled": {"archived"},
    "archived": set(),
}
CASE_TRANSITIONS = {
    "open": {"suspended", "closed", "voided", "archived"},
    "suspended": {"reopened", "closed", "voided", "archived"},
    "reopened": {"suspended", "closed", "voided", "archived"},
    "closed": {"reopened", "archived"},
    "voided": {"archived"},
    "archived": set(),
}


def _revenue_user(user=Depends(auth.require_auth)):
    return require_revenue_user(user)


def _case(row: dict) -> dict:
    return dict(row)


def _notice(row: dict) -> dict:
    return dict(row)


@router.post("/notices", status_code=201)
def create_notice(body: NoticeCreate, user=Depends(_revenue_user)):
    notice_id = secrets.token_hex(16)
    now = time.time()
    if body.supersedes_notice_id:
        with get_ops_db() as db:
            if not db.fetchone("SELECT id FROM notices WHERE id=?", (body.supersedes_notice_id,)):
                raise HTTPException(404, "Superseded notice not found")
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO notices(id,taxpayer_id,notice_type,subject,content,status,related_entity_type,related_entity_id,supersedes_notice_id,issued_at,issued_by,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (notice_id, body.taxpayer_id, body.notice_type, body.subject, body.content, "draft", body.related_entity_type, body.related_entity_id, body.supersedes_notice_id, None, None, user["id"], now, now),
        )
        row = db.fetchone("SELECT * FROM notices WHERE id=?", (notice_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="notice.create",
                      entity_type="notice", entity_id=notice_id, taxpayer_id=body.taxpayer_id,
                      before={}, after=row, correlation_id=secrets.token_hex(8))
    return _notice(row)


@router.get("/notices")
def list_notices(taxpayer_id: str | None = None, status: str | None = None, user=Depends(_revenue_user)):
    clauses, params = [], []
    if taxpayer_id:
        clauses.append("taxpayer_id=?"); params.append(taxpayer_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM notices{where} ORDER BY updated_at DESC LIMIT 250", params)
    return {"items": [_notice(row) for row in rows]}


@router.patch("/notices/{notice_id}")
def patch_notice(notice_id: str, body: NoticePatch, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM notices WHERE id=?", (notice_id,))
        if not before:
            raise HTTPException(404, "Notice not found")
        updates = body.model_dump(exclude_unset=True)
        reason = updates.pop("reason", None)
        if before["status"] == "issued" and any(k in updates for k in {"subject", "content"}):
            raise HTTPException(409, "Issued notice content is immutable")
        target_status = updates.get("status", before["status"])
        if target_status not in NOTICE_STATES:
            raise HTTPException(422, "Invalid notice status")
        if target_status != before["status"] and target_status not in NOTICE_TRANSITIONS.get(before["status"], set()):
            raise HTTPException(409, f"Invalid notice transition: {before['status']} -> {target_status}")
        subject = updates.get("subject", before["subject"])
        content = updates.get("content", before["content"])
        issued_at = before["issued_at"]
        issued_by = before["issued_by"]
        if target_status == "issued" and before["status"] != "issued":
            issued_at = time.time()
            issued_by = user["id"]
        db.execute(
            "UPDATE notices SET subject=?,content=?,status=?,issued_at=?,issued_by=?,updated_at=? WHERE id=?",
            (subject, content, target_status, issued_at, issued_by, time.time(), notice_id),
        )
        after = db.fetchone("SELECT * FROM notices WHERE id=?", (notice_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="notice.update",
                      entity_type="notice", entity_id=notice_id, taxpayer_id=before["taxpayer_id"],
                      before=before, after=after, reason=reason, correlation_id=secrets.token_hex(8))
    return _notice(after)


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate, user=Depends(_revenue_user)):
    case_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO cases(id,taxpayer_id,case_type,title,description,priority,status,assigned_to,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (case_id, body.taxpayer_id, body.case_type, body.title, body.description, body.priority, "open", body.assigned_to, user["id"], now, now),
        )
        row = db.fetchone("SELECT * FROM cases WHERE id=?", (case_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="case.create",
                      entity_type="case", entity_id=case_id, taxpayer_id=body.taxpayer_id,
                      before={}, after=row, correlation_id=secrets.token_hex(8))
    return _case(row)


@router.get("/cases")
def list_cases(taxpayer_id: str | None = None, status: str | None = None, user=Depends(_revenue_user)):
    clauses, params = [], []
    if taxpayer_id:
        clauses.append("taxpayer_id=?"); params.append(taxpayer_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM cases{where} ORDER BY updated_at DESC LIMIT 250", params)
    return {"items": [_case(row) for row in rows]}


@router.patch("/cases/{case_id}")
def patch_case(case_id: str, body: CasePatch, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM cases WHERE id=?", (case_id,))
        if not before:
            raise HTTPException(404, "Case not found")
        updates = body.model_dump(exclude_unset=True)
        reason = updates.pop("reason", None)
        target_status = updates.get("status", before["status"])
        if target_status != before["status"]:
            if target_status not in CASE_TRANSITIONS.get(before["status"], set()):
                raise HTTPException(409, f"Invalid case transition: {before['status']} -> {target_status}")
            if not (reason or "").strip():
                raise HTTPException(422, "Reason is required for case status changes")
        values = {
            "title": updates.get("title", before["title"]),
            "description": updates.get("description", before["description"]),
            "priority": updates.get("priority", before["priority"]),
            "assigned_to": updates.get("assigned_to", before["assigned_to"]),
            "status": target_status,
        }
        db.execute(
            "UPDATE cases SET title=?,description=?,priority=?,assigned_to=?,status=?,updated_at=? WHERE id=?",
            (values["title"], values["description"], values["priority"], values["assigned_to"], values["status"], time.time(), case_id),
        )
        after = db.fetchone("SELECT * FROM cases WHERE id=?", (case_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="case.update",
                      entity_type="case", entity_id=case_id, taxpayer_id=before["taxpayer_id"],
                      before=before, after=after, reason=reason, correlation_id=secrets.token_hex(8))
    return _case(after)


@router.post("/cases/{case_id}/events", status_code=201)
def add_case_event(case_id: str, body: CaseEventIn, user=Depends(_revenue_user)):
    event_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        case = db.fetchone("SELECT * FROM cases WHERE id=?", (case_id,))
        if not case:
            raise HTTPException(404, "Case not found")
        db.execute(
            "INSERT INTO case_events(id,case_id,event_type,note,metadata_json,actor_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (event_id, case_id, body.event_type, body.note, json.dumps(body.metadata or {}, sort_keys=True), user["id"], now),
        )
        row = db.fetchone("SELECT * FROM case_events WHERE id=?", (event_id,))
    out = dict(row)
    out["metadata"] = json.loads(out.pop("metadata_json") or "{}")
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="case.event.add",
                      entity_type="case", entity_id=case_id, taxpayer_id=case["taxpayer_id"],
                      before={}, after=out, reason=body.note, correlation_id=secrets.token_hex(8))
    return out
