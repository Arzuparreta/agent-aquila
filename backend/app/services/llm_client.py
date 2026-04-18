from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.models.user_ai_settings import UserAISettings
from app.services.embedding_client import _api_root, _auth_headers, _extra_headers


@dataclass(frozen=True)
class ChatToolCall:
    """One tool/function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""

    def to_message_dict(self) -> dict[str, Any]:
        """Round-trippable dict suitable for the next chat-completions call."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.raw_arguments or json.dumps(self.arguments)},
        }


@dataclass
class ChatResponse:
    """Structured chat-completion response.

    ``content`` is the assistant's natural-language reply (may be empty when
    the model is exclusively requesting tool calls). ``tool_calls`` carries
    parsed function calls. ``raw_message`` is the unmodified ``message``
    object from the provider, useful for round-tripping back into the
    conversation history without losing provider-specific fields.
    """

    content: str
    tool_calls: list[ChatToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    @staticmethod
    async def chat_completion(
        api_key: str,
        settings_row: UserAISettings,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        response_format_json: bool = False,
    ) -> str:
        """Plain text chat completion. Returns just the assistant's content string.

        Used by classifiers / draft generators that don't need tool calling.
        """
        response = await LLMClient._post(
            api_key,
            settings_row,
            body={
                "model": model or settings_row.chat_model,
                "messages": messages,
                "temperature": temperature,
                **({"response_format": {"type": "json_object"}} if response_format_json else {}),
            },
        )
        return str(response["choices"][0]["message"].get("content") or "")

    @staticmethod
    async def chat_with_tools(
        api_key: str,
        settings_row: UserAISettings,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str | None = None,
        temperature: float = 0.2,
    ) -> ChatResponse:
        """Chat completion with native function/tool calling.

        ``tools`` must be a list of OpenAI-format ``{"type":"function", ...}``
        definitions. Returns a structured :class:`ChatResponse` exposing both
        the natural-language content and any parsed tool calls.

        This is the right primitive for agentic loops: the model is biased to
        either pick a tool from the schema or produce a final answer, removing
        the need for hand-rolled JSON envelopes that small local models
        (Ollama / Gemma / Qwen / Llama) struggle to follow reliably.
        """
        body: dict[str, Any] = {
            "model": model or settings_row.chat_model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        data = await LLMClient._post(api_key, settings_row, body=body)
        message = data["choices"][0]["message"]
        return _parse_message(message)

    @staticmethod
    async def _post(
        api_key: str, settings_row: UserAISettings, *, body: dict[str, Any]
    ) -> dict[str, Any]:
        root = _api_root(settings_row)
        url = f"{root}/chat/completions"
        headers: dict[str, str] = {
            **_auth_headers(api_key, settings_row),
            **_extra_headers(settings_row),
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()


def _parse_message(message: dict[str, Any]) -> ChatResponse:
    """Convert a raw provider ``message`` object into a ``ChatResponse``.

    Tolerates providers that emit ``arguments`` as either a JSON string (the
    OpenAI/Ollama convention) or as an already-decoded object (some
    OpenAI-compatible servers).
    """
    content = str(message.get("content") or "")
    raw_calls = message.get("tool_calls") or []
    parsed: list[ChatToolCall] = []
    for idx, call in enumerate(raw_calls):
        fn = (call.get("function") or {}) if isinstance(call, dict) else {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        raw_args = fn.get("arguments")
        args_dict: dict[str, Any] = {}
        raw_args_str = ""
        if isinstance(raw_args, str):
            raw_args_str = raw_args
            args_dict = parse_json_object(raw_args) or {}
        elif isinstance(raw_args, dict):
            args_dict = raw_args
            raw_args_str = json.dumps(raw_args, ensure_ascii=False)
        parsed.append(
            ChatToolCall(
                id=str(call.get("id") or f"call_{idx}"),
                name=name,
                arguments=args_dict,
                raw_arguments=raw_args_str,
            )
        )
    return ChatResponse(content=content, tool_calls=parsed, raw_message=dict(message))


def parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"\{[\s\S]*\}", text)
    if fence:
        try:
            return json.loads(fence.group(0))
        except json.JSONDecodeError:
            return None
    return None
