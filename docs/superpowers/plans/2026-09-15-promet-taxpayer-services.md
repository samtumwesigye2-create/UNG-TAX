# PROMET Taxpayer Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a persistent, role-isolated taxpayer filing workflow connected end-to-end to PROMET Revenue Operations.

**Architecture:** Keep existing auth/MFA and Revenue Operations boundaries. Add focused taxpayer models/store/API modules backed by PostgreSQL, then wire the existing taxpayer UI to them and bridge submitted returns into staff review/status workflows.

**Tech Stack:** Python, FastAPI, PostgreSQL, existing HTML/JavaScript taxpayer portal, pytest, GitHub Actions, Railway.

**Spec:** `docs/superpowers/specs/2026-09-15-promet-taxpayer-services-design.md`

## Global Constraints
- Normal taxpayers never receive Revenue staff/admin privileges.
- Every taxpayer record is scoped to the authenticated owner.
- Server calculations are authoritative.
- Filed versions are immutable; amendments create linked versions.
- PostgreSQL is the production source of truth.
- Existing auth/MFA and Revenue Operations tests must remain green.
- No OTPs, reset codes, secrets or sensitive tax payloads are logged.

---

### Task 1: Taxpayer identity, profile and ownership boundary

**Files:**
- Create: `taxpayer_models.py`
- Create: `taxpayer_store.py`
- Create: `taxpayer_api.py`
- Modify: `main.py`
- Test: `tests/test_taxpayer_profile.py`
- Test: `tests/test_taxpayer_authorization.py`

**Interfaces:**
- Consumes: authenticated user/session from `auth.py`.
- Produces: owner-scoped taxpayer profile API and reusable taxpayer authorization dependency.

- [ ] Write failing tests for authenticated profile create/read/update, unauthenticated rejection, and cross-user isolation.
- [ ] Run tests and confirm RED for missing taxpayer API.
- [ ] Implement minimal profile models/store/API using existing DB conventions.
- [ ] Mount router in `main.py`.
- [ ] Run focused tests, then full suite.
- [ ] Commit Group 1 only after GREEN.

### Task 2: Return draft, calculation, documents, submission and history

**Files:**
- Modify: `taxpayer_models.py`
- Modify: `taxpayer_store.py`
- Modify: `taxpayer_api.py`
- Test: `tests/test_taxpayer_returns.py`
- Test: `tests/test_taxpayer_return_security.py`

**Interfaces:**
- Consumes: authenticated taxpayer ownership boundary from Task 1.
- Produces: create/update/calculate/submit/list/detail/amend endpoints and durable receipt references.

- [ ] Write failing tests for draft creation and owner-only access.
- [ ] Write failing tests proving server-calculated totals override untrusted client totals.
- [ ] Write failing tests for document metadata ownership and association.
- [ ] Write failing tests for submission immutability, durable receipt and persistence.
- [ ] Write failing tests for amendment version linkage.
- [ ] Run focused tests and confirm intended RED failures.
- [ ] Implement minimal schema/store/API to satisfy each test incrementally.
- [ ] Run focused tests and full suite.
- [ ] Commit Group 2 after GREEN.

### Task 3: Revenue Operations handoff and lifecycle synchronization

**Files:**
- Modify: `ops.py`
- Modify: `ops_store.py`
- Modify: `taxpayer_store.py`
- Modify: `taxpayer_api.py`
- Test: `tests/test_taxpayer_revenue_handoff.py`
- Test: `tests/test_taxpayer_status_sync.py`

**Interfaces:**
- Consumes: immutable submitted taxpayer returns from Task 2 and existing Revenue staff authorization.
- Produces: staff-visible submissions and taxpayer-visible operational status/events.

- [ ] Write failing integration test: submitted return appears to authorized Revenue staff.
- [ ] Write failing authorization test: taxpayer cannot invoke staff review/assessment actions.
- [ ] Write failing synchronization test: staff lifecycle change appears in owner's taxpayer history.
- [ ] Run tests and confirm RED.
- [ ] Implement the narrow handoff/event synchronization boundary without duplicating return ownership.
- [ ] Run focused tests and full suite.
- [ ] Commit integration after GREEN.

### Task 4: Taxpayer portal wiring

**Files:**
- Modify: `static/index.html` only through a safe complete-file update or focused render/injection module; never truncate the large static file.
- Prefer Create/Modify: focused taxpayer UI JS/module if existing serving structure permits.
- Modify: `main.py` if an injection/render boundary is used.
- Test: `tests/test_taxpayer_ui_flow.py`

**Interfaces:**
- Consumes: taxpayer APIs from Tasks 1-3.
- Produces: authenticated taxpayer profile, filing, submission, receipt, history and status UI.

- [ ] Write rendered/UI contract tests for profile, draft, calculation, documents, submit, receipt/history and amendment actions.
- [ ] Confirm RED before UI implementation.
- [ ] Wire UI to APIs while preserving current MFA flow.
- [ ] Verify no Revenue Operations controls render for taxpayer sessions.
- [ ] Run focused tests and full suite.
- [ ] Commit UI after GREEN.

### Task 5: End-to-end acceptance and production verification

**Files:**
- Test: `tests/test_taxpayer_end_to_end.py`
- Modify only files implicated by evidence from acceptance failures.

**Interfaces:**
- Consumes: complete taxpayer + Revenue workflow.
- Produces: verified acceptance evidence suitable for production deployment.

- [ ] Add automated end-to-end API acceptance covering taxpayer submission → persistence → Revenue visibility → staff status → taxpayer visibility.
- [ ] Run complete pytest suite and record exact pass/fail result.
- [ ] Verify GitHub Actions is green for the exact head commit.
- [ ] Deploy only after explicit deployment authorization if a deployment is not already covered by the user's standing instruction.
- [ ] Verify Railway deployment status and `/health`.
- [ ] Perform live user acceptance without exposing credentials or MFA codes.
- [ ] Report completion only with fresh test, CI, deployment and live-flow evidence.