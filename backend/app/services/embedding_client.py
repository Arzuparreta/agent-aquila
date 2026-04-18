from __future__ import annotations

from typing import Any

import httpx

from app.models.user_ai_settings import UserAISettings


def _api_root(settings_row: UserAISettings) -> str:
    if settings_row.base_url:
        return settings_row.base_url.rstrip("/")
    if settings_row.provider_kind == "openrouter":
        return "https://openrouter.ai/api/v1"
    return "https://api.openai.com/v1"


def _extra_headers(settings_row: UserAISettings) -> dict[str, str]:
    extras = settings_row.extras or {}
    headers: dict[str, str] = {}
    for key in ("openrouter_referer", "http_referer", "referer"):
        if key in extras and extras[key]:
            headers["Referer"] = str(extras[key])
    if title := extras.get("openrouter_title"):
        headers["X-Title"] = str(title)
    return headers


class EmbeddingClient:
    @staticmethod
    async def embed_texts(api_key: str, settings_row: UserAISettings, texts: list[str]) -> list[list[float]]:
        root = _api_root(settings_row)
        url = f"{root}/embeddings"
        headers: dict[str, str] = {"Authorization": f"Bearer {api_key}", **_extra_headers(settings_row)}
        payload = {"model": settings_row.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]
