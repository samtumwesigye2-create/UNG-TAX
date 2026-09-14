import os

import pytest
from fastapi import HTTPException


def test_revenue_staff_is_operational_manager():
    from ops_auth import require_revenue_user
    user = {"id": "u1", "role": "revenue_staff"}
    assert require_revenue_user(user)["id"] == "u1"


def test_taxpayer_cannot_enter_ops():
    from ops_auth import require_revenue_user
    with pytest.raises(HTTPException) as exc:
        require_revenue_user({"id": "u2", "role": "taxpayer"})
    assert exc.value.status_code == 403


def test_only_admin_passes_admin_guard():
    from ops_auth import require_revenue_admin
    with pytest.raises(HTTPException) as exc:
        require_revenue_admin({"id": "u3", "role": "revenue_staff"})
    assert exc.value.status_code == 403
    assert require_revenue_admin({"id": "u4", "role": "revenue_admin"})["id"] == "u4"


def test_audit_event_is_append_only_and_queryable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMET_OPS_DB", str(tmp_path / "ops.db"))
    import importlib
    import ops_store
    import ops_audit
    importlib.reload(ops_store)
    importlib.reload(ops_audit)

    event_id = ops_audit.write_audit_event(
        actor_id="u1",
        actor_role="revenue_staff",
        action="taxpayer.update",
        entity_type="taxpayer",
        entity_id="t1",
        taxpayer_id="t1",
        before={"status": "active"},
        after={"status": "suspended"},
        reason="identity review",
        correlation_id="c1",
    )
    events = ops_audit.list_audit_events(entity_type="taxpayer", entity_id="t1")
    assert any(e["id"] == event_id for e in events)
    assert events[0]["before"] == {"status": "active"}
    assert events[0]["after"] == {"status": "suspended"}
