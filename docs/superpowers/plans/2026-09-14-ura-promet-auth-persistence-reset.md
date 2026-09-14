# URA-PROMET Authentication Persistence and Password Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make URA-PROMET authentication durable in PostgreSQL, provide the same password-recovery flow from taxpayer and revenue sign-in surfaces, and verify real reset-email delivery and revenue-role resolution in production.

**Architecture:** Add a focused `auth_store.py` abstraction that owns SQLite/PostgreSQL connections, schema creation, SQL placeholder adaptation, transactions, and optional idempotent SQLite-to-PostgreSQL migration. Refactor `auth.py` and `password_reset.py` to use that store without changing their public HTTP contracts, then add reset controls to the Revenue Operations workspace. Production uses the existing Railway `DATABASE_URL`; SQLite is retained only when no PostgreSQL URL is configured.

**Tech Stack:** Python 3, FastAPI, SQLite, PostgreSQL, psycopg 3, Pydantic 2, vanilla HTML/JavaScript, pytest, Railway.

**Spec:** `docs/superpowers/specs/2026-09-14-ura-promet-auth-persistence-reset-design.md`

## Global Constraints

- Production PostgreSQL is authoritative when `DATABASE_URL` begins with `postgres://` or `postgresql://`.
- SQLite is a local-development fallback only when PostgreSQL is not configured.
- Preserve existing public endpoints: `/auth/register`, `/auth/login`, `/auth/mfa/verify`, `/auth/me`, `/auth/password/request`, `/auth/password/confirm`.
- Preserve PBKDF2 password hashing and per-user salts.
- Preserve anti-account-enumeration behavior for password reset.
- Never log passwords, reset codes, hashes, SMTP secrets, or bearer tokens.
- Reset codes remain valid for 15 minutes and at most 6 attempts.
- Successful password reset invalidates all active sessions for that user.
- Revenue privileges remain environment-controlled through `PROMET_ADMIN_EMAILS` and `PROMET_STAFF_EMAILS`.
- Do not enable live authority transmission.
- Use TDD for every behavior change.

---

## File Structure

- Create `auth_store.py` — database selection, connection wrapper, auth schema, transactions, migration helper.
- Modify `auth.py` — use `auth_store` for users, sessions, and MFA OTPs; preserve API behavior.
- Modify `password_reset.py` — use `auth_store` for reset records and password/session updates.
- Modify `static/ops-workspace.html` — add Revenue Operations password-reset states.
- Modify `static/ops-workspace.js` — wire Revenue Operations reset request/confirm calls.
- Modify `main.py` — expose auth-storage health metadata without secrets.
- Create `tests/test_auth_store.py` — storage/backend/schema behavior.
- Create `tests/test_auth_migration.py` — idempotent SQLite migration behavior.
- Modify/create `tests/test_auth.py` — registration/login/MFA persistence tests.
- Modify `tests/test_password_reset.py` — reset persistence, anti-enumeration, session invalidation.
- Modify `tests/test_ops_ui.py` — Revenue Operations reset controls and endpoint wiring.

---

### Task 1: Shared Authentication Store and PostgreSQL Schema

**Files:**
- Create: `auth_store.py`
- Create: `tests/test_auth_store.py`

**Interfaces:**
- Produces: `backend_name() -> str`, `db() -> connection wrapper`, `init_schema() -> None`, `transaction(connection) -> context manager`.
- Connection wrapper must support existing `?` SQL placeholders and mapping-style rows on SQLite and PostgreSQL.

- [ ] **Step 1: Write failing backend-selection and schema tests**

```python
import importlib


def test_sqlite_is_fallback_without_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store
    importlib.reload(auth_store)
    assert auth_store.backend_name() == "sqlite"


def test_auth_schema_contains_all_four_tables(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PROMET_AUTH_DB", str(tmp_path / "auth.db"))
    import auth_store
    importlib.reload(auth_store)
    auth_store.init_schema()
    c = auth_store.db()
    names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    assert {"auth_users", "auth_sessions", "auth_email_otp", "auth_password_resets"} <= names
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_auth_store.py -q`

Expected: FAIL because `auth_store` does not exist.

- [ ] **Step 3: Implement `auth_store.py` minimally**

Implement:

```python
def backend_name() -> str: ...
def db(): ...
def init_schema() -> None: ...
@contextmanager
def transaction(connection): ...
```

Use `psycopg.connect(..., row_factory=dict_row, autocommit=True)` for PostgreSQL and `sqlite3.Row` for SQLite. Adapt `?` to `%s` only in the PostgreSQL wrapper. Create the four tables with logically equivalent columns and no database-specific behavior leaking into callers.

- [ ] **Step 4: Run store tests and existing foundation tests**

Run: `PYTHONPATH=. pytest tests/test_auth_store.py tests/test_ops_foundation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add auth_store.py tests/test_auth_store.py
git commit -m "feat: add persistent authentication store"
```

---

### Task 2: Refactor Registration, Login, Sessions, and MFA onto the Shared Store

**Files:**
- Modify: `auth.py`
- Create/Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `auth_store.db()`, `auth_store.init_schema()`, `auth_store.transaction()`.
- Preserves: `role_for_email`, `portal_for_role`, `hash_password`, `verify_password`, `require_auth`, all existing `/auth/*` HTTP contracts.

- [ ] **Step 1: Write failing persistence and role tests**

```python
def test_registered_user_survives_new_connection(client):
    r = client.post("/auth/register", json={"email":"persist@example.com", "password":"StrongPass123"})
    assert r.status_code == 200
    import auth_store
    c = auth_store.db()
    row = c.execute("SELECT email FROM auth_users WHERE email=?", ("persist@example.com",)).fetchone()
    c.close()
    assert row["email"] == "persist@example.com"


def test_admin_role_comes_from_environment(monkeypatch):
    monkeypatch.setenv("PROMET_ADMIN_EMAILS", "admin@example.com")
    import auth
    assert auth.role_for_email("ADMIN@example.com") == "revenue_admin"
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_auth.py -q`

Expected: at least the shared-store persistence test FAILS while `auth.py` still owns SQLite directly.

- [ ] **Step 3: Refactor `auth.py`**

Replace direct `sqlite3.connect(DB, ...)` ownership with `auth_store.db()`. Initialize schema through `auth_store.init_schema()`. Keep password/MFA cryptographic behavior and endpoint response shapes unchanged. Replace SQLite-specific `BEGIN IMMEDIATE` blocks with `auth_store.transaction(c)`.

- [ ] **Step 4: Run auth and password tests**

Run: `PYTHONPATH=. pytest tests/test_auth.py tests/test_password_reset.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "refactor: persist auth sessions and users through shared store"
```

---

### Task 3: Refactor Password Reset onto Persistent Storage

**Files:**
- Modify: `password_reset.py`
- Modify: `tests/test_password_reset.py`

**Interfaces:**
- Consumes: `auth_store.db()`, `auth_store.transaction()`.
- Preserves request contract `{email}` and confirm contract `{reset_id, code, new_password}`.
- Preserves unknown-email response: HTTP 200 generic message with no `reset_id`.

- [ ] **Step 1: Write failing reset-store and invalidation tests**

```python
def test_unknown_email_returns_generic_success_without_reset_id(client):
    r = client.post("/auth/password/request", json={"email":"missing@example.com"})
    assert r.status_code == 200
    assert r.json()["sent"] is True
    assert "reset_id" not in r.json()


def test_successful_reset_invalidates_existing_sessions(client, seeded_user, smtp_stub):
    login = client.post("/auth/login", json={"email": seeded_user.email, "password": seeded_user.password}).json()
    reset = client.post("/auth/password/request", json={"email": seeded_user.email}).json()
    code = smtp_stub.last_reset_code
    done = client.post("/auth/password/confirm", json={"reset_id":reset["reset_id"], "code":code, "new_password":"NewStrongPass123"})
    assert done.status_code == 200
    import auth_store
    c = auth_store.db()
    sessions = c.execute("SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=?", (seeded_user.user_id,)).fetchone()["n"]
    c.close()
    assert sessions == 0
```

- [ ] **Step 2: Run reset tests and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_password_reset.py -q`

Expected: persistent-store-specific assertions FAIL before the refactor.

- [ ] **Step 3: Refactor `password_reset.py`**

Use `auth_store.db()` for lookup, reset creation, confirmation, password update, session deletion, and reset deletion. Keep SMTP behavior exactly separated: missing SMTP -> 503; send failure -> delete pending reset + 503; unknown account -> generic 200; successful send -> generic 200 + `reset_id`.

- [ ] **Step 4: Run reset/auth tests**

Run: `PYTHONPATH=. pytest tests/test_password_reset.py tests/test_auth.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add password_reset.py tests/test_password_reset.py
git commit -m "fix: persist password recovery state"
```

---

### Task 4: Idempotent SQLite-to-PostgreSQL Migration

**Files:**
- Modify: `auth_store.py`
- Create: `tests/test_auth_migration.py`

**Interfaces:**
- Produces: `migrate_sqlite_auth(sqlite_path: str) -> dict[str, int]` returning inserted counts for the four auth tables.
- Migration inserts only rows missing by primary key/unique identity and never overwrites destination rows.

- [ ] **Step 1: Write failing migration tests**

```python
def test_migration_is_idempotent(pg_auth_store, legacy_sqlite):
    first = pg_auth_store.migrate_sqlite_auth(str(legacy_sqlite))
    second = pg_auth_store.migrate_sqlite_auth(str(legacy_sqlite))
    assert first["auth_users"] == 1
    assert second == {"auth_users":0, "auth_sessions":0, "auth_email_otp":0, "auth_password_resets":0}


def test_migration_does_not_overwrite_destination_user(pg_auth_store, legacy_sqlite):
    pg_auth_store.seed_user("same-id", "new@example.com")
    pg_auth_store.migrate_sqlite_auth(str(legacy_sqlite))
    assert pg_auth_store.get_user("same-id")["email"] == "new@example.com"
```

- [ ] **Step 2: Run migration tests and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_auth_migration.py -q`

Expected: FAIL because migration helper is undefined.

- [ ] **Step 3: Implement migration helper**

Open the legacy SQLite file read-only when present. For each auth table, read rows and insert with conflict-ignore semantics (`INSERT OR IGNORE` locally, `ON CONFLICT DO NOTHING` in PostgreSQL). Copy no secrets to logs. If the file is absent, return zero counts.

- [ ] **Step 4: Run migration tests**

Run: `PYTHONPATH=. pytest tests/test_auth_migration.py tests/test_auth_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add auth_store.py tests/test_auth_migration.py
git commit -m "feat: add idempotent auth data migration"
```

---

### Task 5: Revenue Operations Forgot-Password UI

**Files:**
- Modify: `static/ops-workspace.html`
- Modify: `static/ops-workspace.js`
- Modify: `tests/test_ops_ui.py`

**Interfaces:**
- Consumes: `POST /auth/password/request`, `POST /auth/password/confirm`.
- UI IDs: `forgotPasswordBtn`, `resetRequestBox`, `resetEmail`, `sendResetBtn`, `resetConfirmBox`, `resetCode`, `resetNewPassword`, `confirmResetBtn`, `backToLoginBtn`.

- [ ] **Step 1: Write failing UI contract test**

```python
def test_revenue_operations_has_password_recovery(client):
    html = client.get("/operations").text
    for control in ["forgotPasswordBtn", "resetEmail", "sendResetBtn", "resetCode", "resetNewPassword", "confirmResetBtn"]:
        assert f'id="{control}"' in html
    js = client.get("/static/ops-workspace.js").text
    assert "/auth/password/request" in js
    assert "/auth/password/confirm" in js
```

- [ ] **Step 2: Run UI test and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_ops_ui.py -q`

Expected: FAIL because Revenue Operations has no reset controls.

- [ ] **Step 3: Add minimal reset states and wiring**

In `ops-workspace.html`, add a **Forgot password?** action beneath the password input plus hidden request and confirmation states. In `ops-workspace.js`, request a code, retain returned `reset_id` only in memory, show the generic message, advance only when a `reset_id` is returned, confirm the code/new password, clear reset state, and return to login after success.

- [ ] **Step 4: Run UI and reset tests**

Run: `PYTHONPATH=. pytest tests/test_ops_ui.py tests/test_password_reset.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/ops-workspace.html static/ops-workspace.js tests/test_ops_ui.py
git commit -m "feat: add password recovery to revenue operations"
```

---

### Task 6: Storage Health Metadata and Full Regression Gate

**Files:**
- Modify: `main.py`
- Create/Modify: `tests/test_health.py`

**Interfaces:**
- `/health` adds `auth_storage` with value `postgresql` or `sqlite`; it must never expose a database URL or credential.

- [ ] **Step 1: Write failing health test**

```python
def test_health_reports_auth_backend_without_secrets(client):
    payload = client.get("/health").json()
    assert payload["auth_storage"] in {"sqlite", "postgresql"}
    assert "DATABASE_URL" not in str(payload)
```

- [ ] **Step 2: Run health test and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_health.py -q`

Expected: FAIL because `auth_storage` is absent.

- [ ] **Step 3: Add health metadata**

Import `auth_store` in `main.py` and add `"auth_storage": auth_store.backend_name()` to the existing health payload. Do not include connection strings, hosts, usernames, or passwords.

- [ ] **Step 4: Run complete test suite**

Run: `PYTHONPATH=. pytest -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_health.py
git commit -m "chore: expose auth storage health status"
```

---

### Task 7: Production Configuration and Acceptance Gate

**Files:**
- No code file changes unless acceptance reveals a reproducible defect; any defect returns to TDD before correction.

**Interfaces:**
- Railway service uses existing `DATABASE_URL`.
- Production variables to configure after explicit address confirmation: `PROMET_ADMIN_EMAILS`, optionally `PROMET_STAFF_EMAILS`.

- [ ] **Step 1: Verify CI on the feature branch**

Run/check: complete GitHub Actions test workflow for the final feature commit.

Expected: green test job.

- [ ] **Step 2: Confirm intended Revenue Admin/Staff email addresses with the user**

Do not infer or promote an email address from screenshots. Record the exact approved addresses before setting Railway variables.

- [ ] **Step 3: Merge only after green CI and user merge approval**

Merge feature branch into `main` using the approved repository workflow.

- [ ] **Step 4: Configure approved Railway role variables and deploy only with explicit deployment authorization**

Set `PROMET_ADMIN_EMAILS` and/or `PROMET_STAFF_EMAILS` without altering SMTP secrets. Confirm the service remains bound to `DATABASE_URL` and `main`.

- [ ] **Step 5: Run production acceptance**

Verify in order:

```text
1. /health reports auth_storage=postgresql.
2. Known account can register/be created and sign in.
3. Revenue Operations exposes Forgot password?.
4. Reset request for known account produces a real email.
5. 6-digit code resets password.
6. Old password fails; new password succeeds.
7. Redeploy/restart service.
8. New password still succeeds after redeploy.
9. Approved admin/staff email resolves to expected revenue role.
10. Unknown email still gets generic reset response without account disclosure.
```

Expected: all ten checks PASS before declaring the authentication repair complete.

- [ ] **Step 6: Record acceptance evidence**

Capture deployment ID/commit, CI run, health response, and pass/fail results without storing passwords, OTP codes, SMTP secrets, or tokens.
