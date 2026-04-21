"""Tests for split embedding provider (chat vs agent-memory embeddings)."""

from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from app.models.user import User
from app.services.ai_provider_config_service import AIProviderConfigService, ProviderConfigUpsert
from app.services.embedding_client import EmbeddingCallContext, EmbeddingClient
from app.services.user_ai_settings_service import UserAISettingsService


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install_embedding_mock(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    captured: list[httpx.Request] = []

    def _wrap(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    def _factory(*_args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(_wrap), **kwargs)

    import app.services.embedding_client as ec

    monkeypatch.setattr(ec.httpx, "AsyncClient", _factory)
    return captured


@pytest.mark.asyncio
async def test_resolve_embedding_runtime_explicit_provider(db_session) -> None:
    user = User(email="embed-split@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    # Optional API key — no envelope encryption needed.
    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "openai_compatible",
        ProviderConfigUpsert(
            base_url="https://proxy.example/v1",
            chat_model="gpt-proxy",
            embedding_model="embed-proxy",
        ),
    )
    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(
            base_url="http://localhost:11434",
            chat_model="qwen",
            embedding_model="nomic-embed-text",
        ),
    )
    await AIProviderConfigService.set_active(db_session, user, "openai_compatible")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.embedding_provider_kind = "ollama"
    await db_session.flush()

    ctx = await AIProviderConfigService.resolve_embedding_runtime(db_session, user)
    assert ctx is not None
    assert ctx.provider_kind == "ollama"
    assert ctx.embedding_model == "nomic-embed-text"
    assert "localhost:11434" in (ctx.base_url or "")


@pytest.mark.asyncio
async def test_resolve_embedding_runtime_null_matches_active(db_session) -> None:
    user = User(email="embed-active@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(
            embedding_model="nomic-embed-text",
        ),
    )
    await AIProviderConfigService.set_active(db_session, user, "ollama")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.embedding_provider_kind = None
    await db_session.flush()

    ctx = await AIProviderConfigService.resolve_embedding_runtime(db_session, user)
    assert ctx is not None
    assert ctx.embedding_model == "nomic-embed-text"


@pytest.mark.asyncio
async def test_delete_config_clears_embedding_pointer(db_session) -> None:
    user = User(email="embed-del@example.com", hashed_password="x", full_name="t")
    db_session.add(user)
    await db_session.flush()

    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "openai_compatible",
        ProviderConfigUpsert(
            base_url="https://proxy.example/v1",
            chat_model="m",
            embedding_model="e",
        ),
    )
    await AIProviderConfigService.upsert_config(
        db_session,
        user,
        "ollama",
        ProviderConfigUpsert(embedding_model="nomic-embed-text"),
    )
    await AIProviderConfigService.set_active(db_session, user, "openai_compatible")
    prefs = await UserAISettingsService.get_or_create(db_session, user)
    prefs.embedding_provider_kind = "ollama"
    await db_session.flush()

    await AIProviderConfigService.delete_config(db_session, user, "ollama")
    await db_session.flush()
    await db_session.refresh(prefs)
    assert prefs.embedding_provider_kind is None


@pytest.mark.asyncio
async def test_embed_texts_uses_context_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/embeddings" in str(request.url)
        body = request.content.decode() if request.content else ""
        assert "nomic-embed-text" in body
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.3, 0.4]}]},
        )

    _install_embedding_mock(monkeypatch, handler)
    ctx = EmbeddingCallContext(
        provider_kind="ollama",
        base_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        extras=None,
        api_key=None,
    )
    vecs = await EmbeddingClient.embed_texts(ctx, ["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 2
