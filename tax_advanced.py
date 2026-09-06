"""Advanced tax workflows. External OCR, banking, payroll and authority connectors remain opt-in integrations."""
from fastapi import APIRouter
router=APIRouter(prefix="/tax/advanced",tags=["tax-advanced"])
@router.get("/capabilities")
def capabilities():
    return {"ocr":"not_configured","banking":"not_configured","payroll":"not_configured","ura_live_filing":False,"irs_live_filing":False}
@router.get("/health")
def health(): return {"status":"ok","service":"tax-advanced"}
