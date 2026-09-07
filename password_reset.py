import hashlib
import hmac
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import auth

router = APIRouter(prefix="/auth/password", tags=["auth"])
RESET_TTL_SECONDS = 15 * 60
RESET_MAX_ATTEMPTS = 6


def _init():
    c = auth.db()
    c.execute("""CREATE TABLE IF NOT EXISTS auth_password_resets(
        reset_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )""")
    c.close()


_init()


def _send_reset_email(email: str, code: str) -> None:
    if not auth._smtp_ready():
        raise RuntimeError("Email delivery is not configured")
    msg = EmailMessage()
    msg["Subject"] = "Your URA-PROMET password reset code"
    msg["From"] = auth.SMTP_FROM
    msg["To"] = email
    msg.set_content(
        f"Your URA-PROMET password reset code is {code}.\n\n"
        "It expires in 15 minutes. If you did not request a password reset, ignore this message."
    )
    with smtplib.SMTP(auth.SMTP_HOST, auth.SMTP_PORT, timeout=10) as server:
        server.ehlo()
        if auth.SMTP_STARTTLS:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if auth.SMTP_USERNAME:
            server.login(auth.SMTP_USERNAME, auth.SMTP_PASSWORD)
        server.send_message(msg)


class ResetRequestIn(BaseModel):
    email: str


class ResetConfirmIn(BaseModel):
    reset_id: str
    code: str
    new_password: str


@router.post("/request")
def request_reset(body: ResetRequestIn):
    email = body.email.strip().lower()
    if not auth._smtp_ready():
        raise HTTPException(503, "Password reset email delivery is not configured")
    c = auth.db()
    user = c.execute("SELECT id,email FROM auth_users WHERE email=?", (email,)).fetchone()
    if not user:
        c.close()
        return {"sent": True, "message": "If that account exists, a reset code has been sent."}
    reset_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = time.time()
    c.execute("DELETE FROM auth_password_resets WHERE user_id=?", (user["id"],))
    c.execute(
        "INSERT INTO auth_password_resets(reset_id,user_id,code_hash,expires_at,attempts,created_at) VALUES(?,?,?,?,0,?)",
        (reset_id, user["id"], hashlib.sha256(code.encode()).hexdigest(), now + RESET_TTL_SECONDS, now),
    )
    try:
        _send_reset_email(email, code)
    except Exception as exc:
        c.execute("DELETE FROM auth_password_resets WHERE reset_id=?", (reset_id,))
        c.close()
        raise HTTPException(503, f"Could not send password reset email: {exc}")
    c.close()
    return {"sent": True, "reset_id": reset_id, "message": "If that account exists, a reset code has been sent."}


@router.post("/confirm")
def confirm_reset(body: ResetConfirmIn):
    if len(body.new_password) < 10:
        raise HTTPException(400, "Password must be at least 10 characters")
    c = auth.db()
    row = c.execute("SELECT * FROM auth_password_resets WHERE reset_id=?", (body.reset_id,)).fetchone()
    if not row or row["expires_at"] < time.time() or row["attempts"] >= RESET_MAX_ATTEMPTS:
        c.close()
        raise HTTPException(400, "Invalid or expired reset code")
    c.execute("UPDATE auth_password_resets SET attempts=attempts+1 WHERE reset_id=?", (body.reset_id,))
    supplied = hashlib.sha256((body.code or "").strip().encode()).hexdigest()
    if not hmac.compare_digest(supplied, row["code_hash"]):
        c.close()
        raise HTTPException(400, "Invalid or expired reset code")
    pw_hash, salt = auth.hash_password(body.new_password)
    c.execute("BEGIN IMMEDIATE")
    c.execute("UPDATE auth_users SET password_hash=?, password_salt=? WHERE id=?", (pw_hash, salt, row["user_id"]))
    c.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["user_id"],))
    c.execute("DELETE FROM auth_password_resets WHERE user_id=?", (row["user_id"],))
    c.execute("COMMIT")
    c.close()
    return {"reset": True, "message": "Password updated. Please sign in with your new password."}
