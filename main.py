"""
main.py — Standalone runnable entrypoint for the tax-filing app.

Run with:
    pip install fastapi uvicorn pydantic --break-system-packages
    uvicorn main:app --reload

Then open http://127.0.0.1:8000 in a browser.

To fold this into the existing platform instead of running it standalone,
skip this file and just `include_router(tax_filing.router)` on the main
app, the same way the other *_ops.py / *_replenishment.py modules are
mounted.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

import auth
import tax_filing
import tax_advanced

app = FastAPI(title="Tax Filing", version="0.2.0")
_origins = [x.strip() for x in os.environ.get("TAX_CORS_ORIGINS", "http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router)
app.include_router(tax_filing.router)
app.include_router(tax_advanced.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/health")
def health():
    return {"status":"ok","service":"tax-filing","version":"0.2.0","live_transmission":False}
