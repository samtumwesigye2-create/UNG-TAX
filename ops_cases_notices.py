"""Direct-access notices and case workflows for URA-PROMET."""
from __future__ import annotations
import json,secrets,time
from fastapi import APIRouter,HTTPException
from ops_audit import write_audit_event
from ops_models import CaseCreate,CaseEventIn,CasePatch,NoticeCreate,NoticePatch,NOTICE_STATES
from ops_store import get_ops_db
router=APIRouter(prefix="/ops",tags=["revenue-operations"])
ACTOR={"id":"promet-direct","role":"revenue_operations"}
NOTICE_TRANSITIONS={"draft":{"approved","cancelled","archived"},"approved":{"issued","cancelled","archived"},"issued":{"cancelled","archived"},"cancelled":{"archived"},"archived":set()}
CASE_TRANSITIONS={"open":{"suspended","closed","voided","archived"},"suspended":{"reopened","closed","voided","archived"},"reopened":{"suspended","closed","voided","archived"},"closed":{"reopened","archived"},"voided":{"archived"},"archived":set()}
def audit(action,etype,eid,taxpayer,before,after,reason=None):write_audit_event(actor_id=ACTOR["id"],actor_role=ACTOR["role"],action=action,entity_type=etype,entity_id=eid,taxpayer_id=taxpayer,before=before,after=after,reason=reason,correlation_id=secrets.token_hex(8))
@router.post("/notices",status_code=201)
def create_notice(body:NoticeCreate):
 n=secrets.token_hex(16);now=time.time()
 with get_ops_db() as db:
  if body.supersedes_notice_id and not db.fetchone("SELECT id FROM notices WHERE id=?",(body.supersedes_notice_id,)):raise HTTPException(404,"Superseded notice not found")
  db.execute("INSERT INTO notices(id,taxpayer_id,notice_type,subject,content,status,related_entity_type,related_entity_id,supersedes_notice_id,issued_at,issued_by,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(n,body.taxpayer_id,body.notice_type,body.subject,body.content,"draft",body.related_entity_type,body.related_entity_id,body.supersedes_notice_id,None,None,ACTOR["id"],now,now));row=db.fetchone("SELECT * FROM notices WHERE id=?",(n,))
 audit("notice.create","notice",n,body.taxpayer_id,{},row);return dict(row)
@router.get("/notices")
def list_notices(taxpayer_id:str|None=None,status:str|None=None):
 c=[];p=[]
 if taxpayer_id:c.append("taxpayer_id=?");p.append(taxpayer_id)
 if status:c.append("status=?");p.append(status)
 w=(" WHERE "+" AND ".join(c)) if c else ""
 with get_ops_db() as db:rows=db.fetchall(f"SELECT * FROM notices{w} ORDER BY updated_at DESC LIMIT 250",p)
 return {"items":[dict(x) for x in rows]}
@router.patch("/notices/{notice_id}")
def patch_notice(notice_id:str,body:NoticePatch):
 with get_ops_db() as db:
  before=db.fetchone("SELECT * FROM notices WHERE id=?",(notice_id,))
  if not before:raise HTTPException(404,"Notice not found")
  u=body.model_dump(exclude_unset=True);reason=u.pop("reason",None);target=u.get("status",before["status"])
  if before["status"]=="issued" and any(k in u for k in {"subject","content"}):raise HTTPException(409,"Issued notice content is immutable")
  if target not in NOTICE_STATES:raise HTTPException(422,"Invalid notice status")
  if target!=before["status"] and target not in NOTICE_TRANSITIONS.get(before["status"],set()):raise HTTPException(409,"Invalid notice transition")
  issued_at=before["issued_at"];issued_by=before["issued_by"]
  if target=="issued" and before["status"]!="issued":issued_at=time.time();issued_by=ACTOR["id"]
  db.execute("UPDATE notices SET subject=?,content=?,status=?,issued_at=?,issued_by=?,updated_at=? WHERE id=?",(u.get("subject",before["subject"]),u.get("content",before["content"]),target,issued_at,issued_by,time.time(),notice_id));after=db.fetchone("SELECT * FROM notices WHERE id=?",(notice_id,))
 audit("notice.update","notice",notice_id,before["taxpayer_id"],before,after,reason);return dict(after)
@router.post("/cases",status_code=201)
def create_case(body:CaseCreate):
 cid=secrets.token_hex(16);now=time.time()
 with get_ops_db() as db:db.execute("INSERT INTO cases(id,taxpayer_id,case_type,title,description,priority,status,assigned_to,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,body.taxpayer_id,body.case_type,body.title,body.description,body.priority,"open",body.assigned_to,ACTOR["id"],now,now));row=db.fetchone("SELECT * FROM cases WHERE id=?",(cid,))
 audit("case.create","case",cid,body.taxpayer_id,{},row);return dict(row)
@router.get("/cases")
def list_cases(taxpayer_id:str|None=None,status:str|None=None):
 c=[];p=[]
 if taxpayer_id:c.append("taxpayer_id=?");p.append(taxpayer_id)
 if status:c.append("status=?");p.append(status)
 w=(" WHERE "+" AND ".join(c)) if c else ""
 with get_ops_db() as db:rows=db.fetchall(f"SELECT * FROM cases{w} ORDER BY updated_at DESC LIMIT 250",p)
 return {"items":[dict(x) for x in rows]}
@router.patch("/cases/{case_id}")
def patch_case(case_id:str,body:CasePatch):
 with get_ops_db() as db:
  before=db.fetchone("SELECT * FROM cases WHERE id=?",(case_id,))
  if not before:raise HTTPException(404,"Case not found")
  u=body.model_dump(exclude_unset=True);reason=u.pop("reason",None);target=u.get("status",before["status"])
  if target!=before["status"]:
   if target not in CASE_TRANSITIONS.get(before["status"],set()):raise HTTPException(409,"Invalid case transition")
   if not (reason or "").strip():raise HTTPException(422,"Reason is required for case status changes")
  db.execute("UPDATE cases SET title=?,description=?,priority=?,assigned_to=?,status=?,updated_at=? WHERE id=?",(u.get("title",before["title"]),u.get("description",before["description"]),u.get("priority",before["priority"]),u.get("assigned_to",before["assigned_to"]),target,time.time(),case_id));after=db.fetchone("SELECT * FROM cases WHERE id=?",(case_id,))
 audit("case.update","case",case_id,before["taxpayer_id"],before,after,reason);return dict(after)
@router.post("/cases/{case_id}/events",status_code=201)
def add_case_event(case_id:str,body:CaseEventIn):
 eid=secrets.token_hex(16);now=time.time()
 with get_ops_db() as db:
  case=db.fetchone("SELECT * FROM cases WHERE id=?",(case_id,))
  if not case:raise HTTPException(404,"Case not found")
  db.execute("INSERT INTO case_events(id,case_id,event_type,note,metadata_json,actor_id,created_at) VALUES(?,?,?,?,?,?,?)",(eid,case_id,body.event_type,body.note,json.dumps(body.metadata or {},sort_keys=True),ACTOR["id"],now));row=db.fetchone("SELECT * FROM case_events WHERE id=?",(eid,))
 out=dict(row);out["metadata"]=json.loads(out.pop("metadata_json") or "{}");audit("case.event.add","case",case_id,case["taxpayer_id"],{},out,body.note);return out
