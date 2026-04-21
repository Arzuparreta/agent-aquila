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
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.services.llm_client import ChatResponse, ChatToolCall


@pytest_asyncio.fixture
async def chat_thread(db_session: AsyncSession, crm_user: User) -> ChatThread:
    t = ChatThread(
        user_id=crm_user.id,
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
    crm_user: User,
    chat_thread: ChatThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return crm_user

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
