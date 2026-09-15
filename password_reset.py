import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import auth
import auth_store

router = APIRouter(prefix="/auth/password", tags=["auth"])
RESET_TTL_SECONDS = 15 * 60
RESET_MAX_ATTEMPTS = 6
RESEND_API_URL = "https://api.resend.com/emails"


def _init():
    auth_store.init_schema()


_init()


def _resend_ready() -> bool:
    return bool(os.getenv("RESEND_API_KEY", "").strip() and auth.SMTP_FROM)


def _send_reset_email(email: str, code: str) -> None:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key or not auth.SMTP_FROM:
        raise RuntimeError("Email delivery is not configured")

    payload = json.dumps({
        "from": auth.SMTP_FROM,
        "to": [email],
        "subject": "Your URA-PROMET password reset code",
        "text": (
            f"Your URA-PROMET password reset code is {code}.\n\n"
            "It expires in 15 minutes. If you did not request a password reset, ignore this message."
        ),
    }).encode("utf-8")
    request = urllib.request.Request(
        RESEND_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "URA-PROMET/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Email provider returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        # Do not leak provider responses or credentials to the client.
        raise RuntimeError(f"Email provider returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Email provider is unavailable") from exc


class ResetRequestIn(BaseModel):
    email: str


class ResetConfirmIn(BaseModel):
    reset_id: str
    code: str
    new_password: str


@router.post("/request")
def request_reset(body: ResetRequestIn):
    email = body.email.strip().lower()
    if not _resend_ready():
        raise HTTPException(503, "Password reset email delivery is not configured")
    c = auth_store.db()
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
    c = auth_store.db()
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
    with auth_store.transaction(c):
        c.execute("UPDATE auth_users SET password_hash=?, password_salt=? WHERE id=?", (pw_hash, salt, row["user_id"]))
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["user_id"],))
        c.execute("DELETE FROM auth_password_resets WHERE user_id=?", (row["user_id"],))
    c.close()
    return {"reset": True, "message": "Password updated. Please sign in with your new password."}
