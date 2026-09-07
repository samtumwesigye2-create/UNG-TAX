"""
tax_filing.py — Core tax-filing engine, database layer, and API routes.

MERGE NOTE (Sept 2026): this file reconciles two branches that had diverged:
  - The GitHub UNG-PROMET branch, which corrected the Uganda PAYE math to be
    effective-dated (pre/post 1 July 2026) and added NSSF, but stripped the
    return/document/submission workflow down to almost nothing.
  - The "hardened" zip branch, which had the fuller taxpayer/return/line-item/
    document/submission workflow, but an unverified, unqualified annual PAYE
    bracket table.
This version keeps the verified monthly PAYE/NSSF engine as the source of
truth for payroll, and rebuilds the fuller return workflow on top of it
rather than reviving the old bracket table. See ANNUAL PAYE ESTIMATE below
for exactly how (and how honestly) individual annual returns use it.

JURISDICTION MODEL
-------------------
UG_URA is the primary jurisdiction, with real published tax figures (see
below for sources). It does NOT transmit real returns to URA; submission
today is a local mock that issues a confirmation code, because actual e-tax
transmission requires URA-issued integration credentials this build doesn't
have (see URAConnector below).

US_IRS also works end-to-end (this project started as a US prototype before
being scoped to Uganda) and is kept as a second option, same caveat about
not transmitting to the real IRS.
"""
import os, sqlite3, time, uuid, re
from datetime import date
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, Literal

import auth

DB = os.getenv("TAX_SQLITE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tax_filing.db"))
router = APIRouter(prefix="/tax", tags=["tax-filing"])


def db():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    c = db()
    c.execute("BEGIN IMMEDIATE")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_taxpayers(
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        taxpayer_type TEXT NOT NULL CHECK(taxpayer_type IN ('individual','business')),
        legal_name TEXT NOT NULL,
        tax_id_encrypted TEXT NOT NULL,
        tax_id_lookup TEXT NOT NULL,
        email TEXT NOT NULL,
        jurisdiction TEXT NOT NULL DEFAULT 'UG_URA',
        entity_subtype TEXT,
        created_at REAL NOT NULL,
        UNIQUE(tax_id_lookup, jurisdiction)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_returns(
        id TEXT PRIMARY KEY,
        taxpayer_id TEXT NOT NULL REFERENCES tax_taxpayers(id),
        tax_year INTEGER NOT NULL,
        jurisdiction TEXT NOT NULL DEFAULT 'UG_URA',
        filing_status TEXT,
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','calculated','submitted','accepted','rejected')),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE(taxpayer_id, tax_year)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_line_items(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL REFERENCES tax_returns(id),
        item_kind TEXT NOT NULL CHECK(item_kind IN ('income','deduction','expense')),
        category TEXT NOT NULL,
        description TEXT,
        amount REAL NOT NULL,
        created_at REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_calculations(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL REFERENCES tax_returns(id),
        gross_income REAL NOT NULL,
        total_deductions REAL NOT NULL,
        taxable_income REAL NOT NULL,
        tax_owed REAL NOT NULL,
        effective_rate REAL NOT NULL,
        amount_due REAL NOT NULL,
        refund_amount REAL NOT NULL,
        rules_version TEXT,
        calculated_at REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_submissions(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL REFERENCES tax_returns(id) UNIQUE,
        confirmation_code TEXT NOT NULL,
        submitted_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'accepted'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_documents(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL REFERENCES tax_returns(id),
        doc_type TEXT NOT NULL,
        filename TEXT,
        uploaded_at REAL NOT NULL,
        extraction_status TEXT NOT NULL DEFAULT 'pending'
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_returns_taxpayer ON tax_returns(taxpayer_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_items_return ON tax_line_items(return_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_taxpayers_user ON tax_taxpayers(user_id)")
    c.execute("COMMIT")
    c.close()


init()

# ---------------------------------------------------------------------------
# Uganda tax engine — effective-dated, verified (carried over from the
# UNG-PROMET hardening pass; see HANDOFF.md for sources).
# ---------------------------------------------------------------------------

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


# NSSF — mandatory contribution: employee 5%, employer 10% of gross monthly wage.
NSSF_EMPLOYEE_RATE = 0.05
NSSF_EMPLOYER_RATE = 0.10

UG_CORPORATE_FLAT_RATE = 0.30
UG_NON_RESIDENT_FLAT_RATE = 0.30  # gated off below until separately verified

# (min_turnover_exclusive, max_turnover_inclusive, base_amount, rate_on_excess_over_min)
# URA's official "with records" presumptive table (unaffected by the PAYE
# amendment — this is a separate turnover-based regime for small businesses).
UG_PRESUMPTIVE_BANDS = [
    (0, 10_000_000, 0, 0.0),
    (10_000_000, 30_000_000, 0, 0.004),
    (30_000_000, 50_000_000, 80_000, 0.005),
    (50_000_000, 80_000_000, 180_000, 0.006),
    (80_000_000, 150_000_000, 360_000, 0.007),
]
UG_PRESUMPTIVE_TURNOVER_CEILING = 150_000_000

@router.get("/health")
def health():
    return {"status": "ok", "service": "tax-core", "live_transmission": False, "rules_version": "effective-dated"}


@router.post("/paye/calculate")
def calculate_paye(x: PayrollRequest):
    """Standalone monthly payroll calculator — the verified source of truth
    for Uganda PAYE. Individual annual *returns* below reuse this rather
    than a separate, unverified annual bracket table."""
    if not x.resident:
        raise HTTPException(422, "Non-resident 2026 schedule is not enabled until separately verified")
    paye, rules_version = resident_paye(x.gross_monthly_pay, x.pay_date)
    employee_nssf = round(x.gross_monthly_pay * NSSF_EMPLOYEE_RATE, 2) if x.nssf_applicable else 0.0
    employer_nssf = round(x.gross_monthly_pay * NSSF_EMPLOYER_RATE, 2) if x.nssf_applicable else 0.0
    net = round(x.gross_monthly_pay - paye - employee_nssf, 2)
    return {
        "currency": "UGX", "gross_monthly_pay": x.gross_monthly_pay, "pay_date": x.pay_date.isoformat(),
        "resident": True, "paye": paye, "employee_nssf": employee_nssf, "employer_nssf": employer_nssf,
        "total_nssf": round(employee_nssf + employer_nssf, 2),
        "net_after_paye_and_employee_nssf": net, "rules_version": rules_version, "live_transmission": False,
    }


@router.post("/corporate/calculate")
def calculate_corporate_tax(x: CorporateTaxRequest):
    return {"currency": "UGX", "chargeable_income": x.chargeable_income,
            "corporate_income_tax": round(x.chargeable_income * UG_CORPORATE_FLAT_RATE, 2),
            "rate": UG_CORPORATE_FLAT_RATE, "live_transmission": False}


def _annual_resident_paye_estimate(annual_income: float, tax_year: int) -> tuple[float, str]:
    """ANNUAL PAYE ESTIMATE — read before changing.

    Uganda's PAYE is a monthly payroll withholding tax (see /tax/paye/calculate
    above); there is no separately-published annual bracket table. This
    estimate spreads the annual figure evenly across 12 months, applies the
    verified monthly schedule(s) for the tax year, and multiplies back up.
    That's a reasonable estimate for steady, even monthly pay — it will be
    wrong for anyone with uneven income across the year, which real payroll
    reconciliation would handle month-by-month.

    Tax years fully before or after the 1 July 2026 amendment use a single
    schedule. A tax year straddling the change (2026, if treated as a
    calendar year) blends 6 months of each schedule and is flagged as a
    blended estimate rather than presented as precise.
    """
    monthly = annual_income / 12.0
    if tax_year >= 2027:
        monthly_tax = _resident_paye_2026_07(monthly)
        rules_version = "UG-PAYE-2026-07-ANNUALIZED-ESTIMATE"
    elif tax_year <= 2025:
        monthly_tax = _resident_paye_pre_2026_07(monthly)
        rules_version = "UG-PAYE-PRE-2026-07-ANNUALIZED-ESTIMATE"
    else:
        monthly_tax = (_resident_paye_pre_2026_07(monthly) * 6 + _resident_paye_2026_07(monthly) * 6) / 12.0
        rules_version = "UG-PAYE-2026-BLENDED-ANNUALIZED-ESTIMATE"
    return round(monthly_tax * 12.0, 2), rules_version


def bracket_tax(taxable_income: float, brackets: list) -> float:
    tax = 0.0
    for lo, hi, rate in brackets:
        if taxable_income <= lo:
            break
        top = min(taxable_income, hi) if hi is not None else taxable_income
        tax += max(0.0, top - lo) * rate
    return round(tax, 2)


def ug_presumptive_tax(turnover: float):
    for lo, hi, base, rate in UG_PRESUMPTIVE_BANDS:
        if turnover <= hi:
            return round(base + max(0.0, turnover - lo) * rate, 2)
    return None  # above presumptive ceiling — standard corporate rate applies instead


# --- United States (secondary jurisdiction, unchanged) ---
US_INDIVIDUAL_BRACKETS = {
    "single": [(0, 11600, 0.10), (11600, 47150, 0.12), (47150, 100525, 0.22),
               (100525, 191950, 0.24), (191950, 243725, 0.32), (243725, 609350, 0.35), (609350, None, 0.37)],
    "married_joint": [(0, 23200, 0.10), (23200, 94300, 0.12), (94300, 201050, 0.22),
                       (201050, 383900, 0.24), (383900, 487450, 0.32), (487450, 731200, 0.35), (731200, None, 0.37)],
    "head_of_household": [(0, 16550, 0.10), (16550, 63100, 0.12), (63100, 100500, 0.22),
                           (100500, 191950, 0.24), (191950, 243700, 0.32), (243700, 609350, 0.35), (609350, None, 0.37)],
}
US_STANDARD_DEDUCTION = {"single": 14600, "married_joint": 29200, "head_of_household": 21900}
US_CORPORATE_FLAT_RATE = 0.21
US_SELF_EMPLOYMENT_TAX_RATE = 0.153


def calc_individual(gross_income: float, deductions: float, status: str, jurisdiction: str, tax_year: int) -> dict:
    if jurisdiction == "UG_URA":
        if status == "non_resident":
            raise HTTPException(422, "Non-resident Uganda individual tax is not enabled until separately verified")
        taxable = max(0.0, gross_income - deductions)
        owed, rules_version = _annual_resident_paye_estimate(taxable, tax_year)
        return {"gross_income": gross_income, "total_deductions": deductions,
                "taxable_income": taxable, "tax_owed": owed, "rules_version": rules_version}
    filing_status = status if status in US_STANDARD_DEDUCTION else "single"
    std = US_STANDARD_DEDUCTION[filing_status]
    total_deductions = max(deductions, std)
    taxable = max(0.0, gross_income - total_deductions)
    owed = bracket_tax(taxable, US_INDIVIDUAL_BRACKETS[filing_status])
    return {"gross_income": gross_income, "total_deductions": total_deductions,
            "taxable_income": taxable, "tax_owed": owed, "rules_version": "US-2024-BRACKETS"}


def calc_business(revenue: float, expenses: float, entity_subtype: str, jurisdiction: str) -> dict:
    net_profit = max(0.0, revenue - expenses)
    if jurisdiction == "UG_URA":
        if entity_subtype == "sole_proprietor" and revenue <= UG_PRESUMPTIVE_TURNOVER_CEILING:
            owed = ug_presumptive_tax(revenue)  # presumptive tax is charged on turnover, not net profit
            rules_version = "UG-PRESUMPTIVE-WITH-RECORDS"
        else:
            owed = round(net_profit * UG_CORPORATE_FLAT_RATE, 2)
            rules_version = "UG-CORPORATE-30PCT"
        return {"gross_income": revenue, "total_deductions": expenses,
                "taxable_income": net_profit, "tax_owed": owed, "rules_version": rules_version}
    if entity_subtype == "sole_proprietor":
        owed = round(net_profit * US_SELF_EMPLOYMENT_TAX_RATE, 2)  # SE tax only; income tax on profit is filed on the owner's individual return
        rules_version = "US-SE-TAX"
    else:
        owed = round(net_profit * US_CORPORATE_FLAT_RATE, 2)
        rules_version = "US-CORPORATE-21PCT"
    return {"gross_income": revenue, "total_deductions": expenses,
            "taxable_income": net_profit, "tax_owed": owed, "rules_version": rules_version}


class URAConnector:
    """Placeholder for the real Uganda Revenue Authority e-tax integration.

    URA's actual filing system (e-tax, at ura.go.ug) is a TIN-authenticated
    web portal; approved tax agents/software integrate via credentials URA
    issues after a registration process this build has no access to. Once
    that's available, implement submit_return() here to call it, and returns
    with jurisdiction 'UG_URA' will route through this class instead of the
    local mock submission used today.
    """
    def submit_return(self, return_id: str, payload: dict) -> str:
        raise NotImplementedError("Uganda Revenue Authority e-tax integration is not yet connected.")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TaxpayerIn(BaseModel):
    taxpayer_type: Literal["individual", "business"]
    legal_name: str
    tax_id: str
    email: str
    jurisdiction: Literal["UG_URA", "US_IRS"] = "UG_URA"
    entity_subtype: Optional[Literal["sole_proprietor", "corporation", "llc"]] = None


class ReturnIn(BaseModel):
    taxpayer_id: str
    tax_year: int
    # For UG_URA individual returns: 'resident' or 'non_resident' (non_resident is gated off — see calc_individual).
    # For US_IRS individual returns: 'single' / 'married_joint' / 'head_of_household'.
    filing_status: Optional[str] = None


class LineItemIn(BaseModel):
    item_kind: Literal["income", "deduction", "expense"]
    category: str
    description: Optional[str] = ""
    amount: float = Field(gt=0)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _tax_id_lookup_hash(tax_id: str, jurisdiction: str) -> str:
    """One-way hash used only to enforce uniqueness — the plaintext tax ID is
    never stored; only this hash (for lookups) and the encrypted value
    (for display) are."""
    import hashlib as _hashlib
    return _hashlib.sha256(f"{jurisdiction}:{tax_id.strip()}".encode()).hexdigest()


def _taxpayer_public(row: dict) -> dict:
    out = dict(row)
    encrypted = out.pop("tax_id_encrypted")
    out.pop("tax_id_lookup", None)
    try:
        decrypted = auth.decrypt_field(encrypted)
    except Exception:
        decrypted = None
    out["tax_id_masked"] = ("•" * max(0, len(decrypted) - 4) + decrypted[-4:]) if decrypted else None
    return out


@router.post("/taxpayers")
def create_taxpayer(body: TaxpayerIn, user=Depends(auth.require_auth)):
    if body.taxpayer_type == "business" and not body.entity_subtype:
        raise HTTPException(400, "entity_subtype is required for business taxpayers")
    c = db()
    try:
        i = str(uuid.uuid4())
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO tax_taxpayers(id,user_id,taxpayer_type,legal_name,tax_id_encrypted,tax_id_lookup,email,jurisdiction,entity_subtype,created_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (i, user["id"], body.taxpayer_type, body.legal_name.strip(),
                   auth.encrypt_field(body.tax_id.strip()),
                   _tax_id_lookup_hash(body.tax_id, body.jurisdiction),
                   body.email.strip(), body.jurisdiction, body.entity_subtype, time.time()))
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK")
        raise HTTPException(409, "A taxpayer with this tax ID already exists for this jurisdiction")
    finally:
        c.close()
    return get_taxpayer(i, user)


@router.get("/taxpayers/{taxpayer_id}")
def get_taxpayer(taxpayer_id: str, user=Depends(auth.require_auth)):
    c = db()
    r = c.execute("SELECT * FROM tax_taxpayers WHERE id=?", (taxpayer_id,)).fetchone()
    c.close()
    if not r:
        raise HTTPException(404, "Taxpayer not found")
    if r["user_id"] != user["id"]:
        raise HTTPException(403, "Not authorized to view this taxpayer")
    return _taxpayer_public(dict(r))


def _owned_return_or_404(c, return_id: str, user_id: str):
    """Fetches a return's row and its taxpayer, raising 404/403 if this user
    has no role (owner/preparer/viewer) on it. Returns (return_row, taxpayer_row)."""
    import tax_advanced
    ret = c.execute("SELECT * FROM tax_returns WHERE id=?", (return_id,)).fetchone()
    if not ret:
        raise HTTPException(404, "Return not found")
    tp = c.execute("SELECT * FROM tax_taxpayers WHERE id=?", (ret["taxpayer_id"],)).fetchone()
    role = tax_advanced.user_role_for_return(c, return_id, user_id)
    if not tp or role is None:
        raise HTTPException(403, "Not authorized to access this return")
    return ret, tp


@router.post("/returns")
def create_return(body: ReturnIn, user=Depends(auth.require_auth)):
    c = db()
    tp = c.execute("SELECT * FROM tax_taxpayers WHERE id=?", (body.taxpayer_id,)).fetchone()
    if not tp:
        c.close()
        raise HTTPException(404, "Taxpayer not found")
    if tp["user_id"] != user["id"]:
        c.close()
        raise HTTPException(403, "Not authorized to file for this taxpayer")
    if tp["taxpayer_type"] == "individual" and not body.filing_status:
        c.close()
        default_hint = "resident (non_resident is not yet enabled)" if tp["jurisdiction"] == "UG_URA" else "single/married_joint/head_of_household"
        raise HTTPException(400, f"filing_status is required for individual returns ({default_hint})")
    if tp["jurisdiction"] == "UG_URA" and body.filing_status == "non_resident":
        c.close()
        raise HTTPException(422, "Non-resident Uganda individual tax is not enabled until separately verified")
    try:
        i = str(uuid.uuid4())
        now = time.time()
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO tax_returns(id,taxpayer_id,tax_year,jurisdiction,filing_status,status,created_at,updated_at)
                     VALUES(?,?,?,?,?,'draft',?,?)""",
                  (i, body.taxpayer_id, body.tax_year, tp["jurisdiction"], body.filing_status, now, now))
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK")
        raise HTTPException(409, "A return already exists for this taxpayer and tax year")
    finally:
        c.close()
    return get_return(i, user)


@router.get("/returns/{return_id}")
def get_return(return_id: str, user=Depends(auth.require_auth)):
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    items = [dict(x) for x in c.execute("SELECT * FROM tax_line_items WHERE return_id=? ORDER BY created_at", (return_id,)).fetchall()]
    calc = c.execute("SELECT * FROM tax_calculations WHERE return_id=? ORDER BY calculated_at DESC LIMIT 1", (return_id,)).fetchone()
    submission = c.execute("SELECT * FROM tax_submissions WHERE return_id=?", (return_id,)).fetchone()
    documents = [dict(x) for x in c.execute("SELECT id,doc_type,filename,uploaded_at,extraction_status FROM tax_documents WHERE return_id=? ORDER BY uploaded_at", (return_id,)).fetchall()]
    c.close()
    out = dict(ret)
    out["line_items"] = items
    out["latest_calculation"] = dict(calc) if calc else None
    out["submission"] = dict(submission) if submission else None
    out["documents"] = documents
    out["validation"] = validate_return_data(dict(tp), items, dict(calc) if calc else None)
    return out


@router.post("/returns/{return_id}/line-items")
def add_line_item(return_id: str, body: LineItemIn, user=Depends(auth.require_auth)):
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    if ret["status"] not in ("draft", "calculated"):
        c.close()
        raise HTTPException(400, f"Cannot edit a return with status '{ret['status']}'")
    i = str(uuid.uuid4())
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_line_items(id,return_id,item_kind,category,description,amount,created_at)
                 VALUES(?,?,?,?,?,?,?)""",
              (i, return_id, body.item_kind, body.category.strip(), body.description, body.amount, time.time()))
    c.execute("UPDATE tax_returns SET status='draft', updated_at=? WHERE id=?", (time.time(), return_id))
    c.execute("COMMIT")
    c.close()
    return get_return(return_id, user)


@router.delete("/returns/{return_id}/line-items/{item_id}")
def delete_line_item(return_id: str, item_id: str, user=Depends(auth.require_auth)):
    c = db()
    _owned_return_or_404(c, return_id, user["id"])
    c.execute("BEGIN IMMEDIATE")
    r = c.execute("SELECT id FROM tax_line_items WHERE id=? AND return_id=?", (item_id, return_id)).fetchone()
    if not r:
        c.execute("ROLLBACK")
        c.close()
        raise HTTPException(404, "Line item not found")
    c.execute("DELETE FROM tax_line_items WHERE id=?", (item_id,))
    c.execute("UPDATE tax_returns SET status='draft', updated_at=? WHERE id=?", (time.time(), return_id))
    c.execute("COMMIT")
    c.close()
    return get_return(return_id, user)


# ---------------------------------------------------------------------------
# Real-time error checking
# ---------------------------------------------------------------------------

def validate_return_data(taxpayer: dict, items: list, calc: Optional[dict]) -> list:
    """Runs the same checks a human reviewer would do before e-filing.
    Returns a list of {field, severity, message}. severity is 'error'
    (blocks filing) or 'warning' (flag, doesn't block)."""
    issues = []
    income_items = [x for x in items if x["item_kind"] == "income"]
    other_items = [x for x in items if x["item_kind"] != "income"]

    if not income_items:
        issues.append({"field": "income", "severity": "error", "message": "Add at least one source of income before filing."})

    for x in items:
        if x["amount"] <= 0:
            issues.append({"field": x["id"], "severity": "error", "message": f"'{x['category']}' has an amount of zero or less."})
        if x["amount"] > 100_000_000:
            issues.append({"field": x["id"], "severity": "warning", "message": f"'{x['category']}' is unusually large — double check the amount."})

    if taxpayer["taxpayer_type"] == "business":
        revenue = sum(x["amount"] for x in income_items)
        expenses = sum(x["amount"] for x in other_items)
        if revenue and expenses > revenue * 3:
            issues.append({"field": "expenses", "severity": "warning",
                            "message": "Expenses are more than 3x revenue — this is a common audit flag, make sure it's accurate."})

    if not re.match(r"^\S+@\S+\.\S+$", taxpayer.get("email", "") or ""):
        issues.append({"field": "email", "severity": "warning", "message": "Email address looks incomplete — status updates will be sent here."})

    if calc and calc.get("taxable_income", 0) < 0:
        issues.append({"field": "taxable_income", "severity": "error", "message": "Taxable income came out negative — check your entries."})

    return issues


@router.get("/returns/{return_id}/validate")
def validate_return(return_id: str, user=Depends(auth.require_auth)):
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    items = [dict(x) for x in c.execute("SELECT * FROM tax_line_items WHERE return_id=?", (return_id,)).fetchall()]
    calc = c.execute("SELECT * FROM tax_calculations WHERE return_id=? ORDER BY calculated_at DESC LIMIT 1", (return_id,)).fetchone()
    c.close()
    issues = validate_return_data(dict(tp), items, dict(calc) if calc else None)
    return {"return_id": return_id, "issues": issues, "can_file": not any(i["severity"] == "error" for i in issues)}


@router.post("/returns/{return_id}/calculate")
def calculate_return(return_id: str, user=Depends(auth.require_auth)):
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    items = c.execute("SELECT * FROM tax_line_items WHERE return_id=?", (return_id,)).fetchall()
    c.close()

    income = sum(x["amount"] for x in items if x["item_kind"] == "income")
    deductions = sum(x["amount"] for x in items if x["item_kind"] == "deduction")
    expenses = sum(x["amount"] for x in items if x["item_kind"] == "expense")

    if tp["taxpayer_type"] == "individual":
        result = calc_individual(income, deductions, ret["filing_status"] or "resident", ret["jurisdiction"], ret["tax_year"])
    else:
        result = calc_business(income, expenses, tp["entity_subtype"] or "corporation", ret["jurisdiction"])

    withheld_or_paid = deductions if tp["taxpayer_type"] == "business" else 0  # placeholder hook for withholding/estimated payments
    tax_owed = result["tax_owed"]
    amount_due = max(0.0, tax_owed - withheld_or_paid)
    refund = max(0.0, withheld_or_paid - tax_owed)
    effective_rate = round((tax_owed / result["gross_income"]) * 100, 2) if result["gross_income"] > 0 else 0.0

    c = db()
    i = str(uuid.uuid4())
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_calculations(id,return_id,gross_income,total_deductions,taxable_income,tax_owed,effective_rate,amount_due,refund_amount,rules_version,calculated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (i, return_id, result["gross_income"], result["total_deductions"], result["taxable_income"],
               tax_owed, effective_rate, amount_due, refund, result.get("rules_version"), time.time()))
    c.execute("UPDATE tax_returns SET status='calculated', updated_at=? WHERE id=?", (time.time(), return_id))
    c.execute("COMMIT")
    c.close()
    return get_return(return_id, user)


@router.post("/returns/{return_id}/submit")
def submit_return(return_id: str, user=Depends(auth.require_auth)):
    import tax_advanced
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    if ret["status"] != "calculated":
        c.close()
        raise HTTPException(400, "Calculate the return before submitting")
    items = [dict(x) for x in c.execute("SELECT * FROM tax_line_items WHERE return_id=?", (return_id,)).fetchall()]
    calc = c.execute("SELECT * FROM tax_calculations WHERE return_id=? ORDER BY calculated_at DESC LIMIT 1", (return_id,)).fetchone()
    issues = validate_return_data(dict(tp), items, dict(calc) if calc else None)
    if any(i["severity"] == "error" for i in issues):
        c.close()
        raise HTTPException(400, "Return has unresolved errors — fix them before filing")
    if not tax_advanced.has_valid_signature(return_id):
        c.close()
        raise HTTPException(400, "This return must be signed (and re-signed if it changed since signing) before filing")
    existing = c.execute("SELECT id FROM tax_submissions WHERE return_id=?", (return_id,)).fetchone()
    c.close()
    if existing:
        raise HTTPException(409, "This return has already been submitted")

    if ret["jurisdiction"] == "UG_URA":
        # Will raise NotImplementedError until the real URA connector is built.
        URAConnector().submit_return(return_id, {})

    # US_IRS path today is a local mock acceptance — this app does not transmit
    # returns to the real IRS. It records a confirmation code and marks the
    # return accepted so the rest of the flow can be tested end-to-end.
    confirmation = f"{ret['jurisdiction']}-{time.strftime('%Y')}-{uuid.uuid4().hex[:10].upper()}"
    c = db()
    i = str(uuid.uuid4())
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_submissions(id,return_id,confirmation_code,submitted_at,status)
                 VALUES(?,?,?,?,'accepted')""", (i, return_id, confirmation, time.time()))
    c.execute("UPDATE tax_returns SET status='submitted', updated_at=? WHERE id=?", (time.time(), return_id))
    c.execute("COMMIT")
    c.close()
    tax_advanced.log_action(return_id, user["id"], "submitted", confirmation)
    return get_return(return_id, user)


@router.get("/returns/{return_id}/status")
def return_status(return_id: str, user=Depends(auth.require_auth)):
    r = get_return(return_id, user)
    return {"return_id": return_id, "status": r["status"], "submission": r["submission"]}


@router.get("/returns/{return_id}/track")
def track_refund(return_id: str, user=Depends(auth.require_auth)):
    """Live status tracking.

    NOTE — production wiring point: neither URA's e-tax portal nor the IRS's
    'Where's My Refund' exposes per-day refund progress to third-party
    filers via a public API. A real integration would poll the authority's
    acknowledgment endpoint (URAConnector / MeF) for accepted/rejected
    status, then direct the taxpayer to the authority's own portal for
    refund progress beyond that.

    Until then, this simulates a plausible progression from the submission
    timestamp so the frontend flow can be demonstrated end-to-end.
    """
    c = db()
    ret, tp = _owned_return_or_404(c, return_id, user["id"])
    sub = c.execute("SELECT * FROM tax_submissions WHERE return_id=?", (return_id,)).fetchone()
    c.close()
    if not sub:
        raise HTTPException(400, "This return has not been filed yet")
    elapsed = time.time() - sub["submitted_at"]
    if elapsed < 60:
        stage, label = "accepted", "Received and accepted"
    elif elapsed < 180:
        stage, label = "processing", "Being processed"
    else:
        stage, label = "completed", "Processing complete — refund or balance finalized"
    return {"return_id": return_id, "confirmation_code": sub["confirmation_code"], "stage": stage, "label": label,
            "note": "Demo simulation — see server code comment for what a live IRS/URA integration would need."}


# ---------------------------------------------------------------------------
# Automated data import (OCR) — see tax_advanced.capabilities() for status
# ---------------------------------------------------------------------------

def extract_document_fields(doc_type: str, filename: str, content: bytes) -> dict:
    """Production wiring point for automated data import.

    A real implementation would route here based on file type:
      - Images (jpg/png of a payslip): OCR via a service like AWS Textract,
        Google Document AI, or `pytesseract` locally.
      - PDFs: text extraction via `pdfplumber`/`PyPDF2`, falling back to OCR
        for scanned PDFs.
      - Direct import: many payroll providers and banks support pulling
        payslips directly via APIs instead of asking the user to upload a
        file at all — that's a separate connector (see FinancialConnector
        in tax_advanced.py), not a file parser.

    This build has no network access to install an OCR/PDF library, so it
    returns a clearly-labeled mock extraction. Nothing gets added to the
    return automatically — the frontend shows suggested amounts and the
    user must confirm each one, exactly like real tax software does after
    OCR (autofill, never auto-submit).
    """
    if doc_type in ("payslip", "w2"):
        return {"suggested_items": [{"item_kind": "income", "category": "Employment income", "amount": None,
                                      "note": "Could not read this file automatically in this environment — enter the gross amount from your payslip/employer statement manually."}]}
    if doc_type in ("1099", "withholding_cert"):
        return {"suggested_items": [{"item_kind": "income", "category": "Other income", "amount": None,
                                      "note": "Could not read this file automatically in this environment — enter the reported amount manually."}]}
    return {"suggested_items": []}


@router.post("/returns/{return_id}/documents")
async def upload_document(return_id: str, doc_type: str = Form(...), file: UploadFile = File(...), user=Depends(auth.require_auth)):
    c = db()
    _owned_return_or_404(c, return_id, user["id"])
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        c.close()
        raise HTTPException(400, "File too large (15MB limit)")
    i = str(uuid.uuid4())
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_documents(id,return_id,doc_type,filename,uploaded_at,extraction_status)
                 VALUES(?,?,?,?,?,'processed')""", (i, return_id, doc_type, file.filename, time.time()))
    c.execute("COMMIT")
    c.close()
    extraction = extract_document_fields(doc_type, file.filename, content)
    return {"document_id": i, **extraction}
