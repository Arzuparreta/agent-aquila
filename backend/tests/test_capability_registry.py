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
        "slack_post",
        "linear_comment",
        "telegram_message",
        "discord_message",
    }
    assert reg["email_send"]["risk_tier"] == "external_write"
    assert reg["email_send"]["auto_apply"] is False


def test_describe_capabilities_shape() -> None:
    cap = describe_capabilities()
    assert "proposal_kinds" in cap
    assert isinstance(cap["proposal_kinds"], dict)
    assert "connector_tool_provider_sets" in cap
    snap = cap["connector_tool_provider_sets"]
    assert isinstance(snap, dict)
    assert "calendar_tools" in snap
    assert "icloud_caldav" in snap["calendar_tools"]


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


def test_preview_for_linear_comment() -> None:
    p = preview_for_proposal_kind(
        "linear_comment",
        {"connection_id": 1, "issue_id": "abc", "body": "LGTM"},
    )
    assert p["action"] == "linear_comment"
    assert p["issue_id"] == "abc"


def test_preview_for_slack_post() -> None:
    p = preview_for_proposal_kind(
        "slack_post",
        {"connection_id": 2, "channel_id": "C0123", "text": "Hello channel"},
    )
    assert p["action"] == "slack_post"
    assert p["channel_id"] == "C0123"
    assert p["text_preview"] == "Hello channel"


def test_preview_for_telegram_message() -> None:
    p = preview_for_proposal_kind(
        "telegram_message",
        {"connection_id": 1, "chat_id": 99, "text": "Hi there"},
    )
    assert p["action"] == "telegram_message"
    assert p["chat_id"] == "99"
    assert p["text_preview"] == "Hi there"


def test_preview_for_discord_message() -> None:
    p = preview_for_proposal_kind(
        "discord_message",
        {"connection_id": 2, "channel_id": "123", "content": "Hello"},
    )
    assert p["action"] == "discord_message"
    assert p["channel_id"] == "123"
    assert p["content_preview"] == "Hello"
