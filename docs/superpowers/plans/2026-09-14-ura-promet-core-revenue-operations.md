# URA-PROMET Core Revenue Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Revenue Staff and Revenue Admin operational cards into functioning taxpayer, return-review, assessment, compliance, payment/liability, notice, case/audit, and reporting workflows with persistence, server-side authorization, and append-only audit events.

**Architecture:** Add a dedicated `/ops` FastAPI router and focused operational persistence module instead of growing `main.py` or `tax_filing.py`. Reuse existing MFA authentication and tax filing/calculation code, require `revenue_staff` or `revenue_admin` on operational mutations, and write an audit event for every state change. UI workspaces remain lightweight responsive HTML/JS clients that call the new APIs.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite development/test fallback, PostgreSQL via existing `psycopg` support when `DATABASE_URL` is present, vanilla HTML/CSS/JavaScript, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-14-ura-promet-operational-workflows-design.md`

## Global Constraints

- Product name remains `URA-PROMET`; repository/service legacy identity may remain `UNG-TAX`.
- Existing roles remain `taxpayer`, `revenue_staff`, and `revenue_admin`.
- Revenue Staff are terminal managers with broad operational edit authority but no hard-delete authority.
- Revenue Admin inherits Revenue Staff operational capabilities.
- All operational endpoints require an MFA-verified authenticated session.
- UI visibility is never an authorization boundary; capability checks are server-side.
- Every state-changing operation records an append-only audit event.
- Issued notices and audit events are never silently mutated.
- Live external tax-authority transmission remains disabled.
- Existing filing and tax-calculation regression tests must remain green.

---

## File Structure

- Create `ops_store.py` — operational schema initialization and database helpers for SQLite/PostgreSQL.
- Create `ops_auth.py` — reusable server-side role/capability guards for `/ops` routes.
- Create `ops_audit.py` — append-only audit writer and record-scoped audit reader.
- Create `ops_models.py` — Pydantic request/response models and workflow state constants.
- Create `ops.py` — `/ops` router composing taxpayer, return, assessment, compliance, payment, notice, case, and reporting handlers.
- Modify `main.py` — include `ops.router` and serve operational workspace pages.
- Create `static/ops-workspace.html` — common Revenue Staff/Admin operations shell.
- Create `static/ops-workspace.js` — API client, module routing, forms, tables, status actions, feedback.
- Modify `static/revenue-staff.html` and `static/revenue.html` — turn cards into actual links to operational modules.
- Create focused tests under `tests/test_ops_*.py`.

---

### Task 1: Operational Authorization, Persistence, and Audit Foundation

**Files:**
- Create: `ops_auth.py`
- Create: `ops_store.py`
- Create: `ops_audit.py`
- Create: `ops_models.py`
- Test: `tests/test_ops_foundation.py`

**Interfaces:**
- Consumes: `auth.require_auth()` returning a user dict containing `id`, `email`, and `role`.
- Produces: `require_revenue_user(user) -> dict`, `require_revenue_admin(user) -> dict`, `get_ops_db()`, `init_ops_schema()`, `write_audit_event(...) -> str`, `list_audit_events(...) -> list[dict]`.

- [ ] **Step 1: Write failing authorization and audit tests**

```python
from fastapi import HTTPException
from ops_auth import require_revenue_user, require_revenue_admin


def test_revenue_staff_is_operational_manager():
    user = {"id": "u1", "role": "revenue_staff"}
    assert require_revenue_user(user)["id"] == "u1"


def test_taxpayer_cannot_enter_ops():
    try:
        require_revenue_user({"id": "u2", "role": "taxpayer"})
        assert False
    except HTTPException as exc:
        assert exc.status_code == 403


def test_only_admin_passes_admin_guard():
    try:
        require_revenue_admin({"id": "u3", "role": "revenue_staff"})
        assert False
    except HTTPException as exc:
        assert exc.status_code == 403
```

Add an audit test that calls `write_audit_event(actor_id="u1", actor_role="revenue_staff", action="taxpayer.update", entity_type="taxpayer", entity_id="t1", taxpayer_id="t1", before={"status":"active"}, after={"status":"suspended"}, reason="identity review", correlation_id="c1")` and asserts the returned event exists in `list_audit_events(entity_type="taxpayer", entity_id="t1")`.

- [ ] **Step 2: Run the foundation tests and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_foundation.py`

Expected: import failures because `ops_auth`, `ops_store`, and `ops_audit` do not yet exist.

- [ ] **Step 3: Implement minimal role guards and operational schema**

`ops_auth.py` must implement:

```python
from fastapi import HTTPException

REVENUE_ROLES = {"revenue_staff", "revenue_admin"}

def require_revenue_user(user: dict) -> dict:
    if user.get("role") not in REVENUE_ROLES:
        raise HTTPException(403, "Revenue role required")
    return user

def require_revenue_admin(user: dict) -> dict:
    if user.get("role") != "revenue_admin":
        raise HTTPException(403, "Revenue Admin role required")
    return user
```

`ops_store.py` must initialize these Block-1 tables: `taxpayer_profiles`, `return_reviews`, `assessments`, `assessment_lines`, `liabilities`, `payment_allocations`, `installment_plans`, `compliance_records`, `notices`, `cases`, `case_events`, and `audit_log`. Use SQLite for tests/local fallback and `DATABASE_URL` for PostgreSQL when configured.

`ops_audit.py` must only INSERT audit rows; it must expose no update/delete function.

- [ ] **Step 4: Run foundation tests and full regression suite**

Run: `PYTHONPATH=. pytest -q tests/test_ops_foundation.py && PYTHONPATH=. pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ops_auth.py ops_store.py ops_audit.py ops_models.py tests/test_ops_foundation.py
git commit -m "feat: add revenue operations persistence and audit foundation"
```

---

### Task 2: Taxpayer Management API

**Files:**
- Create: `ops.py`
- Test: `tests/test_ops_taxpayers.py`

**Interfaces:**
- Consumes: `require_revenue_user`, `get_ops_db`, `write_audit_event`.
- Produces: `GET /ops/taxpayers`, `GET /ops/taxpayers/{taxpayer_id}`, `PATCH /ops/taxpayers/{taxpayer_id}`, `POST /ops/taxpayers/{taxpayer_id}/notes`.

- [ ] **Step 1: Write failing API tests**

Create authenticated test sessions for one taxpayer and one revenue staff user. Assert:
- taxpayer receives `403` from `GET /ops/taxpayers`;
- staff can search by name/email/TIN/account/status;
- staff can update contact fields and status;
- update creates an audit event containing before/after summaries;
- unknown taxpayer returns `404`.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_taxpayers.py`

Expected: routes return `404` because `/ops` router is not yet mounted.

- [ ] **Step 3: Implement taxpayer endpoints**

Use a router `APIRouter(prefix="/ops", tags=["revenue-operations"])`. `PATCH /taxpayers/{id}` must accept only `name`, `email`, `phone`, `address`, `status`, and operational metadata fields defined in `ops_models.py`. Hard delete must not exist in Block 1.

Every successful mutation must call `write_audit_event(action="taxpayer.update", ...)`.

- [ ] **Step 4: Mount router in `main.py` and verify tests**

Add `import ops` and `app.include_router(ops.router)`.

Run: `PYTHONPATH=. pytest -q tests/test_ops_taxpayers.py && PYTHONPATH=. pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ops.py main.py tests/test_ops_taxpayers.py
git commit -m "feat: add taxpayer management operations"
```

---

### Task 3: Return Review Workflow

**Files:**
- Modify: `ops.py`
- Modify: `ops_models.py`
- Test: `tests/test_ops_returns.py`

**Interfaces:**
- Produces: `GET /ops/returns`, `GET /ops/returns/{return_id}`, `PATCH /ops/returns/{return_id}/review`.
- Valid states: `draft`, `submitted`, `under_review`, `needs_correction`, `accepted`, `rejected`, `voided`, `archived`.

- [ ] **Step 1: Write failing state-transition tests**

Tests must verify staff can move `submitted -> under_review -> accepted`, rejection requires a reason, `voided` requires a reason, invalid transitions return `409`, and each transition writes an audit row.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_returns.py`

Expected: missing route/state-machine failures.

- [ ] **Step 3: Implement explicit transition map**

Use this transition policy:

```python
RETURN_TRANSITIONS = {
    "draft": {"submitted", "archived"},
    "submitted": {"under_review", "voided", "archived"},
    "under_review": {"needs_correction", "accepted", "rejected", "voided", "archived"},
    "needs_correction": {"submitted", "voided", "archived"},
    "accepted": {"archived"},
    "rejected": {"archived"},
    "voided": {"archived"},
    "archived": set(),
}
```

Do not allow operational review to modify immutable filing identity fields.

- [ ] **Step 4: Run focused and regression tests**

Run: `PYTHONPATH=. pytest -q tests/test_ops_returns.py && PYTHONPATH=. pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ops.py ops_models.py tests/test_ops_returns.py
git commit -m "feat: add return review workflow"
```

---

### Task 4: Assessments and Compliance

**Files:**
- Modify: `ops.py`
- Modify: `ops_models.py`
- Test: `tests/test_ops_assessments.py`
- Test: `tests/test_ops_compliance.py`

**Interfaces:**
- Produces: `POST /ops/assessments`, `GET /ops/assessments`, `PATCH /ops/assessments/{id}`, `GET /ops/compliance/{taxpayer_id}`, `PATCH /ops/compliance/{taxpayer_id}`.

- [ ] **Step 1: Write failing assessment tests**

Verify principal + penalty + interest + adjustments recompute totals server-side; staff cannot send an arbitrary stored total; adjustment reasons are mandatory; states are `draft`, `issued`, `disputed`, `adjusted`, `satisfied`, `voided`, `archived`; mutations write audit events.

- [ ] **Step 2: Write failing compliance tests**

Verify staff can update filing compliance, payment compliance, risk flags, notes, and next-action date; taxpayer cannot access the endpoint; audit events are written.

- [ ] **Step 3: Run both suites and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_assessments.py tests/test_ops_compliance.py`

Expected: route failures.

- [ ] **Step 4: Implement assessment totals and compliance state**

Assessment total formula is exactly:

```python
total = principal + penalty + interest + sum(adjustment_lines)
```

Persist assessment lines separately. Compliance is one current operational record per taxpayer with timestamped audit history.

- [ ] **Step 5: Verify and commit**

Run: `PYTHONPATH=. pytest -q tests/test_ops_assessments.py tests/test_ops_compliance.py && PYTHONPATH=. pytest -q`

```bash
git add ops.py ops_models.py tests/test_ops_assessments.py tests/test_ops_compliance.py
git commit -m "feat: add assessments and compliance operations"
```

---

### Task 5: Payments, Liabilities, and Installments

**Files:**
- Modify: `ops.py`
- Modify: `ops_models.py`
- Test: `tests/test_ops_payments.py`

**Interfaces:**
- Produces: `GET /ops/liabilities`, `POST /ops/payments/allocations`, `POST /ops/payments/{allocation_id}/reverse`, `POST /ops/installments`, `PATCH /ops/installments/{id}`.

- [ ] **Step 1: Write failing accounting-state tests**

Verify allocation cannot exceed open liability balance, reversal requires a reason, reversal creates a new reversing entry rather than deleting the original allocation, installments preserve total scheduled amount, and all mutations are audited.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_payments.py`

Expected: missing route failures.

- [ ] **Step 3: Implement append-style payment accounting**

Never mutate historical payment allocation amounts. A reversal creates a linked allocation with negative amount and `reversal_of=<original_id>`. Liability open balance is derived from assessment amount plus controlled adjustments minus net allocations.

- [ ] **Step 4: Verify and commit**

Run: `PYTHONPATH=. pytest -q tests/test_ops_payments.py && PYTHONPATH=. pytest -q`

```bash
git add ops.py ops_models.py tests/test_ops_payments.py
git commit -m "feat: add liabilities payments and installment workflows"
```

---

### Task 6: Notices and Cases/Audits

**Files:**
- Modify: `ops.py`
- Modify: `ops_models.py`
- Test: `tests/test_ops_notices.py`
- Test: `tests/test_ops_cases.py`

**Interfaces:**
- Produces: `POST /ops/notices`, `GET /ops/notices`, `PATCH /ops/notices/{id}`, `POST /ops/cases`, `GET /ops/cases`, `PATCH /ops/cases/{id}`, `POST /ops/cases/{id}/events`.

- [ ] **Step 1: Write failing notice immutability tests**

Verify draft notice content can change, `issued` notice receives `issued_at` and `issued_by`, issued content cannot be edited, cancellation/archive changes status without overwriting issued content, and replacement notice can reference `supersedes_notice_id`.

- [ ] **Step 2: Write failing case lifecycle tests**

Verify create/assign/update priority, `open -> suspended -> reopened`, close, void, archive, and timeline event creation. Every change must audit actor and reason.

- [ ] **Step 3: Run and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_notices.py tests/test_ops_cases.py`

Expected: route failures.

- [ ] **Step 4: Implement notice and case rules**

Issued notices are immutable except status transitions that do not rewrite issued content. Case history is append-only in `case_events`; case summary fields may change through valid transitions.

- [ ] **Step 5: Verify and commit**

Run: `PYTHONPATH=. pytest -q tests/test_ops_notices.py tests/test_ops_cases.py && PYTHONPATH=. pytest -q`

```bash
git add ops.py ops_models.py tests/test_ops_notices.py tests/test_ops_cases.py
git commit -m "feat: add notices and case management workflows"
```

---

### Task 7: Operational Reports API

**Files:**
- Modify: `ops.py`
- Test: `tests/test_ops_reports.py`

**Interfaces:**
- Produces: `GET /ops/reports/summary?start=YYYY-MM-DD&end=YYYY-MM-DD&status=...`.

- [ ] **Step 1: Write failing aggregate tests**

Seed filings, assessments, liabilities, payments, compliance records, and cases. Assert response returns counts/totals for each category and honors date/status filters.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_reports.py`

Expected: `404`.

- [ ] **Step 3: Implement server-side aggregation**

Return a stable JSON shape:

```json
{
  "filings": {"count": 0},
  "assessments": {"count": 0, "total": 0},
  "liabilities": {"open_count": 0, "open_total": 0},
  "payments": {"net_allocated": 0},
  "compliance": {"follow_up_count": 0},
  "cases": {"open_count": 0}
}
```

- [ ] **Step 4: Verify and commit**

Run: `PYTHONPATH=. pytest -q tests/test_ops_reports.py && PYTHONPATH=. pytest -q`

```bash
git add ops.py tests/test_ops_reports.py
git commit -m "feat: add operational revenue reports"
```

---

### Task 8: Revenue Operations Workspace UI and Button Wiring

**Files:**
- Create: `static/ops-workspace.html`
- Create: `static/ops-workspace.js`
- Modify: `static/revenue-staff.html`
- Modify: `static/revenue.html`
- Modify: `main.py`
- Test: `tests/test_ops_ui.py`

**Interfaces:**
- Consumes: all Block-1 `/ops` endpoints.
- Produces routes: `/ops-ui?module=taxpayers`, `returns`, `assessments`, `compliance`, `payments`, `notices`, `cases`, `reports`.

- [ ] **Step 1: Write failing UI integration tests**

Assert Revenue Staff and Revenue Admin cards contain real anchor URLs for each module, `/ops-ui` returns the shared workspace, and workspace HTML contains search/filter controls, status feedback region, detail pane, save button, reason field, and module container.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q tests/test_ops_ui.py`

Expected: links/routes missing.

- [ ] **Step 3: Implement responsive operational shell**

`ops-workspace.js` must:
- read `module` from query string;
- load the matching endpoint;
- render list/table cards on mobile;
- open record detail/edit form;
- send bearer token from the authenticated session storage used by the existing filing UI;
- require a reason input for void/reverse/reject/suspend actions;
- show explicit success/error messages;
- never expose hard-delete controls to Revenue Staff.

- [ ] **Step 4: Wire dashboard cards**

Revenue Staff and Admin cards must link to the matching `/ops-ui?module=...` URL instead of displaying inert status badges.

- [ ] **Step 5: Verify and commit**

Run: `PYTHONPATH=. pytest -q tests/test_ops_ui.py && PYTHONPATH=. pytest -q`

```bash
git add static/ops-workspace.html static/ops-workspace.js static/revenue-staff.html static/revenue.html main.py tests/test_ops_ui.py
git commit -m "feat: activate revenue operations dashboard workspaces"
```

---

### Task 9: Block-1 Acceptance and Production Gate

**Files:**
- Modify if necessary: `README.md`
- Test: all tests

**Interfaces:**
- Consumes: completed Block-1 application.
- Produces: a CI-green commit ready for Railway deployment.

- [ ] **Step 1: Run the complete suite**

Run: `PYTHONPATH=. pytest -q`

Expected: all existing and new tests PASS.

- [ ] **Step 2: Verify authorization matrix explicitly**

Run focused tests proving:
- taxpayer receives `403` on operational APIs;
- revenue_staff can perform normal operational edits;
- revenue_admin can perform the same operational edits;
- no Block-1 hard-delete endpoint exists;
- every mutation produces an audit event.

- [ ] **Step 3: Verify UI routes**

Use FastAPI TestClient to GET `/revenue-staff`, `/revenue`, `/ops-ui?module=taxpayers`, `/ops-ui?module=returns`, `/ops-ui?module=assessments`, `/ops-ui?module=compliance`, `/ops-ui?module=payments`, `/ops-ui?module=notices`, `/ops-ui?module=cases`, and `/ops-ui?module=reports`; expect `200` for the pages.

- [ ] **Step 4: Update README operational status**

Document the activated Block-1 modules and explicitly state that high-risk approval queue, staff management, RBAC/settings, hard-delete governance, and full audit-log admin workspace are Block 2.

- [ ] **Step 5: Commit**

```bash
git add README.md tests
git commit -m "test: complete core revenue operations acceptance"
```

- [ ] **Step 6: Deployment verification after explicit deploy approval**

After merge/deploy, verify Railway reports `SUCCESS`, `/health` returns `200`, and HTTP logs show successful requests to `/revenue-staff`, `/revenue`, and `/ops-ui` before calling Block 1 production-ready.

---

## Block 1 Completion Criteria

Block 1 is complete only when:
- every Revenue Staff operational card opens a working module;
- Revenue Admin can use all the same operational modules;
- normal create/edit/state-change workflows persist across requests;
- Revenue Staff has no hard-delete path;
- taxpayer access is rejected server-side;
- all mutations are audited;
- existing tax calculation/filing tests remain green;
- CI passes;
- Railway deployment is verified successful.

Block 2 will be planned separately for the high-risk approval queue, staff management, explicit capability/RBAC administration, system settings, Revenue Admin hard-delete governance, and full audit-log workspace.