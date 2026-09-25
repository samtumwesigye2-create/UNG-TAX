"""Bridge taxpayer filing records into URA-PROMET Revenue Operations."""
from __future__ import annotations

import json
import time
import uuid

from ops_store import get_ops_db


def sync_taxpayer_submission_to_ops(*, taxpayer: dict, filing: dict, calculation: dict | None = None) -> dict:
    """Idempotently expose a submitted taxpayer filing to Revenue Operations."""
    taxpayer_id = taxpayer["id"]
    filing_id = filing["id"]
    now = time.time()
    metadata = {"source": "tax_filing", "jurisdiction": taxpayer.get("jurisdiction")}
    payload = {
        "tax_year": filing.get("tax_year"),
        "filing_status": filing.get("filing_status"),
        "jurisdiction": filing.get("jurisdiction"),
        "calculation": calculation or {},
    }
    with get_ops_db() as db:
        profile = db.fetchone("SELECT id FROM taxpayer_profiles WHERE id=?", (taxpayer_id,))
        if not profile:
            db.execute(
                "INSERT INTO taxpayer_profiles(id,account_id,tin,name,email,status,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?,?)",
                (taxpayer_id, taxpayer.get("user_id"), taxpayer.get("tax_id_lookup"), taxpayer.get("legal_name") or "Taxpayer", taxpayer.get("email"), json.dumps(metadata, sort_keys=True), now, now),
            )
        else:
            db.execute(
                "UPDATE taxpayer_profiles SET name=?,email=?,metadata_json=?,updated_at=? WHERE id=?",
                (taxpayer.get("legal_name") or "Taxpayer", taxpayer.get("email"), json.dumps(metadata, sort_keys=True), now, taxpayer_id),
            )

        review = db.fetchone("SELECT * FROM return_reviews WHERE filing_id=?", (filing_id,))
        if not review:
            review_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO return_reviews(id,taxpayer_id,filing_id,return_type,period,state,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,'submitted',?,?,?)",
                (review_id, taxpayer_id, filing_id, "income_tax", str(filing.get("tax_year") or ""), json.dumps(payload, sort_keys=True), now, now),
            )
            review = db.fetchone("SELECT * FROM return_reviews WHERE id=?", (review_id,))
        return dict(review)
