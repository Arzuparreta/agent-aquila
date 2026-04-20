"""Gmail HTTP proxy: snake_case bodies forward to Gmail REST (mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.deps import get_current_user
from app.main import app
from app.routes import gmail as gmail_routes


class _RecordingGmail:
    def __init__(self) -> None:
        self.modify_thread_calls: list[tuple[str, list[str] | None, list[str] | None]] = []
        self.modify_message_calls: list[tuple[str, list[str] | None, list[str] | None]] = []

    async def modify_thread(
        self,
        thread_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        self.modify_thread_calls.append((thread_id, add_label_ids, remove_label_ids))
        return {"id": thread_id}

    async def modify_message(
        self,
        message_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        self.modify_message_calls.append((message_id, add_label_ids, remove_label_ids))
        return {"id": message_id}


@pytest.fixture
def gmail_route_client(monkeypatch: pytest.MonkeyPatch):
    recording = _RecordingGmail()

    async def fake_resolve(
        db, user, connection_id: int | None
    ):  # noqa: ARG001
        return SimpleNamespace(id=99, user_id=user.id, provider="google_gmail")

    async def fake_client_for(db, row):  # noqa: ARG001
        return recording

    monkeypatch.setattr(gmail_routes, "_resolve_gmail_connection", fake_resolve)
    monkeypatch.setattr(gmail_routes, "_client_for", fake_client_for)

    async def fake_user():
        u = SimpleNamespace()
        u.id = 1
        u.email = "route-test@example.com"
        return u

    async def fake_db():
        yield MagicMock()

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield recording
    app.dependency_overrides.clear()


def test_post_thread_modify_maps_snake_case_to_client(gmail_route_client: _RecordingGmail) -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/gmail/threads/th-xyz/modify",
        json={"add_label_ids": ["SPAM"], "remove_label_ids": ["INBOX"]},
    )
    assert r.status_code == 200
    assert gmail_route_client.modify_thread_calls == [
        ("th-xyz", ["SPAM"], ["INBOX"]),
    ]


def test_post_message_modify_maps_snake_case_to_client(gmail_route_client: _RecordingGmail) -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/gmail/messages/msg-abc/modify",
        json={"remove_label_ids": ["UNREAD"]},
    )
    assert r.status_code == 200
    assert gmail_route_client.modify_message_calls == [
        ("msg-abc", None, ["UNREAD"]),
    ]
