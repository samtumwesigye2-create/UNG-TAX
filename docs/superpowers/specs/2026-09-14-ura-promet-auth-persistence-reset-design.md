# URA-PROMET Authentication Persistence and Password Reset Design

## Purpose

Make URA-PROMET authentication durable across Railway restarts/deployments and make password reset available consistently from taxpayer, Revenue Staff, and Revenue Admin sign-in flows.

## Problem Statement

Production currently uses SQLite (`tax_filing.db`) for authentication users, sessions, MFA OTPs, and password reset records. Railway has no persistent volume mounted for the service, so local authentication state can be lost during redeployments or restarts. The service already exposes `DATABASE_URL`, so PostgreSQL is available and should become the authoritative authentication store.

The password reset backend already exists, but the browser UI is inconsistent: the taxpayer filing login has a reset flow, while the Revenue Operations sign-in does not. The reset endpoint intentionally returns a generic success message for unknown accounts to prevent account enumeration, which means a user can see “code sent” even when no matching account exists.

Revenue-role assignment is also incomplete in production because `PROMET_ADMIN_EMAILS` and `PROMET_STAFF_EMAILS` are not currently configured.

## Scope

This design covers:

- PostgreSQL-backed authentication persistence using the existing `DATABASE_URL`.
- Shared storage for users, sessions, email OTPs, and password reset records.
- A safe migration path from the current SQLite auth schema.
- A consistent Forgot Password flow in all user-facing login surfaces.
- Preservation of anti-enumeration behavior.
- Revenue-role configuration through environment variables.
- End-to-end verification across redeploy/restart boundaries.

This design does not change the tax filing data model, operational `/ops` authorization model, or external tax-authority integrations.

## Architecture

### 1. Shared authentication data layer

Introduce an authentication storage abstraction used by `auth.py` and `password_reset.py`.

The store chooses PostgreSQL when `DATABASE_URL` starts with `postgres://` or `postgresql://`. SQLite remains available only as a local-development fallback when no PostgreSQL URL is configured.

The auth store owns connection creation, placeholder adaptation, transaction handling, and schema initialization. Authentication code should not contain database-specific SQL branching.

### 2. PostgreSQL authentication schema

The authoritative production tables are:

- `auth_users`
- `auth_sessions`
- `auth_email_otp`
- `auth_password_resets`

The logical columns and behavior stay compatible with the existing SQLite schema so application behavior does not change during the migration.

### 3. Migration strategy

Production must not silently discard existing auth records.

On startup, the application initializes the PostgreSQL schema. A one-time migration helper may copy existing SQLite auth records when an old SQLite file is present and the destination rows do not already exist. Migration must be idempotent and must not overwrite newer PostgreSQL records.

If production SQLite data is already gone, the system must report that there is nothing to migrate rather than manufacturing accounts. A new account or admin account must then be created explicitly.

### 4. Shared password reset flow

The backend contract remains:

- `POST /auth/password/request`
- `POST /auth/password/confirm`

The UI contract becomes identical across taxpayer and revenue login surfaces:

1. User taps **Forgot password?**
2. User enters email.
3. App requests a reset code.
4. UI always shows the generic anti-enumeration message.
5. If the backend returns a `reset_id`, the UI advances to code/new-password entry.
6. User enters 6-digit code and a new password of at least 10 characters.
7. App confirms the reset.
8. Existing sessions are invalidated.
9. User is returned to sign-in.

Revenue Operations must expose this flow directly on its own sign-in panel rather than requiring users to visit another portal.

### 5. Email delivery

SMTP remains the delivery mechanism using the current `PROMET_SMTP_*` variables.

The application must distinguish internally between:

- account not found: return generic success without sending email;
- SMTP not configured: return 503;
- SMTP delivery failure: return 503 and delete the pending reset record;
- successful account match and email delivery: return generic success plus `reset_id`.

No UI should reveal whether an email address exists in the system.

### 6. Revenue role configuration

Revenue Admin and Revenue Staff roles continue to be assigned from:

- `PROMET_ADMIN_EMAILS`
- `PROMET_STAFF_EMAILS`

Production must configure these variables before Revenue Admin/Staff acceptance testing.

The exact admin/staff email values are an operational configuration decision and will be set only after explicit confirmation of the intended addresses.

## Data Flow

### Registration

Browser -> `/auth/register` -> auth store -> PostgreSQL `auth_users`.

### Login and MFA

Browser -> `/auth/login` -> auth store reads `auth_users` -> password verification -> `auth_sessions` -> email OTP stored in `auth_email_otp` -> SMTP delivery -> `/auth/mfa/verify` -> session marked MFA-verified.

### Password reset

Browser -> `/auth/password/request` -> auth store reads `auth_users` -> create reset record -> SMTP delivery -> browser receives generic response + internal `reset_id` when applicable -> `/auth/password/confirm` -> password hash updated -> active sessions deleted -> reset records deleted.

## Error Handling

- Unknown email: HTTP 200 with generic message, no reset ID.
- Missing SMTP configuration: HTTP 503 with operational error.
- SMTP send failure: HTTP 503; pending reset record removed.
- Invalid/expired reset code: HTTP 400 with generic invalid/expired message.
- Password shorter than 10 characters: HTTP 400.
- Database connectivity failure: surface as service error; do not silently fall back to a different production database after startup.

## Security Requirements

- Preserve PBKDF2 password hashing and per-user salts unless a separate password-hashing migration is designed.
- Never log reset codes, passwords, password hashes, SMTP secrets, or bearer tokens.
- Preserve anti-account-enumeration behavior.
- Reset success invalidates all sessions for that user.
- Reset codes remain time-limited and attempt-limited.
- Revenue privileges remain environment-controlled, not self-selected by users.

## UI Changes

### Taxpayer login

Retain the inline Forgot Password flow already introduced, but point it at the shared persistent auth backend.

### Revenue Operations login

Add:

- **Forgot password?** action under the password field.
- email-entry reset state;
- code + new password state;
- back-to-sign-in action;
- clear success/error messaging.

The existing MFA sign-in flow remains unchanged.

### Revenue Staff/Admin portal consistency

Any login entry point that ultimately uses the shared auth API must expose the same recovery path. There must not be a portal that requires a separate reset URL.

## Testing Strategy

### Unit/integration tests

- PostgreSQL auth schema initialization.
- Registration persists to PostgreSQL.
- Login reads persisted users.
- Email OTP records persist in PostgreSQL.
- Password reset request creates/reset records correctly.
- Unknown email returns generic success and no `reset_id`.
- Reset confirmation changes password and invalidates sessions.
- Admin/staff role assignment from environment variables.
- Revenue Operations page contains the reset controls and endpoint wiring.

### Migration tests

- SQLite-to-PostgreSQL import copies missing users/sessions/OTP/reset rows.
- Running the migration twice is idempotent.
- Existing PostgreSQL records are not overwritten.

### Acceptance test

1. Register or create a known test account.
2. Confirm it can sign in.
3. Restart/redeploy the Railway service.
4. Confirm the same account still signs in.
5. Request a reset code from Revenue Operations.
6. Confirm the email arrives.
7. Reset the password.
8. Confirm the old password no longer works.
9. Confirm the new password works.
10. Confirm the expected Revenue Admin/Staff role after role variables are configured.

## Deployment Plan

1. Implement the auth-store abstraction and PostgreSQL schema.
2. Add migration support and tests.
3. Refactor `auth.py` and `password_reset.py` to use the shared store.
4. Add reset UI to Revenue Operations and any missing login surface.
5. Run the complete CI suite.
6. Merge to `main` only after green CI.
7. Configure approved `PROMET_ADMIN_EMAILS` / `PROMET_STAFF_EMAILS` values.
8. Deploy to Railway.
9. Run the production acceptance test, including a redeploy persistence check and real reset-email delivery.

## Success Criteria

The work is complete only when:

- authentication survives Railway redeploys/restarts;
- password reset works from taxpayer and revenue login surfaces;
- a real account receives a reset code by email;
- unknown emails do not reveal account existence;
- reset passwords work and old sessions are invalidated;
- Revenue Admin/Staff roles resolve correctly from configured production variables;
- the full CI suite and production acceptance checks pass.
