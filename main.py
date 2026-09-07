from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

import auth
import tax_filing
import tax_advanced

app = FastAPI(title="UNG-PROMET", description="Public Revenue Operations, Management & Electronic Taxation", version="0.3.0")
_origins = [x.strip() for x in os.environ.get("TAX_CORS_ORIGINS", "http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router)
app.include_router(tax_filing.router)
app.include_router(tax_advanced.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _render_wizard() -> str:
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    if auth._smtp_ready():
        html = html.replace(
            "Scan this into an authenticator app (Google Authenticator, Authy, 1Password), then enter the 6-digit code it shows.",
            "We sent a 6-digit verification code to your email. Enter it below."
        )
        html = html.replace(
            '<div class="upload-box" id="mfaUriBox" style="word-break:break-all;font-family:monospace;font-size:0.72rem;"></div>',
            '<div class="upload-box" id="mfaUriBox">Check your email for your UNG-PROMET verification code.</div>'
        )
        html = html.replace("6-digit code from your authenticator app", "6-digit code sent to your email")
        html = html.replace("Set up two-factor authentication", "Verify your email")
        html = html.replace("Enter your authenticator code", "Enter the code sent to your email")
        html = html.replace("showMfaSetup(data.provisioning_uri, data.mfa_secret);", "showMfaSetup('email', '');")
        html = html.replace(
            '$("mfaUriBox").textContent = uri + "\\n\\n(Manual entry key: " + secret + ")";',
            '$("mfaUriBox").textContent = "Check your email for your UNG-PROMET verification code.";'
        )
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
        "service":"ung-promet",
        "legacy_service":"tax-filing",
        "version":"0.3.0",
        "ui":"filing-wizard",
        "mfa":"email-otp" if auth._smtp_ready() else "totp-fallback",
        "email_otp_configured": auth._smtp_ready(),
        "live_transmission":False,
    }
