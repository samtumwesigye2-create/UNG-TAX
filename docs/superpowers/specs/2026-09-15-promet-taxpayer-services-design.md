# PROMET Taxpayer Services Design

## Goal
Build a persistent, non-admin taxpayer workflow that connects authenticated taxpayers to PROMET Revenue Operations without granting staff privileges.

## Architecture
The existing authentication/MFA subsystem remains authoritative for identity and sessions. A dedicated taxpayer-services API owns taxpayer profiles, return drafts, calculations, supporting-document metadata, submission receipts, filing history and amendments. PostgreSQL is the source of truth. Submitted returns are exposed to the existing Revenue Operations layer for staff review and status transitions.

## Authorization
Taxpayer endpoints require an authenticated session and scope every read/write to the authenticated user. Taxpayer accounts cannot call Revenue Operations staff actions. Revenue staff/admin continue using existing role checks. Staff actions may change a return's operational status, but never ownership.

## Workflow
1. Taxpayer signs up/signs in and completes MFA.
2. Taxpayer creates/updates profile and TIN metadata.
3. Taxpayer creates a return draft for a tax type and period.
4. Server calculates totals from validated return inputs; client-provided totals are not authoritative.
5. Taxpayer associates supporting-document metadata with the draft.
6. Taxpayer submits the return. Submission freezes the filed version and generates a durable receipt/reference.
7. Taxpayer can list/view only their returns and statuses after logout/login.
8. Submitted return appears in Revenue Operations for authorized staff.
9. Staff review/assessment/payment/notices update operational state visible to the owning taxpayer.
10. Amendments create a new version linked to the original submission rather than silently overwriting filed data.

## Persistence
Use PostgreSQL through the repository's existing database conventions. Core records: taxpayer_profiles, taxpayer_returns, taxpayer_return_documents, and taxpayer_return_events. Returns include owner user id, tax type, period, payload, server-calculated amounts, lifecycle status, version, submission timestamp and receipt reference. Events provide an auditable lifecycle trail.

## API Boundary
Taxpayer API provides profile get/update, return create/update/calculate/submit, return list/detail, document metadata attach/list, and amendment creation. Revenue Operations receives submitted returns through a controlled integration boundary and existing staff authorization.

## UI
The existing taxpayer portal remains the public interface. It consumes the taxpayer API after MFA, presents draft/submission/history/status functions, and never renders staff controls for taxpayer sessions.

## Acceptance Criteria
A normal taxpayer can complete MFA, create and submit a return, sign out/in and still see the persisted submission and receipt. The submitted return appears in Revenue Admin. An authorized staff status action is then visible to the taxpayer. Cross-taxpayer reads/writes and taxpayer access to staff actions are rejected.

## Delivery Groups
Group 1: identity/profile and taxpayer authorization boundary.
Group 2: return draft/calculation/documents/submission/history/amendment persistence.
Group 3: Revenue Operations handoff, status synchronization, UI wiring and end-to-end acceptance.

## Testing
Use TDD for every behavior. Add API tests for ownership isolation, persistence and lifecycle transitions, integration tests for staff handoff, and rendered/UI contract tests for the taxpayer portal. Existing authentication and Revenue Operations tests must remain green.