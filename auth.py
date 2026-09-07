"""
auth.py — Secure authentication for UNG-PROMET.

Primary MFA: short-lived 6-digit email OTP when SMTP delivery is configured.
Compatibility fallback: existing RFC 6238 authenticator TOTP remains available so
existing deployments are not locked out if mail delivery is not configured yet.
"""
import base64
import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import ssl
import struct
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from threading import Lock

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tax_filing.db")
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.key")
SESSION_TTL_SECONDS = 60 * 60 * 8
OTP_TTL_SECONDS = int(os.getenv("PROMET_EMAIL_OTP_TTL_SECONDS", "600"))
OTP_MAX_ATTEMPTS = int(os.getenv("PROMET_EMAIL_OTP_MAX_ATTEMPTS", "6"))
router = APIRouter(prefix="/auth", tags=["auth"])

SMTP_HOST = os.getenv("PROMET_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("PROMET_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("PROMET_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("PROMET_SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("PROMET_SMTP_FROM", SMTP_USERNAME).strip()
SMTP_STARTTLS = os.getenv("PROMET_SMTP_STARTTLS", "true").strip().lower() not in {"0", "false", "no"}

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
    c.execute("""CREATE TABLE IF NOT EXISTS auth_email_otp(
        session_token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
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
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret_b32: str, code: str, window: int = 1, step: int = 30) -> bool:
    counter = int(time.time() // step)
    code = (code or "").strip()
    return any(hmac.compare_digest(_hotp(secret_b32, counter + w), code) for w in range(-window, window + 1))


def provisioning_uri(email: str, secret_b32: str, issuer: str = "UNG-PROMET") -> str:
    return f"otpauth://totp/{issuer}:{email}?secret={secret_b32}&issuer={issuer}&digits=6&period=30"


def _smtp_ready() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def _send_email_otp(email: str, code: str) -> None:
    if not _smtp_ready():
        raise RuntimeError("PROMET email delivery is not configured")
    msg = EmailMessage()
    msg["Subject"] = "Your UNG-PROMET verification code"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(
        f"Your UNG-PROMET verification code is {code}.\n\n"
        f"It expires in {max(1, OTP_TTL_SECONDS // 60)} minutes. "
        "If you did not request this code, ignore this message."
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.ehlo()
        if SMTP_STARTTLS:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)


def _issue_email_otp(c, session_token: str, user_id: str, email: str) -> None:
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    now = time.time()
    c.execute("DELETE FROM auth_email_otp WHERE session_token=?", (session_token,))
    c.execute(
        "INSERT INTO auth_email_otp(session_token,user_id,code_hash,expires_at,attempts,created_at) VALUES(?,?,?,?,0,?)",
        (session_token, user_id, code_hash, now + OTP_TTL_SECONDS, now),
    )
    try:
        _send_email_otp(email, code)
    except Exception:
        c.execute("DELETE FROM auth_email_otp WHERE session_token=?", (session_token,))
        raise


def _verify_email_otp(c, session_token: str, code: str) -> bool:
    row = c.execute("SELECT * FROM auth_email_otp WHERE session_token=?", (session_token,)).fetchone()
    if not row or row["expires_at"] < time.time() or row["attempts"] >= OTP_MAX_ATTEMPTS:
        return False
    c.execute("UPDATE auth_email_otp SET attempts=attempts+1 WHERE session_token=?", (session_token,))
    supplied = hashlib.sha256((code or "").strip().encode()).hexdigest()
    if not hmac.compare_digest(supplied, row["code_hash"]):
        return False
    c.execute("DELETE FROM auth_email_otp WHERE session_token=?", (session_token,))
    return True


def _purge_expired_sessions(c):
    c.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (time.time(),))
    c.execute("DELETE FROM auth_email_otp WHERE expires_at < ?", (time.time(),))


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
    user = c.execute("SELECT id,email,mfa_enabled FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
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


@router.get("/mfa/capabilities")
def mfa_capabilities():
    return {"email_otp": _smtp_ready(), "sms_otp": False, "totp_fallback": True}


@router.post("/register")
def register(body: RegisterIn):
    if len(body.password) < 10:
        raise HTTPException(400, "Password must be at least 10 characters")
    email = body.email.strip().lower()
    c = db(); pw_hash, salt = hash_password(body.password); mfa_secret = generate_mfa_secret(); uid = secrets.token_hex(16)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO auth_users(id,email,password_hash,password_salt,mfa_secret,mfa_enabled,created_at) VALUES(?,?,?,?,?,0,?)",
                  (uid, email, pw_hash, salt, mfa_secret, time.time()))
        c.execute("COMMIT")
    except sqlite3.IntegrityError:
        c.execute("ROLLBACK"); c.close(); raise HTTPException(409, "An account with this email already exists")
    c.close()
    return {
        "user_id": uid,
        "mfa_method": "email" if _smtp_ready() else "totp",
        "email_otp_available": _smtp_ready(),
        "provisioning_uri": provisioning_uri(email, mfa_secret) if not _smtp_ready() else None,
        "mfa_secret": mfa_secret if not _smtp_ready() else None,
    }


@router.post("/login")
def login(body: LoginIn):
    email = body.email.strip().lower(); _check_login_rate(email)
    c = db(); _purge_expired_sessions(c)
    user = c.execute("SELECT * FROM auth_users WHERE email=?", (email,)).fetchone()
    if not user or not verify_password(body.password, user["password_salt"], user["password_hash"]):
        c.close(); raise HTTPException(401, "Incorrect email or password")
    _clear_login_rate(email)
    token = secrets.token_urlsafe(32); now = time.time()
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO auth_sessions(token,user_id,mfa_verified,created_at,expires_at) VALUES(?,?,?,?,?)",
              (token, user["id"], 0, now, now + SESSION_TTL_SECONDS))
    if _smtp_ready():
        try:
            _issue_email_otp(c, token, user["id"], email)
        except Exception as exc:
            c.execute("ROLLBACK"); c.close(); raise HTTPException(503, f"Could not send verification email: {exc}")
        c.execute("COMMIT"); c.close()
        return {"session_token": token, "mfa_required": True, "mfa_method": "email", "delivery": "email"}
    c.execute("COMMIT"); c.close()
    return {"session_token": token, "mfa_required": True, "mfa_method": "totp", "delivery": "authenticator"}


@router.post("/mfa/enable")
def enable_mfa(body: MfaVerifyIn):
    c = db(); s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (body.session_token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    user = c.execute("SELECT * FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    if _smtp_ready():
        ok = _verify_email_otp(c, body.session_token, body.code)
    else:
        ok = verify_totp(user["mfa_secret"], body.code)
    if not ok:
        c.close(); raise HTTPException(400, "Incorrect or expired code")
    c.execute("BEGIN IMMEDIATE")
    c.execute("UPDATE auth_users SET mfa_enabled=1 WHERE id=?", (user["id"],))
    c.execute("UPDATE auth_sessions SET mfa_verified=1 WHERE token=?", (body.session_token,))
    c.execute("COMMIT"); c.close()
    return {"mfa_enabled": True, "method": "email" if _smtp_ready() else "totp"}


@router.post("/mfa/login-verify")
def mfa_login_verify(body: MfaVerifyIn):
    c = db(); s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (body.session_token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    user = c.execute("SELECT * FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    if _smtp_ready():
        ok = _verify_email_otp(c, body.session_token, body.code)
    else:
        ok = verify_totp(user["mfa_secret"], body.code)
    if not ok:
        c.close(); raise HTTPException(400, "Incorrect or expired code")
    c.execute("BEGIN IMMEDIATE")
    c.execute("UPDATE auth_users SET mfa_enabled=1 WHERE id=?", (user["id"],))
    c.execute("UPDATE auth_sessions SET mfa_verified=1 WHERE token=?", (body.session_token,))
    c.execute("COMMIT"); c.close()
    return {"session_token": body.session_token, "verified": True, "method": "email" if _smtp_ready() else "totp"}


@router.post("/mfa/resend")
def mfa_resend(body: MfaVerifyIn):
    if not _smtp_ready():
        raise HTTPException(503, "Email OTP delivery is not configured")
    c = db(); s = c.execute("SELECT * FROM auth_sessions WHERE token=?", (body.session_token,)).fetchone()
    if not s:
        c.close(); raise HTTPException(401, "Invalid session")
    user = c.execute("SELECT * FROM auth_users WHERE id=?", (s["user_id"],)).fetchone()
    c.execute("BEGIN IMMEDIATE")
    try:
        _issue_email_otp(c, body.session_token, user["id"], user["email"])
        c.execute("COMMIT")
    except Exception as exc:
        c.execute("ROLLBACK"); c.close(); raise HTTPException(503, f"Could not send verification email: {exc}")
    c.close()
    return {"sent": True, "delivery": "email"}
