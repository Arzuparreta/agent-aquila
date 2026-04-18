from __future__ import annotations

from app.services.capability_registry import describe_capabilities, proposal_kind_registry
from app.services.pending_execution_service import preview_for_proposal_kind


def test_proposal_kind_registry_covers_execution_kinds() -> None:
    reg = proposal_kind_registry()
    assert "create_deal" in reg
    assert "connector_teams_message" in reg
    assert reg["connector_email_send"]["risk_tier"] == "external_write"


def test_describe_capabilities_shape() -> None:
    cap = describe_capabilities()
    assert "proposal_kinds" in cap
    assert isinstance(cap["proposal_kinds"], dict)


def test_preview_for_create_deal() -> None:
    p = preview_for_proposal_kind(
        "create_deal",
        {"contact_id": 1, "title": "Festival", "status": "new"},
    )
    assert p["action"] == "create_deal"
    assert p["title"] == "Festival"
