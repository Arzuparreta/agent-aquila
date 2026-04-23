"""HTTP-level checks for dashboard + chat flows (catches schema drift and route regressions).

These tests call the FastAPI app the same way the Next.js UI does, with dependency
overrides so no JWT or second DB session is required. They require a migrated Postgres
(see ``TEST_DATABASE_URL`` in ``conftest.py``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.main import app
from app.models.agent_run import AgentTraceEvent
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.schemas.agent import AgentRunRead
from app.services.chat_service import append_message
from app.services.llm_client import ChatResponse, ChatToolCall


@pytest_asyncio.fixture
async def chat_thread(db_session: AsyncSession, aquila_user: User) -> ChatThread:
    t = ChatThread(
        user_id=aquila_user.id,
        kind="general",
        entity_type=None,
        entity_id=None,
        title="API integration thread",
        is_default=False,
    )
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.mark.asyncio
async def test_dashboard_endpoints_and_chat_message(
    db_session: AsyncSession,
    aquila_user: User,
    chat_thread: ChatThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    monkeypatch.setattr(settings, "agent_async_runs", False)

    async def fake_native(*args: object, **kwargs: object) -> ChatResponse:
        return ChatResponse(
            content="",
            tool_calls=[
                ChatToolCall(
                    id="call_it",
                    name="final_answer",
                    arguments={"text": "Integration test reply"},
                )
            ],
        )

    monkeypatch.setattr("app.services.agent_service.chat_turn_native", fake_native)
    monkeypatch.setattr(
        "app.services.agent_service.resolve_effective_mode",
        lambda *a, **k: "native",
    )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r_ai = await ac.get("/api/v1/ai/settings")
            assert r_ai.status_code == 200, r_ai.text

            r_d1 = await ac.get("/api/v1/dashboard/status")
            assert r_d1.status_code == 200, r_d1.text

            r_d2 = await ac.get("/api/v1/dashboard/metrics")
            assert r_d2.status_code == 200, r_d2.text
            metrics_payload = r_d2.json()
            assert "agent_runs_needs_attention_last_24h" in metrics_payload

            r_runs = await ac.get("/api/v1/agent/runs?limit=5")
            assert r_runs.status_code == 200, r_runs.text

            r_onb = await ac.get("/api/v1/onboarding/status")
            assert r_onb.status_code == 200, r_onb.text

            r_msg = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages",
                json={"content": "Hello from API integration test", "references": []},
            )
            assert r_msg.status_code == 200, r_msg.text
            payload = r_msg.json()
            asst = payload.get("assistant_message") or {}
            content = str(asst.get("content") or "")
            assert "Integration test reply" in content
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_run_returns_attention_metadata_for_needs_attention(
    db_session: AsyncSession,
    aquila_user: User,
    agent_run,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    agent_run.status = "needs_attention"
    agent_run.error = "Run requires attention."
    agent_run.root_trace_id = "0123456789abcdef0123456789abcdef"
    db_session.add(
        AgentTraceEvent(
            run_id=agent_run.id,
            schema_version=1,
            event_type="tool.started",
            trace_id=agent_run.root_trace_id,
            payload={"tool": "gmail_list_messages"},
        )
    )
    await db_session.commit()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r_run = await ac.get(f"/api/v1/agent/runs/{agent_run.id}")
            assert r_run.status_code == 200, r_run.text
            payload = r_run.json()
            assert payload.get("status") == "needs_attention"
            attention = payload.get("attention") or {}
            assert attention.get("stage") == "waiting_tool"
            assert isinstance(attention.get("hint"), str) and attention.get("hint")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_chat_send_idempotency_key_deduplicates_retries(
    db_session: AsyncSession,
    aquila_user: User,
    chat_thread: ChatThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    monkeypatch.setattr(settings, "agent_async_runs", False)

    async def fake_native(*args: object, **kwargs: object) -> ChatResponse:
        return ChatResponse(
            content="",
            tool_calls=[
                ChatToolCall(
                    id="call_it",
                    name="final_answer",
                    arguments={"text": "Idempotent reply"},
                )
            ],
        )

    monkeypatch.setattr("app.services.agent_service.chat_turn_native", fake_native)
    monkeypatch.setattr(
        "app.services.agent_service.resolve_effective_mode",
        lambda *a, **k: "native",
    )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            key = "test-idem-send-1"
            first = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages",
                json={
                    "content": "Please schedule tomorrow's check-in",
                    "references": [],
                    "idempotency_key": key,
                },
            )
            assert first.status_code == 200, first.text
            second = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages",
                json={
                    "content": "Please schedule tomorrow's check-in",
                    "references": [],
                    "idempotency_key": key,
                },
            )
            assert second.status_code == 200, second.text
            p1 = first.json()
            p2 = second.json()
            assert p1["user_message"]["id"] == p2["user_message"]["id"]
            assert p1["assistant_message"]["id"] == p2["assistant_message"]["id"]

            rows = await ac.get(f"/api/v1/threads/{chat_thread.id}/messages")
            assert rows.status_code == 200, rows.text
            messages = rows.json()
            user_rows = [m for m in messages if m["role"] == "user"]
            assert len(user_rows) == 1
            assert user_rows[0]["client_token"] == key
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_native_empty_without_tool_calls_becomes_failed_system_message(
    db_session: AsyncSession,
    aquila_user: User,
    chat_thread: ChatThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    monkeypatch.setattr(settings, "agent_async_runs", False)

    async def fake_native(*args: object, **kwargs: object) -> ChatResponse:
        return ChatResponse(content="", tool_calls=[])

    async def fake_prompted(*args: object, **kwargs: object):
        return ("", None, {}, None)

    monkeypatch.setattr("app.services.agent_service.chat_turn_native", fake_native)
    monkeypatch.setattr(
        "app.services.agent_service.LLMClient.chat_completion_full",
        fake_prompted,
    )
    monkeypatch.setattr(
        "app.services.agent_service.resolve_effective_mode",
        lambda *a, **k: "native",
    )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r_msg = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages",
                json={"content": "Marca ese correo como spam", "references": []},
            )
            assert r_msg.status_code == 200, r_msg.text
            payload = r_msg.json()
            asst = payload.get("assistant_message") or {}
            assert asst.get("role") == "system"
            assert "empty response without tool calls" in str(asst.get("content") or "").lower()

            run_id = asst.get("agent_run_id")
            assert isinstance(run_id, int)
            r_run = await ac.get(f"/api/v1/agent/runs/{run_id}")
            assert r_run.status_code == 200, r_run.text
            run_payload = r_run.json()
            assert run_payload.get("status") == "failed"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_retry_endpoint_idempotency_header_deduplicates(
    db_session: AsyncSession,
    aquila_user: User,
    chat_thread: ChatThread,
    agent_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    monkeypatch.setattr(settings, "agent_async_runs", False)
    async def fake_preflight(*args: object, **kwargs: object):
        return None

    monkeypatch.setattr("app.services.agent_service.AgentService.run_agent_invalid_preflight", fake_preflight)

    async def fake_run_agent(*args: object, **kwargs: object) -> AgentRunRead:
        return AgentRunRead(
            id=agent_run.id,
            status="completed",
            user_message="replay",
            assistant_reply="Retry completed",
            error=None,
            root_trace_id=None,
            chat_thread_id=chat_thread.id,
            turn_profile="user_chat",
            steps=[],
            pending_proposals=[],
        )

    monkeypatch.setattr("app.services.agent_service.AgentService.run_agent", fake_run_agent)

    user_msg = await append_message(db_session, chat_thread, role="user", content="Do the thing")
    failed_msg = await append_message(db_session, chat_thread, role="system", content="Tool provider failed")
    await db_session.commit()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            key = "test-idem-retry-1"
            first = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages/{failed_msg.id}/retry",
                headers={"X-Idempotency-Key": key},
            )
            assert first.status_code == 200, first.text
            second = await ac.post(
                f"/api/v1/threads/{chat_thread.id}/messages/{failed_msg.id}/retry",
                headers={"X-Idempotency-Key": key},
            )
            assert second.status_code == 200, second.text
            p1 = first.json()
            p2 = second.json()
            assert p1["assistant_message"]["id"] == p2["assistant_message"]["id"]
            assert p1["user_message"]["id"] == user_msg.id

            rows = await ac.get(f"/api/v1/threads/{chat_thread.id}/messages")
            assert rows.status_code == 200, rows.text
            messages = rows.json()
            retry_rows = [m for m in messages if m["role"] in ("assistant", "system") and m.get("client_token") == key]
            assert len(retry_rows) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
