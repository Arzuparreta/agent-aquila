"""Unit + integration tests for auto-generated chat thread titles."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_thread import ChatThread
from app.models.user import User
from app.services.chat_thread_title_service import (
    is_thread_title_placeholder,
    maybe_generate_thread_title,
    sanitize_generated_title,
)
from app.services.llm_client import LLMClient


def test_is_thread_title_placeholder() -> None:
    assert is_thread_title_placeholder("New chat")
    assert is_thread_title_placeholder("NUEVO CHAT")
    assert is_thread_title_placeholder("General")
    assert is_thread_title_placeholder("")
    assert is_thread_title_placeholder(None)
    assert not is_thread_title_placeholder("Telegram")
    assert not is_thread_title_placeholder("Custom topic")


def test_sanitize_generated_title() -> None:
    assert sanitize_generated_title('  "Hello world"  ') == "Hello world"
    assert sanitize_generated_title("a\nb\nc") == "a b c"
    assert len(sanitize_generated_title("x" * 300)) == 255


@pytest.mark.asyncio
async def test_maybe_generate_thread_title_skips_non_general(
    db_session: AsyncSession, aquila_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    async def fake_llm(*args: object, **kwargs: object) -> str:
        called.append(True)
        return "Should not apply"

    monkeypatch.setattr(LLMClient, "chat_completion", fake_llm)

    thread = ChatThread(
        user_id=aquila_user.id,
        kind="entity",
        entity_type="gmail",
        entity_id=1,
        title="New chat",
    )
    db_session.add(thread)
    await db_session.flush()

    await maybe_generate_thread_title(
        db_session,
        aquila_user,
        thread.id,
        user_message="Hi",
        assistant_message="Hello",
        run_status="completed",
    )
    await db_session.refresh(thread)
    assert thread.title == "New chat"
    assert called == []


@pytest.mark.asyncio
async def test_maybe_generate_thread_title_updates_placeholder(
    db_session: AsyncSession, aquila_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_llm(*args: object, **kwargs: object) -> str:
        return '  "Plan de viaje a Madrid"  '

    monkeypatch.setattr(LLMClient, "chat_completion", fake_llm)

    thread = ChatThread(
        user_id=aquila_user.id,
        kind="general",
        title="Nuevo chat",
    )
    db_session.add(thread)
    await db_session.flush()

    await maybe_generate_thread_title(
        db_session,
        aquila_user,
        thread.id,
        user_message="Quiero ir a Madrid",
        assistant_message="Aquí tienes ideas.",
        run_status="completed",
    )
    await db_session.refresh(thread)
    assert thread.title == "Plan de viaje a Madrid"


@pytest.mark.asyncio
async def test_maybe_generate_thread_title_skips_failed_run(
    db_session: AsyncSession, aquila_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_llm(*args: object, **kwargs: object) -> str:
        return "Nope"

    monkeypatch.setattr(LLMClient, "chat_completion", fake_llm)

    thread = ChatThread(
        user_id=aquila_user.id,
        kind="general",
        title="New chat",
    )
    db_session.add(thread)
    await db_session.flush()

    await maybe_generate_thread_title(
        db_session,
        aquila_user,
        thread.id,
        user_message="Hi",
        assistant_message="Sorry, failed",
        run_status="failed",
    )
    await db_session.refresh(thread)
    assert thread.title == "New chat"
