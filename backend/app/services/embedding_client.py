from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.services.ai_providers import get_provider, normalize_provider_id
from app.services.llm_errors import (
    LLMProviderError,
    from_http_status_error,
    from_transport_error,
)


@dataclass(frozen=True)
class EmbeddingCallContext:
    """HTTP + model fields for OpenAI-compatible ``/embeddings`` calls.

    Built from a :class:`~app.models.user_ai_provider_config.UserAIProviderConfig`
    row (see :func:`resolve_embedding_runtime`); not tied to the legacy
    ``user_ai_settings`` mirror so chat and embeddings can use different rows.
    """

    provider_kind: str
    base_url: str | None
    embedding_model: str
    extras: dict[str, Any] | None
    api_key: str | None


class _ProviderHttpLike(Protocol):
    """Shared shape for :class:`~app.models.user_ai_settings.UserAISettings` (chat) and :class:`EmbeddingCallContext` (embed)."""

    provider_kind: str
    base_url: str | None
    extras: dict[str, Any] | None


def _api_root(settings_row: _ProviderHttpLike) -> str:
    """Resolve the OpenAI-compatible base URL for this provider.

    The registry owns provider-default URLs; ``base_url`` on the row always
    wins when non-empty. Ollama exposes the OpenAI-compatible API under
    ``/v1`` while model listing uses the root URL; append ``/v1`` when missing so ``/chat/completions`` and ``/embeddings`` resolve correctly.
    """
    if settings_row.base_url:
        base = settings_row.base_url.rstrip("/")
    else:
        definition = get_provider(normalize_provider_id(settings_row.provider_kind))
        if definition and definition.default_base_url:
            base = definition.default_base_url.rstrip("/")
        else:
            base = "https://api.openai.com/v1"
    if normalize_provider_id(settings_row.provider_kind) == "ollama" and not base.endswith("/v1"):
        return f"{base}/v1"
    return base


def _extra_headers(settings_row: _ProviderHttpLike) -> dict[str, str]:
    extras = settings_row.extras or {}
    headers: dict[str, str] = {}
    for key in ("openrouter_referer", "http_referer", "referer"):
        if key in extras and extras[key]:
            headers["Referer"] = str(extras[key])
    if title := extras.get("openrouter_title"):
        headers["X-Title"] = str(title)
    return headers


def _auth_headers(api_key: str, settings_row: _ProviderHttpLike) -> dict[str, str]:
    """Build the auth header for the provider."""
    definition = get_provider(normalize_provider_id(settings_row.provider_kind))
    if definition and definition.auth_kind == "api-key-header":
        return {"api-key": api_key} if api_key else {}
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class EmbeddingClient:
    @staticmethod
    async def embed_texts(ctx: EmbeddingCallContext, texts: list[str]) -> list[list[float]]:
        root = _api_root(ctx)
        url = f"{root}/embeddings"
        api_key = ctx.api_key or ""
        headers: dict[str, str] = {**_auth_headers(api_key, ctx), **_extra_headers(ctx)}
        provider = normalize_provider_id(ctx.provider_kind)
        model = ctx.embedding_model
        payload = {"model": model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            raise from_http_status_error(exc, provider=provider, model=model) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise from_transport_error(exc, provider=provider, model=model) from exc
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(
                provider=provider,
                status_code=None,
                message=f"Unexpected error talking to {provider}.",
                hint="Check the backend logs for the full traceback.",
                detail=str(exc),
                model=model,
            ) from exc
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]
