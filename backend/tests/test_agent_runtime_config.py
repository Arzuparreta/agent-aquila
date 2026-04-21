"""Unit tests for agent runtime merge + API round-trip."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.main import app
from app.models.user import User
from app.schemas.agent_runtime_config import AgentRuntimeConfigPartial
from app.services.agent_runtime_config_service import merge_patch_into_stored, merge_stored_with_env


def test_merge_stored_with_env_uses_defaults_when_no_overrides() -> None:
    r = merge_stored_with_env(None)
    assert r.agent_max_tool_steps == int(settings.agent_max_tool_steps)
    assert isinstance(r.agent_async_runs, bool)


def test_merge_stored_with_env_partial_override() -> None:
    r = merge_stored_with_env({"agent_max_tool_steps": 7})
    assert r.agent_max_tool_steps == 7
    r2 = merge_stored_with_env(None)
    assert r2.agent_max_tool_steps == int(settings.agent_max_tool_steps)


def test_merge_patch_into_stored_clears_with_null() -> None:
    base = merge_patch_into_stored(
        {"agent_max_tool_steps": 7},
        AgentRuntimeConfigPartial(agent_max_tool_steps=None),
    )
    assert "agent_max_tool_steps" not in base


def test_merge_patch_into_stored_updates() -> None:
    base = merge_patch_into_stored(
        {"agent_max_tool_steps": 3},
        AgentRuntimeConfigPartial(agent_async_runs=True),
    )
    assert base["agent_max_tool_steps"] == 3
    assert base["agent_async_runs"] is True


@pytest.mark.asyncio
async def test_patch_agent_runtime_roundtrip(
    db_session: AsyncSession,
    aquila_user: User,
) -> None:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_user() -> User:
        return aquila_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r0 = await ac.get("/api/v1/ai/settings")
            assert r0.status_code == 200, r0.text
            base_steps = r0.json()["agent_runtime"]["agent_max_tool_steps"]

            r1 = await ac.patch(
                "/api/v1/ai/settings",
                json={"agent_runtime": {"agent_max_tool_steps": 9}},
            )
            assert r1.status_code == 200, r1.text
            assert r1.json()["agent_runtime"]["agent_max_tool_steps"] == 9

            r2 = await ac.patch(
                "/api/v1/ai/settings",
                json={"agent_runtime": {"agent_max_tool_steps": None}},
            )
            assert r2.status_code == 200, r2.text
            assert r2.json()["agent_runtime"]["agent_max_tool_steps"] == base_steps

            r3 = await ac.patch("/api/v1/ai/settings", json={"agent_runtime": None})
            assert r3.status_code == 200, r3.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
