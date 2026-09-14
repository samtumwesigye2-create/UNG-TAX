# URA-PROMET Operational Workflows Design

## Goal
Turn the existing URA-PROMET Taxpayer, Revenue Staff, and Revenue Admin dashboard cards into real operational workflows backed by persistent data, role-aware APIs, approvals, and audit logging.

## Current Baseline
URA-PROMET already has three roles (`taxpayer`, `revenue_staff`, `revenue_admin`), MFA/session handling, tax filing logic, advanced tax calculations, and three role-specific portal shells. The new work extends that baseline rather than replacing it.

## Authority Model

### Taxpayer
- Create and manage their own filings and supporting information.
- View their own liabilities, notices, filing status, and reports.
- Cannot access staff or administrative records.

### Revenue Staff
Revenue Staff are terminal managers with broad operational authority. They can:
- Search and open taxpayer records.
- Edit taxpayer profile/account data within their assigned operational scope.
- Correct filing details and manage return review state.
- Create and update assessments, penalties, interest, liabilities, payment allocations, installment plans, and account adjustments.
- Update compliance status and operational flags.
- Prepare and issue notices.
- Create, assign, update, suspend, reopen, void, reverse, and archive operational records.
- Work cases and audits.
- Generate operational reports.

Revenue Staff cannot:
- Permanently delete taxpayer, filing, assessment, payment, notice, or case records.
- Manage staff accounts, RBAC policy, or global system settings.
- Finalize high-risk write-offs, refunds, or exceptional overrides that exceed configured thresholds.

### Revenue Admin
Revenue Admin has all Revenue Staff capabilities plus:
- Staff account management.
- Role and permission management.
- System settings and threshold configuration.
- Approval/rejection of high-risk write-offs, refunds, and exceptional overrides.
- Permanent deletion where policy allows it.
- Full audit-log review and governance.

## Operational Modules

### 1. Taxpayer Management
Functions:
- Search by taxpayer name, email, TIN, account ID, or status.
- Open a taxpayer detail workspace.
- Edit contact/profile fields and taxpayer status.
- Suspend/reactivate an account.
- Add operational notes.
- View filings, assessments, liabilities, notices, cases, and audit history for that taxpayer.

State-changing actions must require an authenticated Revenue Staff or Revenue Admin session and create an audit event.

### 2. Return Review
Functions:
- Review submitted returns and validation state.
- Open supporting-document metadata.
- Correct reviewable filing fields without changing immutable filing identity fields.
- Set return state to `draft`, `submitted`, `under_review`, `needs_correction`, `accepted`, `rejected`, `voided`, or `archived`.
- Record reviewer notes and reasons for rejection/voiding.

Revenue Staff can manage normal review states. Permanent deletion is Revenue Admin only.

### 3. Assessments
Functions:
- Create assessments against a taxpayer/return.
- Add tax principal, penalty, interest, and adjustment lines.
- Recalculate totals.
- Set status: `draft`, `issued`, `disputed`, `adjusted`, `satisfied`, `voided`, or `archived`.
- Record an officer reason for adjustments.

Large reductions, refunds, write-offs, or overrides over configured thresholds enter `pending_admin_approval` and cannot take effect until Revenue Admin approves them.

### 4. Compliance
Functions:
- Track filing compliance, payment compliance, and operational risk flags.
- Record compliance notes and next-action dates.
- Mark cases for follow-up.
- Show open obligations and overdue items.

Compliance changes are operational state, not destructive edits, and are fully auditable.

### 5. Payments & Liabilities
Functions:
- View open liabilities and assessed balances.
- Record payment allocations against liabilities.
- Create installment arrangements.
- Reverse or reallocate payments with reason codes.
- Adjust account balances through controlled adjustment entries rather than direct balance mutation.

High-risk refunds/write-offs enter the Revenue Admin approval queue.

### 6. Notices
Functions:
- Create notice drafts from templates.
- Address a notice to a taxpayer and link it to a return, assessment, liability, or case.
- Set state: `draft`, `approved`, `issued`, `cancelled`, or `archived`.
- Record issuance timestamp and officer.
- Preserve immutable issued notice content after issuance; corrections create a replacement notice rather than silently changing the original.

### 7. Cases & Audits
Functions:
- Create and assign cases.
- Link taxpayers, returns, assessments, payments, notices, and notes.
- Set priority and case status.
- Add timeline events and evidence metadata.
- Close, reopen, suspend, archive, or void cases.

### 8. Revenue Reports
Functions:
- Operational counts and totals for filings, assessments, liabilities, payments, compliance, and cases.
- Filter by date range and status.
- Revenue Staff sees operational scope; Revenue Admin can view system-wide summaries.

### 9. Staff Management
Revenue Admin only.
Functions:
- List registered revenue users.
- Promote/demote between `revenue_staff` and `revenue_admin` through explicit admin action.
- Suspend/reactivate staff access.
- Record assignment metadata and notes.

Public users can never self-register into a revenue role.

### 10. Role & Permission Management
Revenue Admin only.
Initial RBAC remains role-based rather than building a generic policy engine. Permissions are explicit capabilities checked server-side, including taxpayer editing, assessment management, payment management, notice issuance, case management, approvals, staff management, settings, hard delete, and audit access.

### 11. System Settings
Revenue Admin only.
Functions:
- Configure high-risk approval thresholds.
- Configure operational feature switches relevant to workflows.
- Configure non-secret business rules.

Secrets and credentials stay in environment configuration and are never editable from this UI.

### 12. Audit Log
Every state-changing action must record:
- actor user ID and role
- action name
- entity type and entity ID
- taxpayer ID when applicable
- before-state summary
- after-state summary
- reason/note when supplied
- timestamp
- request correlation ID

Audit records are append-only from normal application APIs. Revenue Staff may see audit history relevant to records they manage; Revenue Admin can review the complete log.

## Data Model Strategy
Add focused persistence tables for operational workflows rather than overloading existing filing tables. Recommended logical tables:
- `taxpayer_profiles`
- `return_reviews`
- `assessments`
- `assessment_lines`
- `liabilities`
- `payment_allocations`
- `installment_plans`
- `compliance_records`
- `notices`
- `cases`
- `case_events`
- `approval_requests`
- `staff_assignments`
- `system_settings`
- `audit_log`

Use existing PostgreSQL support when `DATABASE_URL` is present, while retaining the current local fallback behavior for tests/development where required by the existing codebase.

## API Design
Create a dedicated operational router instead of growing `main.py` or `tax_filing.py` further. Suggested prefix: `/ops`.

Server-side authorization is mandatory. UI visibility is never considered an access-control boundary.

Representative endpoints:
- `GET /ops/taxpayers`
- `GET /ops/taxpayers/{id}`
- `PATCH /ops/taxpayers/{id}`
- `GET /ops/returns`
- `PATCH /ops/returns/{id}/review`
- `POST /ops/assessments`
- `PATCH /ops/assessments/{id}`
- `GET /ops/liabilities`
- `POST /ops/payments/allocations`
- `POST /ops/notices`
- `POST /ops/cases`
- `PATCH /ops/cases/{id}`
- `GET /ops/reports/summary`
- `GET /ops/admin/staff`
- `PATCH /ops/admin/staff/{id}`
- `GET /ops/admin/approvals`
- `POST /ops/admin/approvals/{id}/approve`
- `POST /ops/admin/approvals/{id}/reject`
- `GET /ops/admin/settings`
- `PATCH /ops/admin/settings`
- `GET /ops/admin/audit`

## UI Design
Each dashboard card becomes a real link/button that opens a dedicated responsive workspace. Workspaces use consistent patterns:
- search/filter header
- data table or card list
- detail drawer/page
- edit form where authorized
- explicit save/confirm action
- visible status badges
- error/success feedback
- reason field for sensitive state changes

The existing mobile-friendly visual language remains unchanged unless a workflow requires additional controls.

## Approval Queue
High-risk actions create an `approval_request` containing:
- requested action
- officer
- entity
- original values
- proposed values
- reason
- requested timestamp
- status (`pending`, `approved`, `rejected`, `cancelled`)

Revenue Admin must see a before/after comparison and explicitly approve or reject. The operational mutation is applied only on approval. The decision becomes immutable audit history.

## Deletion Policy
- Revenue Staff: no hard delete.
- Revenue Staff can void, reverse, suspend, reopen, and archive.
- Revenue Admin: hard delete only where allowed by entity policy, with mandatory reason and audit event.
- Issued notices, approval decisions, and audit records are not silently editable; corrections use replacement/superseding records.

## Security
- All operational endpoints require MFA-authenticated sessions.
- Role/capability checks occur on the server.
- Revenue Admin endpoints reject Revenue Staff and Taxpayer roles.
- Sensitive changes require reasons where applicable.
- No secrets are exposed to or modified by system-settings UI.
- Live tax-authority transmission remains disabled until official credentials and schemas pass acceptance testing.

## Error Handling
- `401` for missing/expired authentication.
- `403` for authenticated users without capability.
- `404` for unknown entities.
- `409` for invalid state transitions or conflicting operations.
- `422` for invalid field data.
- High-risk actions return a created `pending_admin_approval` request instead of pretending the change is complete.

## Testing
Use TDD for each workflow.
Required test groups:
- role/capability authorization tests
- taxpayer edit tests
- return state-transition tests
- assessment calculation/state tests
- payment allocation and reversal tests
- compliance update tests
- notice issuance immutability tests
- case lifecycle tests
- admin approval queue tests
- staff/RBAC/settings tests
- audit-event tests
- UI route/button integration tests
- regression tests for existing tax calculations and filing APIs

No workflow is considered complete until its API, role checks, persistence, UI path, and tests all pass.

## Delivery Order
Implement in two production blocks.

### Block 1 — Core Revenue Operations
1. shared operational persistence + audit layer
2. taxpayer management
3. return review
4. assessments
5. compliance
6. payments & liabilities
7. notices
8. cases & audits
9. operational reports
10. wire Revenue Staff and Revenue Admin dashboard buttons

### Block 2 — Revenue Administration
1. approval queue
2. staff management
3. explicit capability/RBAC layer
4. system settings
5. full audit-log workspace
6. wire Revenue Admin-only buttons

Each block must pass CI and Railway deployment verification before being considered production-ready.
