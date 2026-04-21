"""Tests for split ranking / auxiliary LLM provider (classify_model row vs active chat)."""

from __future__ import annotations

import pytest

from app.models.user import User
from app.services.ai_provider_config_service import AIProviderConfigService, ProviderConfigUpsert
from app.services.user_ai_settings_service import UserAISettingsService


@pytest.mark.asyncio
async def test_resolve_ranking_runtime_explicit_provider(db_session) -> None:
    user = User(email="rank-split@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "openai_compatible",
        ProviderConfigUpsert(
            base_url="https://proxy.example/v1",
            chat_model="gpt-proxy",
            classify_model="gpt-mini",
        ),
    )
    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(
            base_url="http://localhost:11434",
            chat_model="qwen",
            classify_model="phi",
        ),
    )
    await AIProviderConfigService.set_active(db_session, user, "openai_compatible")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.ranking_provider_kind = "ollama"
    await db_session.flush()

    ctx = await AIProviderConfigService.resolve_ranking_runtime(db_session, user)
    assert ctx is not None
    assert ctx.provider_kind == "ollama"
    assert ctx.default_model == "phi"
    assert "localhost:11434" in (ctx.base_url or "")


@pytest.mark.asyncio
async def test_resolve_ranking_runtime_null_matches_active(db_session) -> None:
    user = User(email="rank-active@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(
            chat_model="qwen",
            classify_model="phi",
        ),
    )
    await AIProviderConfigService.set_active(db_session, user, "ollama")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.ranking_provider_kind = None
    await db_session.flush()

    ctx = await AIProviderConfigService.resolve_ranking_runtime(db_session, user)
    assert ctx is not None
    assert ctx.default_model == "phi"


@pytest.mark.asyncio
async def test_resolve_ranking_falls_back_to_chat_when_classify_empty(db_session) -> None:
    user = User(email="rank-fallback@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(chat_model="qwen"),
    )
    await AIProviderConfigService.set_active(db_session, user, "ollama")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.ranking_provider_kind = None
    await db_session.flush()

    ctx = await AIProviderConfigService.resolve_ranking_runtime(db_session, user)
    assert ctx is not None
    assert ctx.default_model == "qwen"


@pytest.mark.asyncio
async def test_delete_config_clears_ranking_pointer(db_session) -> None:
    user = User(email="rank-del@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "openai_compatible",
        ProviderConfigUpsert(
            base_url="https://proxy.example/v1",
            chat_model="m",
            classify_model="c",
        ),
    )
    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(chat_model="qwen"),
    )
    await AIProviderConfigService.set_active(db_session, user, "openai_compatible")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.ranking_provider_kind = "ollama"
    await db_session.flush()

    await AIProviderConfigService.delete_config(db_session, user, "ollama")
    await db_session.flush()
    await db_session.refresh(prefs)
    assert prefs.ranking_provider_kind is None
