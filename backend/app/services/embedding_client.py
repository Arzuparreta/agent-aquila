from __future__ import annotations

from typing import Any

import httpx

from app.models.user_ai_settings import UserAISettings
from app.services.ai_providers import get_provider, normalize_provider_id


def _api_root(settings_row: UserAISettings) -> str:
    """Resolve the OpenAI-compatible base URL for this user's provider.

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


def _extra_headers(settings_row: UserAISettings) -> dict[str, str]:
    extras = settings_row.extras or {}
    headers: dict[str, str] = {}
    for key in ("openrouter_referer", "http_referer", "referer"):
        if key in extras and extras[key]:
            headers["Referer"] = str(extras[key])
    if title := extras.get("openrouter_title"):
        headers["X-Title"] = str(title)
    return headers


def _auth_headers(api_key: str, settings_row: UserAISettings) -> dict[str, str]:
    """Build the auth header for the provider.

    Azure OpenAI uses the ``api-key`` header; everything else here is
    OpenAI-compatible and takes a bearer token.
    """
    definition = get_provider(normalize_provider_id(settings_row.provider_kind))
    if definition and definition.auth_kind == "api-key-header":
        return {"api-key": api_key} if api_key else {}
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class EmbeddingClient:
    @staticmethod
    async def embed_texts(api_key: str, settings_row: UserAISettings, texts: list[str]) -> list[list[float]]:
        root = _api_root(settings_row)
        url = f"{root}/embeddings"
        headers: dict[str, str] = {**_auth_headers(api_key, settings_row), **_extra_headers(settings_row)}
        payload = {"model": settings_row.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]
