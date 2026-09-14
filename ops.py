"""URA-PROMET Revenue Operations API."""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query

import auth
from ops_audit import write_audit_event
from ops_auth import require_revenue_user
from ops_models import NoteIn, ReturnReviewPatch, TaxpayerPatch, RETURN_TRANSITIONS
from ops_store import get_ops_db

router = APIRouter(prefix="/ops", tags=["revenue-operations"])


def _revenue_user(user=Depends(auth.require_auth)):
    return require_revenue_user(user)


def _json(value, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _profile(row: dict) -> dict:
    out = dict(row)
    out["metadata"] = _json(out.pop("metadata_json", "{}"), {})
    return out


def _return(row: dict) -> dict:
    out = dict(row)
    out["payload"] = _json(out.pop("payload_json", "{}"), {})
    return out


@router.get("/taxpayers")
def list_taxpayers(q: str | None = Query(default=None), status: str | None = None, user=Depends(_revenue_user)):
    clauses = []
    params = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if q:
        pattern = f"%{q.strip()}%"
        clauses.append("(name LIKE ? OR email LIKE ? OR tin LIKE ? OR account_id LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM taxpayer_profiles{where} ORDER BY updated_at DESC LIMIT 250", params)
    return {"items": [_profile(row) for row in rows]}


@router.get("/taxpayers/{taxpayer_id}")
def get_taxpayer(taxpayer_id: str, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        row = db.fetchone("SELECT * FROM taxpayer_profiles WHERE id=?", (taxpayer_id,))
        if not row:
            raise HTTPException(404, "Taxpayer not found")
        notes = db.fetchall("SELECT * FROM taxpayer_notes WHERE taxpayer_id=? ORDER BY created_at DESC", (taxpayer_id,))
    out = _profile(row)
    out["notes"] = notes
    return out


@router.patch("/taxpayers/{taxpayer_id}")
def patch_taxpayer(taxpayer_id: str, body: TaxpayerPatch, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM taxpayer_profiles WHERE id=?", (taxpayer_id,))
        if not before:
            raise HTTPException(404, "Taxpayer not found")
        updates = body.model_dump(exclude_unset=True)
        reason = updates.pop("reason", None)
        allowed = {"name", "email", "phone", "address", "status", "metadata"}
        updates = {k: v for k, v in updates.items() if k in allowed}
        if not updates:
            return _profile(before)
        assignments = []
        params = []
        for key, value in updates.items():
            column = "metadata_json" if key == "metadata" else key
            if key == "metadata":
                value = json.dumps(value or {}, sort_keys=True)
            assignments.append(f"{column}=?")
            params.append(value)
        assignments.append("updated_at=?")
        params.append(time.time())
        params.append(taxpayer_id)
        db.execute(f"UPDATE taxpayer_profiles SET {', '.join(assignments)} WHERE id=?", params)
        after = db.fetchone("SELECT * FROM taxpayer_profiles WHERE id=?", (taxpayer_id,))
    write_audit_event(
        actor_id=user["id"], actor_role=user["role"], action="taxpayer.update",
        entity_type="taxpayer", entity_id=taxpayer_id, taxpayer_id=taxpayer_id,
        before=_profile(before), after=_profile(after), reason=reason,
        correlation_id=secrets.token_hex(8),
    )
    return _profile(after)


@router.post("/taxpayers/{taxpayer_id}/notes", status_code=201)
def add_taxpayer_note(taxpayer_id: str, body: NoteIn, user=Depends(_revenue_user)):
    note_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        exists = db.fetchone("SELECT id FROM taxpayer_profiles WHERE id=?", (taxpayer_id,))
        if not exists:
            raise HTTPException(404, "Taxpayer not found")
        db.execute("INSERT INTO taxpayer_notes(id,taxpayer_id,note,actor_id,created_at) VALUES(?,?,?,?,?)",
                   (note_id, taxpayer_id, body.note, user["id"], now))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="taxpayer.note.add",
                      entity_type="taxpayer_note", entity_id=note_id, taxpayer_id=taxpayer_id,
                      before={}, after={"note": body.note}, correlation_id=secrets.token_hex(8))
    return {"id": note_id, "taxpayer_id": taxpayer_id, "note": body.note, "actor_id": user["id"], "created_at": now}


@router.get("/returns")
def list_returns(state: str | None = None, taxpayer_id: str | None = None, user=Depends(_revenue_user)):
    clauses, params = [], []
    if state:
        clauses.append("state=?")
        params.append(state)
    if taxpayer_id:
        clauses.append("taxpayer_id=?")
        params.append(taxpayer_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM return_reviews{where} ORDER BY updated_at DESC LIMIT 250", params)
    return {"items": [_return(row) for row in rows]}


@router.get("/returns/{return_id}")
def get_return(return_id: str, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        row = db.fetchone("SELECT * FROM return_reviews WHERE id=?", (return_id,))
    if not row:
        raise HTTPException(404, "Return not found")
    return _return(row)


@router.patch("/returns/{return_id}/review")
def review_return(return_id: str, body: ReturnReviewPatch, user=Depends(_revenue_user)):
    target = body.state
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM return_reviews WHERE id=?", (return_id,))
        if not before:
            raise HTTPException(404, "Return not found")
        current = before["state"]
        if target not in RETURN_TRANSITIONS.get(current, set()):
            raise HTTPException(409, f"Invalid return transition: {current} -> {target}")
        if target in {"rejected", "voided"} and not (body.reason or "").strip():
            raise HTTPException(422, "Reason is required for rejected or voided returns")
        now = time.time()
        db.execute(
            "UPDATE return_reviews SET state=?,reviewer_id=?,reviewer_notes=?,reason=?,updated_at=? WHERE id=?",
            (target, user["id"], body.reviewer_notes, body.reason, now, return_id),
        )
        after = db.fetchone("SELECT * FROM return_reviews WHERE id=?", (return_id,))
    write_audit_event(
        actor_id=user["id"], actor_role=user["role"], action="return.review.transition",
        entity_type="return", entity_id=return_id, taxpayer_id=before["taxpayer_id"],
        before=_return(before), after=_return(after), reason=body.reason,
        correlation_id=secrets.token_hex(8),
    )
    return _return(after)
