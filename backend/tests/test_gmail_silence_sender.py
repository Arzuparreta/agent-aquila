"""``gmail_silence_sender``: no SPAM in filter actions; optional thread spam via modify."""

from __future__ import annotations

import pytest

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services import agent_service
from app.services.agent_service import AgentService


class _FakeGmail:
    def __init__(self) -> None:
        self.create_filter_calls: list[dict] = []
        self.modify_thread_calls: list[tuple] = []
        self.modify_message_calls: list[tuple] = []

    async def create_filter(self, *, criteria: dict, action: dict) -> dict:
        self.create_filter_calls.append({"criteria": criteria, "action": action})
        return {"id": "filter-1"}

    async def modify_thread(
        self,
        thread_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        self.modify_thread_calls.append(
            (thread_id, add_label_ids, remove_label_ids)
        )
        return {"id": thread_id}

    async def modify_message(
        self,
        message_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        self.modify_message_calls.append(
            (message_id, add_label_ids, remove_label_ids)
        )
        return {"id": message_id}


@pytest.mark.asyncio
async def test_silence_spam_filter_never_adds_spam_label(
    db_session,
    aquila_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = ConnectorConnection(
        user_id=aquila_user.id,
        provider="google_gmail",
        label="Gmail",
        credentials_encrypted="{}",
    )
    db_session.add(row)
    await db_session.flush()

    fake = _FakeGmail()

    async def fake_gmail_client(db, conn):  # noqa: ARG001
        return fake

    monkeypatch.setattr(agent_service, "_gmail_client", fake_gmail_client)

    out = await AgentService._tool_gmail_silence_sender(
        db_session,
        aquila_user,
        {"email": "annoy@spam.test", "mode": "spam", "connection_id": row.id},
    )
    assert out["ok"] is True
    assert out["moved_to_spam"] is False
    assert fake.modify_thread_calls == []
    assert fake.modify_message_calls == []
    assert len(fake.create_filter_calls) == 1
    action = fake.create_filter_calls[0]["action"]
    assert "addLabelIds" not in action
    assert action.get("removeLabelIds") == ["INBOX", "UNREAD"]


@pytest.mark.asyncio
async def test_silence_spam_with_thread_modifies_before_filter(
    db_session,
    aquila_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = ConnectorConnection(
        user_id=aquila_user.id,
        provider="google_gmail",
        label="Gmail",
        credentials_encrypted="{}",
    )
    db_session.add(row)
    await db_session.flush()

    fake = _FakeGmail()

    async def fake_gmail_client(db, conn):  # noqa: ARG001
        return fake

    monkeypatch.setattr(agent_service, "_gmail_client", fake_gmail_client)

    out = await AgentService._tool_gmail_silence_sender(
        db_session,
        aquila_user,
        {
            "email": "annoy@spam.test",
            "mode": "spam",
            "thread_id": "t-99",
            "connection_id": row.id,
        },
    )
    assert out["ok"] is True
    assert out["moved_to_spam"] is True
    # modify (spam) before create_filter
    assert fake.modify_thread_calls[0] == (
        "t-99",
        ["SPAM"],
        ["INBOX"],
    )
    assert fake.create_filter_calls[0]["action"] == {
        "removeLabelIds": ["INBOX", "UNREAD"],
    }
