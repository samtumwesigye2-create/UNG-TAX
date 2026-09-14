"""Operational reporting endpoints for URA-PROMET."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

import auth
from ops_auth import require_revenue_user
from ops_store import get_ops_db

router = APIRouter(prefix="/ops", tags=["revenue-operations"])


def _revenue_user(user=Depends(auth.require_auth)):
    return require_revenue_user(user)


def _epoch(value: str | None, end: bool = False) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, "Dates must use YYYY-MM-DD")
    if end:
        return dt.timestamp() + 86400 - 0.000001
    return dt.timestamp()


def _aggregate(db, table: str, time_col: str, status_col: str | None, start: float | None,
               end: float | None, status: str | None, total_col: str | None = None) -> dict:
    clauses = []
    params = []
    if start is not None:
        clauses.append(f"{time_col}>=?"); params.append(start)
    if end is not None:
        clauses.append(f"{time_col}<=?"); params.append(end)
    if status and status_col:
        clauses.append(f"{status_col}=?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    select = "COUNT(*) AS count"
    if total_col:
        select += f", COALESCE(SUM({total_col}),0) AS total"
    row = db.fetchone(f"SELECT {select} FROM {table}{where}", params)
    result = {"count": int(row["count"] or 0)}
    if total_col:
        result["total"] = float(row["total"] or 0)
    return result


@router.get("/reports/summary")
def summary_report(start: str | None = None, end: str | None = None, status: str | None = None,
                   user=Depends(_revenue_user)):
    start_epoch = _epoch(start)
    end_epoch = _epoch(end, end=True)
    if start_epoch is not None and end_epoch is not None and start_epoch > end_epoch:
        raise HTTPException(422, "Start date must be on or before end date")
    with get_ops_db() as db:
        returns = _aggregate(db, "return_reviews", "created_at", "state", start_epoch, end_epoch, status)
        assessments = _aggregate(db, "assessments", "created_at", "status", start_epoch, end_epoch, status, "total")
        liabilities = _aggregate(db, "liabilities", "created_at", "status", start_epoch, end_epoch, status, "original_amount")
        payments = _aggregate(db, "payment_allocations", "created_at", None, start_epoch, end_epoch, None, "amount")
        compliance = _aggregate(db, "compliance_records", "updated_at", None, start_epoch, end_epoch, None)
        cases = _aggregate(db, "cases", "created_at", "status", start_epoch, end_epoch, status)
        notices = _aggregate(db, "notices", "created_at", "status", start_epoch, end_epoch, status)
    return {
        "filters": {"start": start, "end": end, "status": status},
        "returns": returns,
        "assessments": assessments,
        "liabilities": liabilities,
        "payments": payments,
        "compliance": compliance,
        "cases": cases,
        "notices": notices,
    }
