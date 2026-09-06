"""Core tax filing API. Production filing transmission remains disabled until official integrations are configured."""
import os, sqlite3, time, uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/tax", tags=["tax-filing"])
DB = os.getenv("TAX_SQLITE_PATH", os.path.join(os.path.dirname(__file__), "tax_filing.db"))

def db():
    c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS tax_returns(id TEXT PRIMARY KEY,jurisdiction TEXT,taxpayer_type TEXT,tax_year INTEGER,gross_income REAL,deductions REAL,status TEXT,created_at REAL)")
    c.commit(); return c

class ReturnCreate(BaseModel):
    jurisdiction: str = "UG_URA"
    taxpayer_type: str = "individual"
    tax_year: int
    gross_income: float = 0
    deductions: float = 0

@router.get("/health")
def health(): return {"status":"ok","service":"tax-core","live_transmission":False}

@router.post("/returns")
def create_return(x: ReturnCreate):
    if x.gross_income < 0 or x.deductions < 0: raise HTTPException(400,"Amounts cannot be negative")
    rid=str(uuid.uuid4()); c=db(); c.execute("INSERT INTO tax_returns VALUES(?,?,?,?,?,?,?,?)",(rid,x.jurisdiction,x.taxpayer_type,x.tax_year,x.gross_income,x.deductions,"draft",time.time())); c.commit(); c.close()
    return {"id":rid,"status":"draft","jurisdiction":x.jurisdiction}

@router.get("/returns/{return_id}")
def get_return(return_id:str):
    c=db(); r=c.execute("SELECT * FROM tax_returns WHERE id=?",(return_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404,"Return not found")
    return dict(r)

@router.post("/returns/{return_id}/calculate")
def calculate(return_id:str):
    c=db(); r=c.execute("SELECT * FROM tax_returns WHERE id=?",(return_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Return not found")
    taxable=max(0.0,float(r["gross_income"])-float(r["deductions"])); c.execute("UPDATE tax_returns SET status='calculated' WHERE id=?",(return_id,)); c.commit(); c.close()
    return {"return_id":return_id,"taxable_income":taxable,"status":"calculated","tax_amount":None,"notice":"Tax liability requires verified jurisdiction/year rules before production use."}

@router.post("/returns/{return_id}/submit")
def submit(return_id:str):
    raise HTTPException(503,"Live tax transmission is disabled until official authority integration credentials and current rules are verified")
