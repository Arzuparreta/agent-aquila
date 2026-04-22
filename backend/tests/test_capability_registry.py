from __future__ import annotations

from app.services.capability_registry import describe_capabilities, proposal_kind_registry
from app.services.pending_execution_service import preview_for_proposal_kind


def test_proposal_kind_registry_covers_gated_kinds() -> None:
    reg = proposal_kind_registry()
    assert set(reg.keys()) == {
        "email_send",
        "email_reply",
        "whatsapp_send",
        "youtube_upload",
    }
    assert reg["email_send"]["risk_tier"] == "external_write"
    assert reg["email_send"]["auto_apply"] is False


def test_describe_capabilities_shape() -> None:
    cap = describe_capabilities()
    assert "proposal_kinds" in cap
    assert isinstance(cap["proposal_kinds"], dict)


def test_preview_for_email_send() -> None:
    p = preview_for_proposal_kind(
        "email_send",
        {
            "connection_id": 7,
            "to": ["alice@example.com"],
            "subject": "Hello",
            "body": "Hey there",
        },
    )
    assert p["action"] == "email_send"
    assert p["to"] == ["alice@example.com"]
    assert p["subject"] == "Hello"
    assert p["body_preview"].startswith("Hey")


def test_preview_for_whatsapp_send() -> None:
    p = preview_for_proposal_kind(
        "whatsapp_send",
        {
            "connection_id": 3,
            "to_e164": "+34123456789",
            "body": "Hello from approval card",
        },
    )
    assert p["action"] == "whatsapp_send"
    assert p["to_e164"] == "+34123456789"
    assert p["body_preview"] == "Hello from approval card"
