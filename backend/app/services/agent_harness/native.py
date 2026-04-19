from __future__ import annotations

from typing import Any

from app.models.user_ai_settings import UserAISettings
from app.services.llm_client import ChatResponse, LLMClient


async def chat_turn_native(
    api_key: str,
    settings_row: UserAISettings,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float,
) -> ChatResponse:
    return await LLMClient.chat_with_tools(
        api_key,
        settings_row,
        messages=messages,
        tools=tools,
        tool_choice="required",
        temperature=temperature,
    )
