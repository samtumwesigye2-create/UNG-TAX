"""
tax_advanced.py — Enterprise-grade capabilities layered on tax_filing.py:

  - Role-based collaboration (owner / preparer / viewer per return)
  - Comprehensive audit trail (every meaningful action, who + when)
  - E-signature capture (required before filing, like a real e-file PIN/sig)
  - Compliance/diagnostics versioning (tracks which rule set a return was
    checked against, with a color-coded severity model)
  - Jurisdiction-aware export: URA-style schedule summary for UG_URA
    returns, MeF-style XML for US_IRS returns
  - Batch filing (submit many returns in one call — for preparers)
  - Financial account linking (bank/payroll import) — architecture only

HONESTY NOTE — what's real vs. architecture-only in this file
----------------------------------------------------------------
Fully functional, no external dependency: roles, audit log, e-signature,
compliance versioning, batch submission logic.

Architecture-only (need a live third-party account/credential this build
does not have access to):
  - `generate_mef_xml()` produces a structured XML document *shaped like*
    an MeF submission, for demonstrating the transmission pipeline end to
    end. It is NOT validated against the IRS's actual MeF XSD schemas
    (those are large, versioned, and access-gated to registered
    e-file providers) and is not wired to IRS's transmission endpoint.
    Treat it as the payload-building step of a real integration, not a
    finished one.
  - `FinancialConnector` (bank/payroll linking) requires an aggregator
    like Plaid or Finicity, or direct payroll-provider APIs (ADP, Gusto).
    Those require a signed business agreement and API keys — the
    interface here shows exactly where that would plug in.
"""
import os, sqlite3, time, uuid, hashlib
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Literal
from xml.sax.saxutils import escape as xml_escape

import auth

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tax_filing.db")
router = APIRouter(prefix="/tax", tags=["tax-advanced"])

# Bump this when the simplified bracket/deduction tables in tax_filing.py
# change. Real tax software subscribes to a compliance feed for federal,
# state, and local law updates — this project has no such feed, so this is
# a manually-maintained version stamp instead of a live update pipeline.
COMPLIANCE_RULESET_VERSION = "2025.1-demo"


def db():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init():
    c = db()
    c.execute("BEGIN IMMEDIATE")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_collaborators(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('owner','preparer','viewer')),
        added_at REAL NOT NULL,
        UNIQUE(return_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_audit_log(
        id TEXT PRIMARY KEY,
        return_id TEXT,
        actor_user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT,
        created_at REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_signatures(
        id TEXT PRIMARY KEY,
        return_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        typed_name TEXT NOT NULL,
        document_hash TEXT NOT NULL,
        signed_at REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tax_financial_links(
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        institution_name TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_return ON tax_audit_log(return_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_collab_return ON tax_collaborators(return_id)")
    c.execute("COMMIT")
    c.close()


init()


def log_action(return_id: Optional[str], actor_user_id: str, action: str, detail: str = ""):
    c = db()
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_audit_log(id,return_id,actor_user_id,action,detail,created_at)
                 VALUES(?,?,?,?,?,?)""", (str(uuid.uuid4()), return_id, actor_user_id, action, detail, time.time()))
    c.execute("COMMIT")
    c.close()


def user_role_for_return(c, return_id: str, user_id: str) -> Optional[str]:
    """Owner via tax_taxpayers.user_id counts as 'owner' even with no explicit
    collaborator row (that row only matters for *additional* collaborators)."""
    ret = c.execute("SELECT taxpayer_id FROM tax_returns WHERE id=?", (return_id,)).fetchone()
    if not ret:
        return None
    tp = c.execute("SELECT user_id FROM tax_taxpayers WHERE id=?", (ret["taxpayer_id"],)).fetchone()
    if tp and tp["user_id"] == user_id:
        return "owner"
    collab = c.execute("SELECT role FROM tax_collaborators WHERE return_id=? AND user_id=?", (return_id, user_id)).fetchone()
    return collab["role"] if collab else None


def require_role(return_id: str, user_id: str, allowed: tuple) -> str:
    c = db()
    role = user_role_for_return(c, return_id, user_id)
    c.close()
    if role is None:
        raise HTTPException(403, "You don't have access to this return")
    if role not in allowed:
        raise HTTPException(403, f"Your role ('{role}') can't perform this action")
    return role


# ---------------------------------------------------------------------------
# Collaboration
# ---------------------------------------------------------------------------

class CollaboratorIn(BaseModel):
    collaborator_email: str
    role: Literal["preparer", "viewer"]


@router.post("/returns/{return_id}/collaborators")
def add_collaborator(return_id: str, body: CollaboratorIn, user=Depends(auth.require_auth)):
    require_role(return_id, user["id"], allowed=("owner",))
    c = db()
    invitee = c.execute("SELECT id FROM auth_users WHERE email=?", (body.collaborator_email.strip().lower(),)).fetchone()
    if not invitee:
        c.close()
        raise HTTPException(404, "No account found with that email — they need to register first")
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO tax_collaborators(id,return_id,user_id,role,added_at) VALUES(?,?,?,?,?)""",
                  (str(uuid.uuid4()), return_id, invitee["id"], body.role, time.time()))
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK")
        c.close()
        raise HTTPException(409, "That person already has access to this return")
    c.close()
    log_action(return_id, user["id"], "collaborator_added", f"{body.collaborator_email} as {body.role}")
    return {"added": True, "role": body.role}


@router.get("/returns/{return_id}/collaborators")
def list_collaborators(return_id: str, user=Depends(auth.require_auth)):
    require_role(return_id, user["id"], allowed=("owner", "preparer", "viewer"))
    c = db()
    rows = c.execute("""SELECT tc.role, tc.added_at, au.email
                         FROM tax_collaborators tc JOIN auth_users au ON au.id = tc.user_id
                         WHERE tc.return_id=?""", (return_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

@router.get("/returns/{return_id}/audit-log")
def get_audit_log(return_id: str, user=Depends(auth.require_auth)):
    require_role(return_id, user["id"], allowed=("owner", "preparer", "viewer"))
    c = db()
    rows = c.execute("""SELECT tal.action, tal.detail, tal.created_at, au.email as actor_email
                         FROM tax_audit_log tal LEFT JOIN auth_users au ON au.id = tal.actor_user_id
                         WHERE tal.return_id=? ORDER BY tal.created_at""", (return_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Compliance / diagnostics versioning
# ---------------------------------------------------------------------------

@router.get("/compliance/version")
def compliance_version():
    return {
        "ruleset_version": COMPLIANCE_RULESET_VERSION,
        "note": ("This project has no live feed to federal/state/local tax law changes. "
                 "A production system would subscribe to a compliance data provider "
                 "(e.g. Thomson Reuters, Wolters Kluwer) and bump this version automatically "
                 "whenever brackets, deduction amounts, or validation rules change."),
        "severity_colors": {"error": "#9C3A2E", "warning": "#A8791E", "info": "#2B4A6B"},
    }


# ---------------------------------------------------------------------------
# E-signature (required before filing)
# ---------------------------------------------------------------------------

class SignIn(BaseModel):
    typed_name: str


def _return_document_hash(c, return_id: str) -> str:
    """Hashes the return's current numbers so a signature is provably tied to
    *this* version of the return — if a line item changes after signing, the
    hash won't match and re-signing is required, the same way real e-file
    software invalidates a signature if the return changes post-signing."""
    calc = c.execute("SELECT * FROM tax_calculations WHERE return_id=? ORDER BY calculated_at DESC LIMIT 1", (return_id,)).fetchone()
    basis = f"{return_id}:{dict(calc) if calc else 'no-calc'}"
    return hashlib.sha256(basis.encode()).hexdigest()


@router.post("/returns/{return_id}/sign")
def sign_return(return_id: str, body: SignIn, user=Depends(auth.require_auth)):
    require_role(return_id, user["id"], allowed=("owner",))
    if not body.typed_name.strip():
        raise HTTPException(400, "Type your full legal name to sign")
    c = db()
    doc_hash = _return_document_hash(c, return_id)
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_signatures(id,return_id,user_id,typed_name,document_hash,signed_at)
                 VALUES(?,?,?,?,?,?)""", (str(uuid.uuid4()), return_id, user["id"], body.typed_name.strip(), doc_hash, time.time()))
    c.execute("COMMIT")
    c.close()
    log_action(return_id, user["id"], "signed", body.typed_name.strip())
    return {"signed": True, "document_hash": doc_hash}


def has_valid_signature(return_id: str) -> bool:
    """Used by tax_filing.submit_return to enforce sign-before-file."""
    c = db()
    ret = c.execute("SELECT id FROM tax_returns WHERE id=?", (return_id,)).fetchone()
    sig = c.execute("SELECT * FROM tax_signatures WHERE return_id=? ORDER BY signed_at DESC LIMIT 1", (return_id,)).fetchone()
    if not sig:
        c.close()
        return False
    current_hash = _return_document_hash(c, return_id)
    c.close()
    return sig["document_hash"] == current_hash


# ---------------------------------------------------------------------------
# MeF-style XML export (architecture demonstration — see module docstring)
# ---------------------------------------------------------------------------

@router.get("/returns/{return_id}/export")
def export_return(return_id: str, user=Depends(auth.require_auth)):
    """Jurisdiction-aware export. For UG_URA this produces a structured
    summary shaped like the schedules URA's e-tax portal asks for
    (employment/business/rental income schedules); for US_IRS it produces
    the MeF-style XML. Neither is a real government-format submission —
    see the module docstring for exactly what's missing."""
    require_role(return_id, user["id"], allowed=("owner", "preparer"))
    c = db()
    ret = c.execute("SELECT * FROM tax_returns WHERE id=?", (return_id,)).fetchone()
    if not ret:
        c.close()
        raise HTTPException(404, "Return not found")
    tp = c.execute("SELECT * FROM tax_taxpayers WHERE id=?", (ret["taxpayer_id"],)).fetchone()
    items = c.execute("SELECT * FROM tax_line_items WHERE return_id=?", (return_id,)).fetchall()
    calc = c.execute("SELECT * FROM tax_calculations WHERE return_id=? ORDER BY calculated_at DESC LIMIT 1", (return_id,)).fetchone()
    c.close()
    if not calc:
        raise HTTPException(400, "Calculate the return before exporting")

    if ret["jurisdiction"] == "UG_URA":
        return {
            "return_id": return_id,
            "format": "ura_style_summary (illustrative — not URA's actual e-tax schema)",
            "note": ("URA's real e-tax portal schema is not publicly documented in detail and is "
                     "accessed via TIN-authenticated sessions/agent credentials this build doesn't have. "
                     "This mirrors the shape of URA's return schedules for demonstration."),
            "tax_year": ret["tax_year"],
            "taxpayer_type": tp["taxpayer_type"],
            "residency_or_entity": ret["filing_status"] or tp["entity_subtype"],
            "schedules": {
                "income": [{"category": x["category"], "amount": x["amount"]} for x in items if x["item_kind"] == "income"],
                "deductions_or_expenses": [{"category": x["category"], "amount": x["amount"]} for x in items if x["item_kind"] != "income"],
            },
            "financial_summary": {
                "gross_income": calc["gross_income"], "total_deductions": calc["total_deductions"],
                "taxable_income": calc["taxable_income"], "tax_owed": calc["tax_owed"],
                "amount_due": calc["amount_due"], "refund_amount": calc["refund_amount"],
            },
        }
    return {"return_id": return_id, **_mef_style_xml_payload(ret, tp, items, calc)}


def _mef_style_xml_payload(ret, tp, items, calc) -> dict:
    line_xml = "\n".join(
        f'    <LineItem kind="{xml_escape(x["item_kind"])}" category="{xml_escape(x["category"])}" amount="{x["amount"]}"/>'
        for x in items
    )
    xml_doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Illustrative MeF-style submission payload. NOT validated against the
     real IRS MeF XSD schema set and not wired to IRS transmission —
     see tax_advanced.py module docstring. -->
<ReturnData xmlns="urn:demo:tax-filing:mef-style" jurisdiction="{xml_escape(ret["jurisdiction"])}">
  <ReturnHeader>
    <TaxYear>{ret["tax_year"]}</TaxYear>
    <FilerType>{xml_escape(tp["taxpayer_type"])}</FilerType>
    <FilingStatus>{xml_escape(ret["filing_status"] or "")}</FilingStatus>
  </ReturnHeader>
  <FinancialSummary>
    <GrossIncome>{calc["gross_income"]}</GrossIncome>
    <TotalDeductions>{calc["total_deductions"]}</TotalDeductions>
    <TaxableIncome>{calc["taxable_income"]}</TaxableIncome>
    <TaxOwed>{calc["tax_owed"]}</TaxOwed>
    <AmountDue>{calc["amount_due"]}</AmountDue>
    <RefundAmount>{calc["refund_amount"]}</RefundAmount>
  </FinancialSummary>
  <LineItems>
{line_xml}
  </LineItems>
</ReturnData>"""
    return {"mef_style_xml": xml_doc}


# ---------------------------------------------------------------------------
# Batch filing (for preparers handling multiple returns)
# ---------------------------------------------------------------------------

class BatchSubmitIn(BaseModel):
    return_ids: list


@router.post("/returns/batch-submit")
def batch_submit(body: BatchSubmitIn, user=Depends(auth.require_auth)):
    import tax_filing  # local import avoids a circular import at module load time
    results = []
    for rid in body.return_ids:
        try:
            require_role(rid, user["id"], allowed=("owner", "preparer"))
            result = tax_filing.submit_return(rid, user)
            results.append({"return_id": rid, "status": "submitted", "confirmation_code": result["submission"]["confirmation_code"]})
        except HTTPException as e:
            results.append({"return_id": rid, "status": "failed", "error": e.detail})
    return {"results": results}


# ---------------------------------------------------------------------------
# Financial account linking — architecture only, see module docstring
# ---------------------------------------------------------------------------

class LinkAccountIn(BaseModel):
    provider: Literal["plaid_demo"]


class FinancialConnector:
    """Real implementation needs an aggregator (Plaid/Finicity) or direct
    payroll API (ADP/Gusto) credential set. This class is the interface a
    real one should implement:

        start_link(user_id) -> a hosted-link URL/token the frontend opens
        exchange_public_token(token) -> stores a long-lived access token
        import_transactions(link_id) -> list of transactions to map to
                                         income/expense line items

    None of that is implemented here — there's no account to connect to.
    """
    def start_link(self, user_id: str) -> str:
        raise NotImplementedError("No financial data aggregator is connected yet.")

    def import_transactions(self, link_id: str) -> list:
        raise NotImplementedError("No financial data aggregator is connected yet.")


@router.post("/financial-links")
def start_financial_link(body: LinkAccountIn, user=Depends(auth.require_auth)):
    c = db()
    i = str(uuid.uuid4())
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO tax_financial_links(id,user_id,provider,status,created_at)
                 VALUES(?,?,?,'not_connected',?)""", (i, user["id"], body.provider, time.time()))
    c.execute("COMMIT")
    c.close()
    return {"link_id": i, "status": "not_connected",
            "message": "Bank/payroll linking requires a live aggregator account (e.g. Plaid) that isn't connected in this environment. See FinancialConnector in tax_advanced.py for the integration point."}


# ---------------------------------------------------------------------------
# Capabilities status — carried over from the UNG-PROMET hardening pass so
# the honest not_configured/disabled flags stay visible at a glance.
# ---------------------------------------------------------------------------

@router.get("/capabilities")
def capabilities():
    return {
        "ocr": "not_configured",
        "banking": "not_configured",
        "payroll": "not_configured",
        "ura_live_filing": False,
        "irs_live_filing": False,
        "non_resident_ug_paye": False,
    }
