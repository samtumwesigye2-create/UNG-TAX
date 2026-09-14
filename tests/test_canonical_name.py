from pathlib import Path
import main


def test_health_uses_only_ura_promet_identity():
    payload = main.health()
    assert payload["service"] == "URA-PROMET"
    assert "legacy_service" not in payload
    assert "UNG-TAX" not in str(payload)


def test_user_facing_source_does_not_identify_as_ung_tax():
    text = Path("main.py").read_text(encoding="utf-8")
    assert '"UNG-TAX"' not in text
