"""Unit tests for the AI provider adapters.

Each test patches ``httpx.AsyncClient`` with a ``MockTransport`` so no real
network I/O occurs. Focuses on the shape of the response and on how the
adapter normalizes error cases.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from app.services.ai_providers import adapters
from app.services.ai_providers.adapters import ProviderConfig, safe_list_models
from app.services.ai_providers.adapters import test_connection as run_test_connection


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Replace ``httpx.AsyncClient`` inside the adapter module with a mock.

    Returns the list of captured requests so tests can assert URLs/headers.
    """
    captured: list[httpx.Request] = []

    def _wrap(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    def _factory(*_args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(_wrap), **kwargs)

    monkeypatch.setattr(adapters.httpx, "AsyncClient", _factory)
    return captured


# --- OpenAI-like --------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_list_models_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.openai.com/v1/models"
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o-mini"},
                    {"id": "text-embedding-3-small"},
                ]
            },
        )

    _install(monkeypatch, handler)
    cfg = ProviderConfig(provider_id="openai", api_key="sk-test")
    result = await run_test_connection(cfg)
    assert result.ok is True
    assert "OpenAI" in result.message

    models, err = await safe_list_models(cfg)
    assert err is None
    ids = {m.id for m in models}
    assert ids == {"gpt-4o-mini", "text-embedding-3-small"}
    caps = {m.id: m.capability for m in models}
    assert caps["text-embedding-3-small"] == "embedding"
    assert caps["gpt-4o-mini"] == "chat"


@pytest.mark.asyncio
async def test_openai_invalid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    _install(monkeypatch, handler)
    result = await run_test_connection(ProviderConfig(provider_id="openai", api_key="sk-bad"))
    assert result.ok is False
    assert result.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_openai_requires_api_key() -> None:
    result = await run_test_connection(ProviderConfig(provider_id="openai", api_key=""))
    assert result.ok is False
    assert result.code == "missing_field"


# --- Ollama -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:11434/api/tags"
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.1"}, {"name": "nomic-embed-text"}]},
        )

    _install(monkeypatch, handler)
    cfg = ProviderConfig(provider_id="ollama", base_url="http://localhost:11434")
    result = await run_test_connection(cfg)
    assert result.ok is True

    models, err = await safe_list_models(cfg)
    assert err is None
    assert {m.id for m in models} == {"llama3.1", "nomic-embed-text"}
    caps = {m.id: m.capability for m in models}
    assert caps["nomic-embed-text"] == "embedding"


@pytest.mark.asyncio
async def test_ollama_strips_v1_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"models": []})

    _install(monkeypatch, handler)
    cfg = ProviderConfig(provider_id="ollama", base_url="http://localhost:11434/v1")
    await run_test_connection(cfg)
    assert requested == ["http://localhost:11434/api/tags"]


@pytest.mark.asyncio
async def test_ollama_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(monkeypatch, handler)
    result = await run_test_connection(ProviderConfig(provider_id="ollama", base_url="http://localhost:11434"))
    assert result.ok is False
    assert result.code == "network"


# --- Anthropic ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_list_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.anthropic.com/v1/models"
        assert request.headers["x-api-key"] == "ak-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-3-5-sonnet-latest", "display_name": "Claude 3.5 Sonnet"},
                    {"id": "claude-3-haiku"},
                ]
            },
        )

    _install(monkeypatch, handler)
    cfg = ProviderConfig(provider_id="anthropic", api_key="ak-test")
    models, err = await safe_list_models(cfg)
    assert err is None
    assert models[0].label == "Claude 3.5 Sonnet"
    assert all(m.capability == "chat" for m in models)


# --- OpenRouter ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_sends_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})

    _install(monkeypatch, handler)
    cfg = ProviderConfig(
        provider_id="openrouter",
        api_key="or-test",
        extras={"openrouter_referer": "https://example.com", "openrouter_title": "Agent Aquila"},
    )
    result = await run_test_connection(cfg)
    assert result.ok is True
    req = captured[0]
    assert req.headers["Referer"] == "https://example.com"
    assert req.headers["X-Title"] == "Agent Aquila"


# --- Azure --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_lists_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/deployments"
        assert request.url.params.get("api-version") == "2024-06-01"
        assert request.headers["api-key"] == "az-key"
        return httpx.Response(
            200,
            json={"data": [{"id": "prod-chat", "model": "gpt-4o"}, {"id": "prod-embed", "model": "text-embedding-3-small"}]},
        )

    _install(monkeypatch, handler)
    cfg = ProviderConfig(
        provider_id="azure_openai",
        api_key="az-key",
        base_url="https://my-resource.openai.azure.com",
        extras={"api_version": "2024-06-01"},
    )
    models, err = await safe_list_models(cfg)
    assert err is None
    ids = {m.id for m in models}
    assert ids == {"prod-chat", "prod-embed"}


@pytest.mark.asyncio
async def test_azure_missing_api_version() -> None:
    cfg = ProviderConfig(
        provider_id="azure_openai",
        api_key="az-key",
        base_url="https://my-resource.openai.azure.com",
        extras={},
    )
    result = await run_test_connection(cfg)
    assert result.ok is False
    assert result.code == "missing_field"


# --- LiteLLM / Custom ---------------------------------------------------------


@pytest.mark.asyncio
async def test_litellm_base_url_required() -> None:
    result = await run_test_connection(ProviderConfig(provider_id="litellm"))
    assert result.ok is False
    assert result.code == "missing_field"


@pytest.mark.asyncio
async def test_custom_openai_compatible_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/v1/models"
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    _install(monkeypatch, handler)
    cfg = ProviderConfig(provider_id="openai_compatible", base_url="https://example.com/v1")
    result = await run_test_connection(cfg)
    assert result.ok is True


# --- Timeouts -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    _install(monkeypatch, handler)
    result = await run_test_connection(ProviderConfig(provider_id="openai", api_key="x"))
    assert result.ok is False
    assert result.code == "timeout"
