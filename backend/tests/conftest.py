"""Shared pytest fixtures.

Includes optional Postgres fixtures for integration tests (pgvector schema).
Set ``TEST_DATABASE_URL`` or use the default host URL from ``.env.example``.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.user_ai_settings_service import UserAISettingsService

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://crm_user:crm_password@127.0.0.1:5433/crm_db",
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """One isolated transaction per test (rolled back). Requires migrated Postgres + pgvector."""
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        conn = await engine.connect()
    except Exception as exc:  # noqa: BLE001 — surface connection errors as skip
        await engine.dispose()
        pytest.skip(
            f"Postgres unreachable ({exc!s}). "
            "Try: docker compose up -d db && cd backend && alembic upgrade head"
        )
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def crm_user(db_session: AsyncSession) -> User:
    """User with Ollama provider so semantic search does not require an API key."""
    user = User(
        email=f"agent-tools-{uuid.uuid4().hex}@example.com",
        hashed_password="not-used-in-these-tests",
        full_name="Agent Tools Test User",
    )
    db_session.add(user)
    await db_session.flush()
    settings_row = await UserAISettingsService.get_or_create(db_session, user)
    settings_row.provider_kind = "ollama"
    settings_row.ai_disabled = False
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def agent_run(db_session: AsyncSession, crm_user: User) -> AgentRun:
    run = AgentRun(user_id=crm_user.id, status="running", user_message="tool test")
    db_session.add(run)
    await db_session.flush()
    return run
