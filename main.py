from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

import auth
import tax_filing
import tax_advanced

app = FastAPI(title="UNG-PROMET", description="Public Revenue Operations, Management & Electronic Taxation", version="0.2.1")
_origins = [x.strip() for x in os.environ.get("TAX_CORS_ORIGINS", "http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router)
app.include_router(tax_filing.router)
app.include_router(tax_advanced.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def wizard():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), media_type="text/html", headers={"Cache-Control":"no-store, max-age=0","X-PROMET-UI":"filing-wizard"})


@app.get("/", include_in_schema=False)
def index():
    return wizard()


@app.get("/app", include_in_schema=False)
def app_page():
    return wizard()


@app.get("/health")
def health():
    return {"status":"ok","service":"ung-promet","legacy_service":"tax-filing","version":"0.2.1","ui":"filing-wizard","live_transmission":False}
