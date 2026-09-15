"""auth.py — Secure authentication for URA-PROMET."""
import base64, hashlib, hmac, json, os, secrets, struct, time, urllib.error, urllib.request
from collections import defaultdict, deque
from threading import Lock
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import auth_store

KEY_FILE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"secret.key")
SESSION_TTL_SECONDS=60*60*8; OTP_TTL_SECONDS=int(os.getenv("PROMET_EMAIL_OTP_TTL_SECONDS","600")); OTP_MAX_ATTEMPTS=int(os.getenv("PROMET_EMAIL_OTP_MAX_ATTEMPTS","6"))
router=APIRouter(prefix="/auth",tags=["auth"])
SMTP_FROM=os.getenv("PROMET_SMTP_FROM","").strip()
RESEND_API_URL="https://api.resend.com/emails"
_LOGIN_ATTEMPTS=defaultdict(deque); _LOGIN_LOCK=Lock(); _LOGIN_WINDOW=300; _LOGIN_MAX=8

def role_for_email(email:str)->str:
    normalized=(email or "").strip().lower()
    admins={x.strip().lower() for x in os.getenv("PROMET_ADMIN_EMAILS","").split(",") if x.strip()}
    staff={x.strip().lower() for x in os.getenv("PROMET_STAFF_EMAILS","").split(",") if x.strip()}
    if normalized in admins:return "revenue_admin"
    if normalized in staff:return "revenue_staff"
    return "taxpayer"

def portal_for_role(role:str)->str:
    if role=="revenue_admin": return "/revenue"
    if role=="revenue_staff": return "/revenue-staff"
    return "/taxpayer"

def _check_login_rate(key):
    now=time.time()
    with _LOGIN_LOCK:
        q=_LOGIN_ATTEMPTS[key]
        while q and q[0]<now-_LOGIN_WINDOW:q.popleft()
        if len(q)>=_LOGIN_MAX: raise HTTPException(429,"Too many login attempts. Try again later.")
        q.append(now)
def _clear_login_rate(key):
    with _LOGIN_LOCK:_LOGIN_ATTEMPTS.pop(key,None)
def db(): return auth_store.db()
def init(): auth_store.init_schema()
init()

def _load_or_create_key():
    k=os.environ.get("TAX_FIELD_KEY_B64","").strip()
    if k:return base64.urlsafe_b64decode(k.encode())
    if os.path.exists(KEY_FILE):return open(KEY_FILE,"rb").read()
    key=secrets.token_bytes(32); open(KEY_FILE,"wb").write(key); return key
ENCRYPTION_KEY=_load_or_create_key()
def _keystream(key,nonce,length):
    out=b""; counter=0
    while len(out)<length: out+=hmac.new(key,nonce+counter.to_bytes(4,"big"),hashlib.sha256).digest(); counter+=1
    return out[:length]
def encrypt_field(plaintext):
    nonce=secrets.token_bytes(16); data=plaintext.encode(); ct=bytes(a^b for a,b in zip(data,_keystream(ENCRYPTION_KEY,nonce,len(data)))); tag=hmac.new(ENCRYPTION_KEY,nonce+ct,hashlib.sha256).digest(); return base64.urlsafe_b64encode(nonce+tag+ct).decode()
def decrypt_field(token):
    raw=base64.urlsafe_b64decode(token); nonce,tag,ct=raw[:16],raw[16:48],raw[48:]; expected=hmac.new(ENCRYPTION_KEY,nonce+ct,hashlib.sha256).digest()
    if not hmac.compare_digest(tag,expected):raise ValueError("Encrypted field integrity check failed")
    return bytes(a^b for a,b in zip(ct,_keystream(ENCRYPTION_KEY,nonce,len(ct)))).decode()
def hash_password(password,salt_hex=None):
    salt_hex=salt_hex or secrets.token_hex(16); dk=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt_hex),200_000); return dk.hex(),salt_hex
def verify_password(password,salt_hex,expected_hash):return hmac.compare_digest(hash_password(password,salt_hex)[0],expected_hash)
def generate_mfa_secret():return base64.b32encode(secrets.token_bytes(10)).decode()
def _hotp(secret_b32,counter,digits=6):
    key=base64.b32decode(secret_b32); digest=hmac.new(key,struct.pack(">Q",counter),hashlib.sha1).digest(); offset=digest[-1]&15; code=(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%(10**digits); return str(code).zfill(digits)
def verify_totp(secret_b32,code,window=1,step=30):
    counter=int(time.time()//step); code=(code or "").strip(); return any(hmac.compare_digest(_hotp(secret_b32,counter+w),code) for w in range(-window,window+1))
def provisioning_uri(email,secret_b32,issuer="URA-PROMET"):return f"otpauth://totp/{issuer}:{email}?secret={secret_b32}&issuer={issuer}&digits=6&period=30"
def _resend_ready():return bool(os.getenv("RESEND_API_KEY","").strip() and SMTP_FROM)
def _send_email_otp(email,code):
    api_key=os.getenv("RESEND_API_KEY","").strip()
    if not api_key or not SMTP_FROM:raise RuntimeError("PROMET email delivery is not configured")
    payload=json.dumps({"from":SMTP_FROM,"to":[email],"subject":"Your URA-PROMET verification code","text":f"Your URA-PROMET verification code is {code}.\n\nIt expires in {max(1,OTP_TTL_SECONDS//60)} minutes."}).encode("utf-8")
    request=urllib.request.Request(RESEND_API_URL,data=payload,headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json","User-Agent":"URA-PROMET/1.0"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=5) as response:
            if response.status<200 or response.status>=300:raise RuntimeError(f"Email provider returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Email provider returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Email provider is unavailable") from exc
def _issue_email_otp(c,session_token,user_id,email):
    code=f"{secrets.randbelow(1_000_000):06d}"; now=time.time(); c.execute("DELETE FROM auth_email_otp WHERE session_token=?",(session_token,)); c.execute("INSERT INTO auth_email_otp(session_token,user_id,code_hash,expires_at,attempts,created_at) VALUES(?,?,?,?,0,?)",(session_token,user_id,hashlib.sha256(code.encode()).hexdigest(),now+OTP_TTL_SECONDS,now)); _send_email_otp(email,code)
def _verify_email_otp(c,session_token,code):
    row=c.execute("SELECT * FROM auth_email_otp WHERE session_token=?",(session_token,)).fetchone()
    if not row or row["expires_at"]<time.time() or row["attempts"]>=OTP_MAX_ATTEMPTS:return False
    c.execute("UPDATE auth_email_otp SET attempts=attempts+1 WHERE session_token=?",(session_token,)); supplied=hashlib.sha256((code or "").strip().encode()).hexdigest()
    if not hmac.compare_digest(supplied,row["code_hash"]):return False
    c.execute("DELETE FROM auth_email_otp WHERE session_token=?",(session_token,)); return True
def require_auth(authorization:str=Header(None)):
    if not authorization or not authorization.startswith("Bearer "):raise HTTPException(401,"Missing bearer token")
    token=authorization.split(" ",1)[1]; c=db(); s=c.execute("SELECT * FROM auth_sessions WHERE token=?",(token,)).fetchone()
    if not s or s["expires_at"]<time.time():c.close();raise HTTPException(401,"Invalid or expired session")
    if not s["mfa_verified"]:c.close();raise HTTPException(401,"MFA verification required")
    user=c.execute("SELECT id,email,mfa_enabled FROM auth_users WHERE id=?",(s["user_id"],)).fetchone(); c.close(); out=dict(user); out["role"]=role_for_email(out["email"]); return out
class RegisterIn(BaseModel):email:str;password:str
class LoginIn(BaseModel):email:str;password:str
class MfaIn(BaseModel):session_token:str;code:str
@router.post("/register")
def register(body:RegisterIn):
    if len(body.password)<10:raise HTTPException(400,"Password must be at least 10 characters")
    c=db(); uid=secrets.token_hex(16); secret=generate_mfa_secret(); ph,salt=hash_password(body.password)
    try:
        c.execute("INSERT INTO auth_users VALUES(?,?,?,?,?,0,?)",(uid,body.email.lower().strip(),ph,salt,secret,time.time()))
    except Exception as exc:
        c.close()
        if exc.__class__.__name__ in {"IntegrityError","UniqueViolation"}:raise HTTPException(409,"Account already exists")
        raise
    c.close(); return {"status":"registered","role":"taxpayer"}
@router.post("/login")
def login(body:LoginIn):
    email=body.email.lower().strip(); _check_login_rate(email); c=db(); u=c.execute("SELECT * FROM auth_users WHERE email=?",(email,)).fetchone()
    if not u or not verify_password(body.password,u["password_salt"],u["password_hash"]):c.close();raise HTTPException(401,"Invalid credentials")
    token=secrets.token_urlsafe(32); now=time.time(); c.execute("INSERT INTO auth_sessions VALUES(?,?,?,?,?)",(token,u["id"],0,now,now+SESSION_TTL_SECONDS)); _clear_login_rate(email)
    if _resend_ready(): _issue_email_otp(c,token,u["id"],email); method="email_otp"
    else: method="totp"
    c.close(); return {"session_token":token,"mfa_required":True,"mfa_method":method,"provisioning_uri":provisioning_uri(email,u["mfa_secret"]) if method=="totp" else None,"mfa_secret":u["mfa_secret"] if method=="totp" else None}
@router.post("/mfa/verify")
def mfa_verify(body:MfaIn):
    c=db(); s=c.execute("SELECT * FROM auth_sessions WHERE token=?",(body.session_token,)).fetchone()
    if not s:c.close();raise HTTPException(401,"Invalid session")
    u=c.execute("SELECT * FROM auth_users WHERE id=?",(s["user_id"],)).fetchone(); ok=_verify_email_otp(c,body.session_token,body.code) if _resend_ready() else verify_totp(u["mfa_secret"],body.code)
    if not ok:c.close();raise HTTPException(401,"Invalid verification code")
    c.execute("UPDATE auth_sessions SET mfa_verified=1 WHERE token=?",(body.session_token,)); role=role_for_email(u["email"]); c.close(); return {"access_token":body.session_token,"token_type":"bearer","role":role,"portal":portal_for_role(role)}
@router.get("/me")
def me(user=__import__('fastapi').Depends(require_auth)):return user
class ChangePasswordIn(BaseModel):current_password:str;new_password:str
@router.post("/password/change")
def change_password(body:ChangePasswordIn,authorization:str=Header(None)):
    if not authorization or not authorization.startswith("Bearer "):raise HTTPException(401,"Missing bearer token")
    token=authorization.split(" ",1)[1]; c=db(); s=c.execute("SELECT * FROM auth_sessions WHERE token=?",(token,)).fetchone()
    if not s or s["expires_at"]<time.time():c.close();raise HTTPException(401,"Invalid or expired session")
    if not s["mfa_verified"]:c.close();raise HTTPException(401,"MFA verification required")
    u=c.execute("SELECT * FROM auth_users WHERE id=?",(s["user_id"],)).fetchone()
    if not u or not verify_password(body.current_password,u["password_salt"],u["password_hash"]):c.close();raise HTTPException(401,"Current password is incorrect")
    if len(body.new_password)<10:c.close();raise HTTPException(400,"New password must be at least 10 characters")
    if hmac.compare_digest(body.new_password.encode(),body.current_password.encode()):c.close();raise HTTPException(400,"New password must be different from your current password")
    ph,salt=hash_password(body.new_password)
    with auth_store.transaction(c):
        c.execute("UPDATE auth_users SET password_hash=?,password_salt=? WHERE id=?",(ph,salt,u["id"]))
        c.execute("DELETE FROM auth_sessions WHERE user_id=? AND token!=?",(u["id"],token))
    c.close(); return {"changed":True,"message":"Password updated. Other signed-in devices have been signed out."}
