"""Operational reporting endpoints for URA-PROMET."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from ops_store import get_ops_db
router=APIRouter(prefix="/ops",tags=["revenue-operations"])

def _epoch(value:str|None,end:bool=False)->float|None:
    if not value:return None
    try:dt=datetime.strptime(value,"%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:raise HTTPException(422,"Dates must use YYYY-MM-DD")
    return dt.timestamp()+(86400-0.000001 if end else 0)

def _aggregate(db,table,time_col,status_col,start,end,status,total_col=None):
    clauses=[];params=[]
    if start is not None:clauses.append(f"{time_col}>=?");params.append(start)
    if end is not None:clauses.append(f"{time_col}<=?");params.append(end)
    if status and status_col:clauses.append(f"{status_col}=?");params.append(status)
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    select="COUNT(*) AS count"+(f", COALESCE(SUM({total_col}),0) AS total" if total_col else "")
    row=db.fetchone(f"SELECT {select} FROM {table}{where}",params)
    result={"count":int(row["count"] or 0)}
    if total_col:result["total"]=float(row["total"] or 0)
    return result

@router.get("/reports/summary")
def summary_report(start:str|None=None,end:str|None=None,status:str|None=None):
    s=_epoch(start);e=_epoch(end,True)
    if s is not None and e is not None and s>e:raise HTTPException(422,"Start date must be on or before end date")
    with get_ops_db() as db:
        return {"filters":{"start":start,"end":end,"status":status},"returns":_aggregate(db,"return_reviews","created_at","state",s,e,status),"assessments":_aggregate(db,"assessments","created_at","status",s,e,status,"total"),"liabilities":_aggregate(db,"liabilities","created_at","status",s,e,status,"original_amount"),"payments":_aggregate(db,"payment_allocations","created_at",None,s,e,None,"amount"),"compliance":_aggregate(db,"compliance_records","updated_at",None,s,e,None),"cases":_aggregate(db,"cases","created_at","status",s,e,status),"notices":_aggregate(db,"notices","created_at","status",s,e,status)}
