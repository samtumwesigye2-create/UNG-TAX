from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import auth, auth_store, password_reset, tax_filing, tax_advanced, ops, ops_cases_notices, ops_reports
from password_reset_ui import inject_password_reset_ui

app=FastAPI(title="URA-PROMET",description="Public Revenue Operations, Management & Electronic Taxation",version="0.7.2")
_origins=[x.strip() for x in os.environ.get("TAX_CORS_ORIGINS","http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=_origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE"],allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router); app.include_router(password_reset.router); app.include_router(tax_filing.router); app.include_router(tax_advanced.router); app.include_router(ops.router); app.include_router(ops_cases_notices.router); app.include_router(ops_reports.router)
STATIC_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),"static"); app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")

def _render_wizard():
    with open(os.path.join(STATIC_DIR,"index.html"),"r",encoding="utf-8") as f: html=f.read()
    html=inject_password_reset_ui(html)
    banner='<div style="background:#102b46;color:white;padding:10px 16px;font-family:-apple-system,sans-serif"><b>URA-PROMET</b> · <a href="/taxpayer" style="color:white">Taxpayer Portal</a> · <a href="/revenue-staff" style="color:white">Revenue Staff</a> · <a href="/revenue" style="color:white">Revenue Admin</a></div>'
    return banner+html

def wizard():return HTMLResponse(_render_wizard(),headers={"Cache-Control":"no-store, max-age=0","X-PROMET-UI":"filing-wizard"})
@app.get("/",include_in_schema=False)
def index():return wizard()
@app.get("/app",include_in_schema=False)
def app_page():return wizard()
@app.get("/taxpayer",include_in_schema=False)
def taxpayer_portal():return FileResponse(os.path.join(STATIC_DIR,"taxpayer.html"))
@app.get("/revenue-staff",include_in_schema=False)
def revenue_staff_portal():return FileResponse(os.path.join(STATIC_DIR,"revenue-staff.html"))
@app.get("/revenue",include_in_schema=False)
def revenue_admin_portal():return FileResponse(os.path.join(STATIC_DIR,"revenue.html"))
@app.get("/operations",include_in_schema=False)
def revenue_operations_workspace():return FileResponse(os.path.join(STATIC_DIR,"ops-workspace.html"))
@app.get("/health")
def health():
    return {"status":"ok","service":"ura-promet","legacy_service":"UNG-TAX","version":"0.7.2","ui":"operational-workspaces","role_portals":["taxpayer","revenue_staff","revenue_admin"],"auth_storage":auth_store.backend_name(),"mfa":"email-otp" if auth._smtp_ready() else "totp-fallback","email_otp_configured":auth._smtp_ready(),"live_transmission":False,"operations_api":"/ops","operations_workspace":"/operations","password_reset_ui":True}
