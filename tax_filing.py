"""Core tax filing API.

Live filing transmission stays disabled until an official authority integration is configured.
Uganda payroll rules are effective-dated so historical payroll is not silently recalculated.
"""
import os, sqlite3, time, uuid
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tax", tags=["tax-filing"])
DB = os.getenv("TAX_SQLITE_PATH", os.path.join(os.path.dirname(__file__), "tax_filing.db"))

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS tax_returns(id TEXT PRIMARY KEY,jurisdiction TEXT,taxpayer_type TEXT,tax_year INTEGER,gross_income REAL,deductions REAL,status TEXT,created_at REAL)")
    c.commit()
    return c

class ReturnCreate(BaseModel):
    jurisdiction: str = "UG_URA"
    taxpayer_type: str = "individual"
    tax_year: int
    gross_income: float = 0
    deductions: float = 0

class PayrollRequest(BaseModel):
    gross_monthly_pay: float = Field(ge=0)
    pay_date: date
    resident: bool = True
    nssf_applicable: bool = True

class CorporateTaxRequest(BaseModel):
    chargeable_income: float = Field(ge=0)

# Pre-July-2026 resident PAYE schedule currently published on URA's PAYE page.
def _resident_paye_pre_2026_07(income: float) -> float:
    if income <= 235_000: return 0.0
    if income <= 335_000: return (income - 235_000) * 0.10
    if income <= 410_000: return 10_000 + (income - 335_000) * 0.20
    tax = 25_000 + (income - 410_000) * 0.30
    if income > 10_000_000: tax += (income - 10_000_000) * 0.10
    return tax

# FY2026/27 resident PAYE reform, effective 1 July 2026.
def _resident_paye_2026_07(income: float) -> float:
    if income <= 335_000: return 0.0
    if income <= 410_000: return (income - 335_000) * 0.20
    if income <= 485_000: return 15_000 + (income - 410_000) * 0.25
    if income <= 10_000_000: return 33_750 + (income - 485_000) * 0.30
    return 2_888_250 + (income - 10_000_000) * 0.40

def resident_paye(income: float, pay_date: date) -> tuple[float, str]:
    if pay_date >= date(2026, 7, 1):
        return round(_resident_paye_2026_07(income), 2), "UG-PAYE-2026-07"
    return round(_resident_paye_pre_2026_07(income), 2), "UG-PAYE-PRE-2026-07"

@router.get("/health")
def health():
    return {"status":"ok","service":"tax-core","live_transmission":False,"rules_version":"effective-dated"}

@router.post("/paye/calculate")
def calculate_paye(x: PayrollRequest):
    if not x.resident:
        raise HTTPException(422, "Non-resident 2026 schedule is not enabled until separately verified")
    paye, rules_version = resident_paye(x.gross_monthly_pay, x.pay_date)
    employee_nssf = round(x.gross_monthly_pay * 0.05, 2) if x.nssf_applicable else 0.0
    employer_nssf = round(x.gross_monthly_pay * 0.10, 2) if x.nssf_applicable else 0.0
    net_after_paye_and_employee_nssf = round(x.gross_monthly_pay - paye - employee_nssf, 2)
    return {
        "currency":"UGX",
        "gross_monthly_pay":x.gross_monthly_pay,
        "pay_date":x.pay_date.isoformat(),
        "resident":True,
        "paye":paye,
        "employee_nssf":employee_nssf,
        "employer_nssf":employer_nssf,
        "total_nssf":round(employee_nssf + employer_nssf, 2),
        "net_after_paye_and_employee_nssf":net_after_paye_and_employee_nssf,
        "rules_version":rules_version,
        "live_transmission":False,
    }

@router.post("/corporate/calculate")
def calculate_corporate_tax(x: CorporateTaxRequest):
    return {"currency":"UGX","chargeable_income":x.chargeable_income,"corporate_income_tax":round(x.chargeable_income * 0.30, 2),"rate":0.30,"live_transmission":False}

@router.post("/returns")
def create_return(x: ReturnCreate):
    if x.gross_income < 0 or x.deductions < 0: raise HTTPException(400,"Amounts cannot be negative")
    rid = str(uuid.uuid4()); c = db()
    c.execute("INSERT INTO tax_returns VALUES(?,?,?,?,?,?,?,?)",(rid,x.jurisdiction,x.taxpayer_type,x.tax_year,x.gross_income,x.deductions,"draft",time.time()))
    c.commit(); c.close()
    return {"id":rid,"status":"draft","jurisdiction":x.jurisdiction}

@router.get("/returns/{return_id}")
def get_return(return_id: str):
    c = db(); r = c.execute("SELECT * FROM tax_returns WHERE id=?",(return_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404,"Return not found")
    return dict(r)

@router.post("/returns/{return_id}/calculate")
def calculate(return_id: str):
    c = db(); r = c.execute("SELECT * FROM tax_returns WHERE id=?",(return_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Return not found")
    taxable = max(0.0,float(r["gross_income"])-float(r["deductions"]))
    c.execute("UPDATE tax_returns SET status='calculated' WHERE id=?",(return_id,)); c.commit(); c.close()
    return {"return_id":return_id,"taxable_income":taxable,"status":"calculated","tax_amount":None,"notice":"Use the jurisdiction-specific calculator for liability; filing transmission remains disabled."}

@router.post("/returns/{return_id}/submit")
def submit(return_id: str):
    raise HTTPException(503,"Live tax transmission is disabled until official authority integration credentials are configured")
