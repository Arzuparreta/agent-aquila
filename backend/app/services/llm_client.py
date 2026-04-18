from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.models.user_ai_settings import UserAISettings
from app.services.embedding_client import _api_root, _auth_headers, _extra_headers


class LLMClient:
    @staticmethod
    async def chat_completion(
        api_key: str,
        settings_row: UserAISettings,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        response_format_json: bool = False,
    ) -> str:
        root = _api_root(settings_row)
        url = f"{root}/chat/completions"
        headers: dict[str, str] = {**_auth_headers(api_key, settings_row), **_extra_headers(settings_row)}
        body: dict[str, Any] = {
            "model": model or settings_row.chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"]["content"])


def parse_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    fence = re.search(r"\{[\s\S]*\}", text)
    if fence:
        text = fence.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
