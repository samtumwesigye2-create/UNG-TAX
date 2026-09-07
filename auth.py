"""
auth.py — Secure authentication for the tax filing app.

Implements:
  - Password hashing: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
  - Multi-factor auth: standard TOTP (RFC 6238).
  - Session tokens: random 256-bit tokens, expiring, checked on every request.
  - Field-level encryption pattern for sensitive values at rest.
  - Login rate limiting (per-email sliding window).

Production deployment must keep encryption material outside the repository.
"""
import os, sqlite3, time, hmac, hashlib, secrets, base64, struct
from collections import defaultdict, deque
from threading import Lock
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tax_filing.db")
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.key")
SESSION_TTL_SECONDS = 60 * 60 * 8
router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_ATTEMPTS = defaultdict(deque)
_LOGIN_LOCK = Lock()
_LOGIN_WINDOW = 300
_LOGIN_MAX = 8


def _check_login_rate(key: str):
    now = time.time()
    with _LOGIN_LOCK:
        q = _LOGIN_ATTEMPTS[key]
        while q and q[0] < now - _LOGIN_WINDOW:
            q.popleft()
        if len(q) >= _LOGIN_MAX:
            raise HTTPException(429, "Too many login attempts. Try again later.")
        q.append(now)


def _clear_login_rate(key: str):
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


def _purge_expired_sessions(c):
    c.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (time.time(),))


def db():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init():
    c = db()
    c.execute("BEGIN IMMEDIATE")
    c.execute("""CREATE TABLE IF NOT EXISTS auth_users(
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        mfa_secret TEXT NOT NULL,
        mfa_enabled INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS auth_sessions(
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES auth_users(id),
        mfa_verified INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    )""")
    c.execute("COMMIT")
    c.close()


init()


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("TAX_FIELD_KEY_B64", "").strip()
    if env_key:
        return base64.urlsafe_b64decode(env_key.encode())
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = secrets.token_bytes(32)
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


ENCRYPTION_KEY = _load_or_create_key()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out, counter = b"", 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def encrypt_field(plaintext: str) -> str:
    nonce = secrets.token_bytes(16)
    data = plaintext.encode()
    ct = bytes(a ^ b for a, b in zip(data, _keystream(ENCRYPTION_KEY, nonce, len(data))))
    tag = hmac.new(ENCRYPTION_KEY, nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt_field(token: str) -> str:
    raw = base64.urlsafe_b64decode(token)
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    expected = hmac.new(ENCRYPTION_KEY, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Encrypted field integrity check failed")
    data = bytes(a ^ b for a, b in zip(ct, _keystream(ENCRYPTION_KEY, nonce, len(ct))))
    return data.decode()


def hash_password(password: str, salt_hex: str = None) -> tuple:
    salt_hex = salt_hex or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return dk.hex(), salt_hex


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    dk, _ = hash_password(password, salt_hex)
    return hmac.compare_digest(dk, expected_hash)


def generate_mfa_secret() -> str:
    return base64.b32encode(secrets.token_bytes(10)).decode()


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, step: int = 30, digits: int = 6) -> str:
    return _hotp(secret_b32, int(time.time() // step), digits)


def verify_totp(secret_b32: str, code: str, window: int = 1, step: int = 30) -> bool:
    now_counter = int(time.time() // step)
    code = (code or "").strip()
    return any(hmac.compare_digest(_hotp(secret_b32, now_counter + w), code) for w in range(-window, window + 1))


def provisioning_uri(email: str, secret_b32: str, issuer: str = "UNG Tax") -> str:
    return f"otpauth://totp/{issuer}:{email}?secret={secret_b32}&issuer={issuer}&digits=6&period=30"


def require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    c = db()
    s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    if s["expires_at"] < time.time():
        c.close(); raise HTTPException(401, "Session expired, please log in again")
    if not s["mfa_verified"]:
        c.close(); raise HTTPException(401, "MFA verification required")
    user = c.execute("SELECT id, email, mfa_enabled FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    c.close()
    return dict(user)


class RegisterIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class MfaVerifyIn(BaseModel):
    session_token: str
    code: str


@router.post("/register")
def register(body: RegisterIn):
    if len(body.password) < 10:
        raise HTTPException(400, "Password must be at least 10 characters")
    c = db(); pw_hash, salt = hash_password(body.password); mfa_secret = generate_mfa_secret(); uid = secrets.token_hex(16)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO auth_users(id,email,password_hash,password_salt,mfa_secret,mfa_enabled,created_at)
                     VALUES(?,?,?,?,?,0,?)""", (uid, body.email.strip().lower(), pw_hash, salt, mfa_secret, time.time()))
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK"); c.close(); raise HTTPException(409, "An account with this email already exists")
    c.close()
    return {"user_id": uid, "mfa_secret": mfa_secret, "provisioning_uri": provisioning_uri(body.email, mfa_secret)}


@router.post("/login")
def login(body: LoginIn):
    email_key = body.email.strip().lower(); _check_login_rate(email_key)
    c = db(); _purge_expired_sessions(c)
    user = c.execute("SELECT * FROM auth_users WHERE email=?", (email_key,)).fetchone()
    if not user or not verify_password(body.password, user["password_salt"], user["password_hash"]):
        c.close(); raise HTTPException(401, "Incorrect email or password")
    _clear_login_rate(email_key)
    token = secrets.token_urlsafe(32); now = time.time(); mfa_required = bool(user["mfa_enabled"])
    c.execute("BEGIN IMMEDIATE")
    c.execute("""INSERT INTO auth_sessions(token,user_id,mfa_verified,created_at,expires_at)
                 VALUES(?,?,?,?,?)""", (token, user["id"], 0 if mfa_required else 1, now, now + SESSION_TTL_SECONDS))
    c.execute("COMMIT"); c.close()
    return {"session_token": token, "mfa_required": mfa_required}


@router.post("/mfa/enable")
def enable_mfa(body: MfaVerifyIn):
    c = db(); s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (body.session_token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    user = c.execute("SELECT * FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    if not verify_totp(user["mfa_secret"], body.code):
        c.close(); raise HTTPException(400, "Incorrect code")
    c.execute("BEGIN IMMEDIATE"); c.execute("UPDATE auth_users SET mfa_enabled=1 WHERE id=?", (user["id"],)); c.execute("UPDATE auth_sessions SET mfa_verified=1 WHERE token=?", (body.session_token,)); c.execute("COMMIT"); c.close()
    return {"mfa_enabled": True}


@router.post("/mfa/login-verify")
def mfa_login_verify(body: MfaVerifyIn):
    c = db(); s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (body.session_token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    user = c.execute("SELECT * FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    if not verify_totp(user["mfa_secret"], body.code):
        c.close(); raise HTTPException(400, "Incorrect code")
    c.execute("BEGIN IMMEDIATE"); c.execute("UPDATE auth_sessions SET mfa_verified=1 WHERE token=?", (body.session_token,)); c.execute("COMMIT"); c.close()
    return {"session_token": body.session_token, "verified": True}
