"""URA-PROMET Revenue Operations API."""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query

import auth
from ops_audit import write_audit_event
from ops_auth import require_revenue_user
from ops_models import (
    ASSESSMENT_STATES,
    RETURN_TRANSITIONS,
    AssessmentCreate,
    AssessmentPatch,
    CompliancePatch,
    InstallmentCreate,
    InstallmentPatch,
    NoteIn,
    PaymentAllocationIn,
    ReturnReviewPatch,
    ReversalIn,
    TaxpayerPatch,
)
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


def _compliance(row: dict) -> dict:
    out = dict(row)
    out["risk_flags"] = _json(out.pop("risk_flags_json", "[]"), [])
    return out


def _assessment_with_lines(db, row: dict) -> dict:
    out = dict(row)
    out["lines"] = db.fetchall(
        "SELECT * FROM assessment_lines WHERE assessment_id=? ORDER BY created_at,id",
        (out["id"],),
    )
    return out


def _liability_view(db, row: dict) -> dict:
    out = dict(row)
    allocated = db.fetchone(
        "SELECT COALESCE(SUM(amount),0) AS total FROM payment_allocations WHERE liability_id=?",
        (out["id"],),
    )["total"]
    out["allocated_amount"] = allocated
    out["open_balance"] = out["original_amount"] - allocated
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


@router.post("/assessments", status_code=201)
def create_assessment(body: AssessmentCreate, user=Depends(_revenue_user)):
    for line in body.adjustments:
        if line.amount != 0 and not (line.reason or "").strip():
            raise HTTPException(422, "Adjustment reason is required")
    assessment_id = secrets.token_hex(16)
    now = time.time()
    adjustments_total = sum(line.amount for line in body.adjustments)
    total = body.principal + body.penalty + body.interest + adjustments_total
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO assessments(id,taxpayer_id,return_id,status,principal,penalty,interest,total,reason,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (assessment_id, body.taxpayer_id, body.return_id, "draft", body.principal, body.penalty, body.interest, total, body.reason, user["id"], now, now),
        )
        for line in body.adjustments:
            db.execute(
                "INSERT INTO assessment_lines(id,assessment_id,line_type,amount,reason,created_at) VALUES(?,?,?,?,?,?)",
                (secrets.token_hex(16), assessment_id, line.line_type, line.amount, line.reason, now),
            )
        row = db.fetchone("SELECT * FROM assessments WHERE id=?", (assessment_id,))
        after = _assessment_with_lines(db, row)
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="assessment.create",
                      entity_type="assessment", entity_id=assessment_id, taxpayer_id=body.taxpayer_id,
                      before={}, after=after, reason=body.reason, correlation_id=secrets.token_hex(8))
    return after


@router.get("/assessments")
def list_assessments(taxpayer_id: str | None = None, status: str | None = None, user=Depends(_revenue_user)):
    clauses, params = [], []
    if taxpayer_id:
        clauses.append("taxpayer_id=?"); params.append(taxpayer_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM assessments{where} ORDER BY updated_at DESC LIMIT 250", params)
        items = [_assessment_with_lines(db, row) for row in rows]
    return {"items": items}


@router.patch("/assessments/{assessment_id}")
def patch_assessment(assessment_id: str, body: AssessmentPatch, user=Depends(_revenue_user)):
    if body.status is not None and body.status not in ASSESSMENT_STATES:
        raise HTTPException(422, "Invalid assessment status")
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM assessments WHERE id=?", (assessment_id,))
        if not before:
            raise HTTPException(404, "Assessment not found")
        updates = body.model_dump(exclude_unset=True)
        reason = updates.pop("reason", None)
        if any(k in updates for k in {"principal", "penalty", "interest"}) and not (reason or "").strip():
            raise HTTPException(422, "Reason is required when changing assessment amounts")
        principal = updates.get("principal", before["principal"])
        penalty = updates.get("penalty", before["penalty"])
        interest = updates.get("interest", before["interest"])
        adjustment_total = db.fetchone("SELECT COALESCE(SUM(amount),0) AS total FROM assessment_lines WHERE assessment_id=?", (assessment_id,))["total"]
        total = principal + penalty + interest + adjustment_total
        db.execute(
            "UPDATE assessments SET status=?,principal=?,penalty=?,interest=?,total=?,reason=?,updated_at=? WHERE id=?",
            (updates.get("status", before["status"]), principal, penalty, interest, total, reason or before.get("reason"), time.time(), assessment_id),
        )
        after_row = db.fetchone("SELECT * FROM assessments WHERE id=?", (assessment_id,))
        before_full = _assessment_with_lines(db, before)
        after_full = _assessment_with_lines(db, after_row)
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="assessment.update",
                      entity_type="assessment", entity_id=assessment_id, taxpayer_id=before["taxpayer_id"],
                      before=before_full, after=after_full, reason=reason, correlation_id=secrets.token_hex(8))
    return after_full


@router.get("/compliance/{taxpayer_id}")
def get_compliance(taxpayer_id: str, user=Depends(_revenue_user)):
    with get_ops_db() as db:
        row = db.fetchone("SELECT * FROM compliance_records WHERE taxpayer_id=?", (taxpayer_id,))
    if not row:
        return {"taxpayer_id": taxpayer_id, "filing_compliance": "unknown", "payment_compliance": "unknown", "risk_flags": [], "notes": None, "next_action_date": None}
    return _compliance(row)


@router.patch("/compliance/{taxpayer_id}")
def patch_compliance(taxpayer_id: str, body: CompliancePatch, user=Depends(_revenue_user)):
    now = time.time()
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM compliance_records WHERE taxpayer_id=?", (taxpayer_id,))
        current = _compliance(before) if before else {
            "taxpayer_id": taxpayer_id,
            "filing_compliance": "unknown",
            "payment_compliance": "unknown",
            "risk_flags": [],
            "notes": None,
            "next_action_date": None,
            "updated_by": user["id"],
            "updated_at": now,
        }
        incoming = body.model_dump(exclude_unset=True)
        merged = dict(current)
        merged.update(incoming)
        risk_flags_json = json.dumps(merged.get("risk_flags") or [], sort_keys=True)
        if before:
            db.execute(
                "UPDATE compliance_records SET filing_compliance=?,payment_compliance=?,risk_flags_json=?,notes=?,next_action_date=?,updated_by=?,updated_at=? WHERE taxpayer_id=?",
                (merged["filing_compliance"], merged["payment_compliance"], risk_flags_json, merged.get("notes"), merged.get("next_action_date"), user["id"], now, taxpayer_id),
            )
        else:
            db.execute(
                "INSERT INTO compliance_records(taxpayer_id,filing_compliance,payment_compliance,risk_flags_json,notes,next_action_date,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (taxpayer_id, merged["filing_compliance"], merged["payment_compliance"], risk_flags_json, merged.get("notes"), merged.get("next_action_date"), user["id"], now),
            )
        after = db.fetchone("SELECT * FROM compliance_records WHERE taxpayer_id=?", (taxpayer_id,))
    after_out = _compliance(after)
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="compliance.update",
                      entity_type="compliance", entity_id=taxpayer_id, taxpayer_id=taxpayer_id,
                      before=current if before else {}, after=after_out, reason=body.notes,
                      correlation_id=secrets.token_hex(8))
    return after_out


@router.get("/liabilities")
def list_liabilities(taxpayer_id: str | None = None, status: str | None = None, user=Depends(_revenue_user)):
    clauses, params = [], []
    if taxpayer_id:
        clauses.append("taxpayer_id=?"); params.append(taxpayer_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_ops_db() as db:
        rows = db.fetchall(f"SELECT * FROM liabilities{where} ORDER BY updated_at DESC LIMIT 250", params)
        items = [_liability_view(db, row) for row in rows]
    return {"items": items}


@router.post("/payments/allocations", status_code=201)
def create_payment_allocation(body: PaymentAllocationIn, user=Depends(_revenue_user)):
    allocation_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        liability = db.fetchone("SELECT * FROM liabilities WHERE id=?", (body.liability_id,))
        if not liability:
            raise HTTPException(404, "Liability not found")
        view = _liability_view(db, liability)
        if body.amount > view["open_balance"] + 1e-9:
            raise HTTPException(409, "Allocation exceeds open liability balance")
        db.execute(
            "INSERT INTO payment_allocations(id,taxpayer_id,liability_id,amount,payment_reference,reversal_of,reason,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (allocation_id, body.taxpayer_id, body.liability_id, body.amount, body.payment_reference, None, body.reason, user["id"], now),
        )
        row = db.fetchone("SELECT * FROM payment_allocations WHERE id=?", (allocation_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="payment.allocate",
                      entity_type="payment_allocation", entity_id=allocation_id, taxpayer_id=body.taxpayer_id,
                      before={}, after=row, reason=body.reason, correlation_id=secrets.token_hex(8))
    return row


@router.post("/payments/{allocation_id}/reverse", status_code=201)
def reverse_payment_allocation(allocation_id: str, body: ReversalIn, user=Depends(_revenue_user)):
    reversal_id = secrets.token_hex(16)
    now = time.time()
    with get_ops_db() as db:
        original = db.fetchone("SELECT * FROM payment_allocations WHERE id=?", (allocation_id,))
        if not original:
            raise HTTPException(404, "Payment allocation not found")
        already = db.fetchone("SELECT id FROM payment_allocations WHERE reversal_of=?", (allocation_id,))
        if already:
            raise HTTPException(409, "Payment allocation already reversed")
        db.execute(
            "INSERT INTO payment_allocations(id,taxpayer_id,liability_id,amount,payment_reference,reversal_of,reason,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (reversal_id, original["taxpayer_id"], original["liability_id"], -original["amount"], original["payment_reference"], allocation_id, body.reason, user["id"], now),
        )
        reversal = db.fetchone("SELECT * FROM payment_allocations WHERE id=?", (reversal_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="payment.reverse",
                      entity_type="payment_allocation", entity_id=reversal_id, taxpayer_id=original["taxpayer_id"],
                      before=original, after=reversal, reason=body.reason, correlation_id=secrets.token_hex(8))
    return reversal


@router.post("/installments", status_code=201)
def create_installment_plan(body: InstallmentCreate, user=Depends(_revenue_user)):
    plan_id = secrets.token_hex(16)
    now = time.time()
    if body.liability_id:
        with get_ops_db() as db:
            liability = db.fetchone("SELECT * FROM liabilities WHERE id=?", (body.liability_id,))
            if not liability:
                raise HTTPException(404, "Liability not found")
            open_balance = _liability_view(db, liability)["open_balance"]
            if body.total_amount > open_balance + 1e-9:
                raise HTTPException(409, "Installment total exceeds open liability balance")
    with get_ops_db() as db:
        db.execute(
            "INSERT INTO installment_plans(id,taxpayer_id,liability_id,total_amount,installment_count,frequency,start_date,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, body.taxpayer_id, body.liability_id, body.total_amount, body.installment_count, body.frequency, body.start_date, "active", user["id"], now, now),
        )
        row = db.fetchone("SELECT * FROM installment_plans WHERE id=?", (plan_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="installment.create",
                      entity_type="installment_plan", entity_id=plan_id, taxpayer_id=body.taxpayer_id,
                      before={}, after=row, correlation_id=secrets.token_hex(8))
    return row


@router.patch("/installments/{plan_id}")
def patch_installment_plan(plan_id: str, body: InstallmentPatch, user=Depends(_revenue_user)):
    allowed = {"active", "suspended", "completed", "cancelled", "archived"}
    if body.status not in allowed:
        raise HTTPException(422, "Invalid installment status")
    with get_ops_db() as db:
        before = db.fetchone("SELECT * FROM installment_plans WHERE id=?", (plan_id,))
        if not before:
            raise HTTPException(404, "Installment plan not found")
        db.execute("UPDATE installment_plans SET status=?,updated_at=? WHERE id=?", (body.status, time.time(), plan_id))
        after = db.fetchone("SELECT * FROM installment_plans WHERE id=?", (plan_id,))
    write_audit_event(actor_id=user["id"], actor_role=user["role"], action="installment.update",
                      entity_type="installment_plan", entity_id=plan_id, taxpayer_id=before["taxpayer_id"],
                      before=before, after=after, reason=body.reason, correlation_id=secrets.token_hex(8))
    return after
