from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.models.user_ai_settings import UserAISettings
from app.services.ai_providers import normalize_provider_id
from app.services.embedding_client import _api_root, _auth_headers, _extra_headers
from app.services.llm_errors import (
    LLMProviderError,
    from_http_status_error,
    from_transport_error,
)


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
    ``finish_reason`` is taken from ``choices[0].finish_reason`` when present.
    ``usage`` is the provider's token usage object when returned (prompt/completion/total).
    """

    content: str
    tool_calls: list[ChatToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# Reused across requests for connection pooling (TLS session reuse, lower latency).
_shared_http: httpx.AsyncClient | None = None


def _shared_client() -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is None:
        _shared_http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _shared_http


@dataclass(frozen=True)
class LlmProviderContext:
    """HTTP fields + default chat model for auxiliary completions (ranking / JSON).

    Built from a saved :class:`~app.models.user_ai_provider_config.UserAIProviderConfig`
    row via :func:`~app.services.ai_provider_config_service.AIProviderConfigService.resolve_ranking_runtime`.
    ``default_model`` is ``classify_model`` when set, otherwise ``chat_model``.
    """

    provider_kind: str
    base_url: str | None
    extras: dict[str, Any] | None
    default_model: str
    api_key: str | None


def _default_chat_model(settings_row: UserAISettings | LlmProviderContext) -> str:
    if isinstance(settings_row, LlmProviderContext):
        return settings_row.default_model
    return settings_row.chat_model


async def aclose_llm_http_client() -> None:
    """Close the pooled HTTP client (call from app/worker shutdown)."""
    global _shared_http
    if _shared_http is not None:
        await _shared_http.aclose()
        _shared_http = None


def shared_http_client() -> httpx.AsyncClient:
    """Process-wide pooled AsyncClient (LLM + lightweight outbound calls)."""
    return _shared_client()


class LLMClient:
    @staticmethod
    async def chat_completion(
        api_key: str,
        settings_row: UserAISettings | LlmProviderContext,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        response_format_json: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Plain text chat completion. Returns just the assistant's content string.

        Used by classifiers / draft generators that don't need tool calling.
        """
        effective_key = api_key
        if isinstance(settings_row, LlmProviderContext):
            effective_key = api_key or (settings_row.api_key or "")
        body: dict[str, Any] = {
            "model": model or _default_chat_model(settings_row),
            "messages": messages,
            "temperature": temperature,
            **({"response_format": {"type": "json_object"}} if response_format_json else {}),
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        response = await LLMClient._post(effective_key, settings_row, body=body)
        return str(response["choices"][0]["message"].get("content") or "")

    @staticmethod
    async def chat_completion_full(
        api_key: str,
        settings_row: UserAISettings | LlmProviderContext,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> tuple[str, str | None, dict[str, Any], dict[str, Any] | None]:
        """Chat completion without tools; returns content, finish_reason, raw message dict, usage."""
        effective_key = api_key
        if isinstance(settings_row, LlmProviderContext):
            effective_key = api_key or (settings_row.api_key or "")
        body: dict[str, Any] = {
            "model": model or _default_chat_model(settings_row),
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        data = await LLMClient._post(effective_key, settings_row, body=body)
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        usage = data.get("usage")
        return content, choice.get("finish_reason"), dict(message), usage if isinstance(usage, dict) else None

    @staticmethod
    async def chat_with_tools(
        api_key: str,
        settings_row: UserAISettings | LlmProviderContext,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
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
        effective_key = api_key
        if isinstance(settings_row, LlmProviderContext):
            effective_key = api_key or (settings_row.api_key or "")
        # Strip internal metadata (_palette_modes) before sending to LLM
        clean_tools = [{k: v for k, v in t.items() if k != "_palette_modes"} for t in tools]
        
        body: dict[str, Any] = {
            "model": model or _default_chat_model(settings_row),
            "messages": messages,
            "temperature": temperature,
            "tools": clean_tools,
            "tool_choice": tool_choice,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        data = await LLMClient._post(effective_key, settings_row, body=body)
        choice = data["choices"][0]
        message = choice["message"]
        parsed = _parse_message(message)
        parsed.finish_reason = choice.get("finish_reason")
        usage = data.get("usage")
        if isinstance(usage, dict):
            parsed.usage = usage
        return parsed

    @staticmethod
    async def _post(
        api_key: str,
        settings_row: UserAISettings | LlmProviderContext,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        root = _api_root(settings_row)
        url = f"{root}/chat/completions"
        headers: dict[str, str] = {
            **_auth_headers(api_key, settings_row),
            **_extra_headers(settings_row),
        }
        provider = normalize_provider_id(settings_row.provider_kind)
        model = body.get("model") if isinstance(body, dict) else None
        try:
            response = await _shared_client().post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise from_http_status_error(exc, provider=provider, model=model) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise from_transport_error(exc, provider=provider, model=model) from exc
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive normalization
            raise LLMProviderError(
                provider=provider,
                status_code=None,
                message=f"Unexpected error talking to {provider}.",
                hint="Check the backend logs for the full traceback.",
                detail=str(exc),
                model=model,
            ) from exc


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
    return ChatResponse(
        content=content, tool_calls=parsed, raw_message=dict(message), finish_reason=None
    )


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
