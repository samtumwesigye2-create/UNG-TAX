from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

import auth
import password_reset
import tax_filing
import tax_advanced

app = FastAPI(title="URA-PROMET", description="Public Revenue Operations, Management & Electronic Taxation", version="0.4.0")
_origins = [x.strip() for x in os.environ.get("TAX_CORS_ORIGINS", "http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router)
app.include_router(password_reset.router)
app.include_router(tax_filing.router)
app.include_router(tax_advanced.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _render_wizard() -> str:
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    if auth._smtp_ready():
        html = html.replace(
            "Secured with a password and a one-time code from your authenticator app.",
            "Secured with a password and a one-time code sent to your email."
        )
        html = html.replace(
            "Scan this into an authenticator app (Google Authenticator, Authy, 1Password), then enter the 6-digit code it shows.",
            "We sent a 6-digit verification code to your email. Enter it below."
        )
        html = html.replace(
            '<div class="upload-box" id="mfaUriBox" style="word-break:break-all;font-family:monospace;font-size:0.72rem;"></div>',
            '<div class="upload-box" id="mfaUriBox">Check your email for your URA-PROMET verification code.</div>'
        )
        html = html.replace("6-digit code from your authenticator app", "6-digit code sent to your email")
        html = html.replace("Set up two-factor authentication", "Verify your email")
        html = html.replace("Enter your authenticator code", "Enter the code sent to your email")
        html = html.replace("showMfaSetup(data.provisioning_uri, data.mfa_secret);", "showMfaSetup('email', '');")
        html = html.replace(
            '$("mfaUriBox").textContent = uri + "\\n\\n(Manual entry key: " + secret + ")";',
            '$("mfaUriBox").textContent = "Check your email for your URA-PROMET verification code.";'
        )

    reset_link = '<button type="button" class="btn-text" style="margin-top:8px" onclick="showPasswordReset()">Forgot password?</button>'
    html = html.replace('<input type="password" id="authPassword">', '<input type="password" id="authPassword">' + reset_link)

    reset_panel = '''
    <div id="passwordResetForm" class="hidden">
      <p class="sub">Reset your password by email.</p>
      <label>Email</label>
      <input type="email" id="resetEmail">
      <div id="resetRequestActions" class="actions">
        <button type="button" class="btn-text" onclick="cancelPasswordReset()">Back to sign in</button>
        <button type="button" class="btn-primary" onclick="requestPasswordReset()">Send reset code</button>
      </div>
      <div id="resetConfirmFields" class="hidden">
        <label>6-digit reset code</label>
        <input type="text" id="resetCode" maxlength="6" inputmode="numeric">
        <label>New password <span class="hint">(10+ characters)</span></label>
        <input type="password" id="resetNewPassword">
        <label>Confirm new password</label>
        <input type="password" id="resetConfirmPassword">
        <div class="actions">
          <button type="button" class="btn-text" onclick="cancelPasswordReset()">Cancel</button>
          <button type="button" class="btn-primary" onclick="confirmPasswordReset()">Reset password</button>
        </div>
      </div>
      <div class="error hidden" id="resetError"></div>
      <div class="hint hidden" id="resetStatus"></div>
    </div>
'''
    html = html.replace('    <div id="authRegisterForm" class="hidden">', reset_panel + '\n    <div id="authRegisterForm" class="hidden">')

    reset_js = r'''
<script>
let prometResetId = null;
function _hideAuthPanels(){
  ["authLoginForm","authRegisterForm","mfaSetupForm","mfaLoginForm","passwordResetForm"].forEach(function(id){
    const el=document.getElementById(id); if(el) el.classList.add("hidden");
  });
}
function showPasswordReset(){
  _hideAuthPanels();
  document.getElementById("passwordResetForm").classList.remove("hidden");
  document.getElementById("authHeading").textContent="Reset password";
  const current=document.getElementById("authEmail").value;
  document.getElementById("resetEmail").value=current || "";
  document.getElementById("resetError").classList.add("hidden");
}
function cancelPasswordReset(){
  _hideAuthPanels();
  document.getElementById("authLoginForm").classList.remove("hidden");
  document.getElementById("authHeading").textContent="Sign in";
  prometResetId=null;
  document.getElementById("resetConfirmFields").classList.add("hidden");
  document.getElementById("resetRequestActions").classList.remove("hidden");
}
async function requestPasswordReset(){
  const err=document.getElementById("resetError"), status=document.getElementById("resetStatus");
  err.classList.add("hidden"); status.classList.add("hidden");
  try{
    const r=await fetch("/auth/password/request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:document.getElementById("resetEmail").value.trim()})});
    const data=await r.json();
    if(!r.ok) throw new Error(data.detail || "Could not send reset code");
    prometResetId=data.reset_id || null;
    if(!prometResetId){
      status.textContent=data.message || "If that account exists, a reset code has been sent."; status.classList.remove("hidden"); return;
    }
    document.getElementById("resetRequestActions").classList.add("hidden");
    document.getElementById("resetConfirmFields").classList.remove("hidden");
    status.textContent="Reset code sent. Check your email."; status.classList.remove("hidden");
  }catch(e){ err.textContent=e.message; err.classList.remove("hidden"); }
}
async function confirmPasswordReset(){
  const err=document.getElementById("resetError"), status=document.getElementById("resetStatus");
  err.classList.add("hidden"); status.classList.add("hidden");
  const p1=document.getElementById("resetNewPassword").value, p2=document.getElementById("resetConfirmPassword").value;
  if(p1!==p2){ err.textContent="Passwords do not match"; err.classList.remove("hidden"); return; }
  try{
    const r=await fetch("/auth/password/confirm",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reset_id:prometResetId,code:document.getElementById("resetCode").value.trim(),new_password:p1})});
    const data=await r.json();
    if(!r.ok) throw new Error(data.detail || "Could not reset password");
    cancelPasswordReset();
    document.getElementById("authEmail").value=document.getElementById("resetEmail").value.trim();
    const e0=document.getElementById("err-0"); e0.textContent="Password updated. Sign in with your new password."; e0.classList.remove("hidden");
  }catch(e){ err.textContent=e.message; err.classList.remove("hidden"); }
}
</script>
'''
    html = html.replace("</body>", reset_js + "\n</body>")
    return html


def wizard():
    return HTMLResponse(
        _render_wizard(),
        headers={"Cache-Control":"no-store, max-age=0","X-PROMET-UI":"filing-wizard"}
    )


@app.get("/", include_in_schema=False)
def index():
    return wizard()


@app.get("/app", include_in_schema=False)
def app_page():
    return wizard()


@app.get("/health")
def health():
    return {
        "status":"ok",
        "service":"ura-promet",
        "legacy_service":"tax-filing",
        "version":"0.4.0",
        "ui":"filing-wizard",
        "mfa":"email-otp" if auth._smtp_ready() else "totp-fallback",
        "email_otp_configured": auth._smtp_ready(),
        "password_reset":"email-code" if auth._smtp_ready() else "unavailable",
        "live_transmission":False,
    }
