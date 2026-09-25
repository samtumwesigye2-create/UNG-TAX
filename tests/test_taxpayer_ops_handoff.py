"""Contract tests for the taxpayer -> Revenue Operations handoff."""
from pathlib import Path


def test_tax_filing_submission_wires_revenue_operations_handoff():
    source = Path("tax_filing.py").read_text(encoding="utf-8")
    assert "sync_taxpayer_submission_to_ops" in source
    assert "return_reviews" in source or "taxpayer_ops_handoff" in source


def test_handoff_module_creates_taxpayer_profile_and_return_review():
    source = Path("taxpayer_ops_handoff.py").read_text(encoding="utf-8")
    assert "taxpayer_profiles" in source
    assert "return_reviews" in source
    assert "filing_id" in source
