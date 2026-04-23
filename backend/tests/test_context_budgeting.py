from __future__ import annotations

import pytest

from app.services import llm_client
from app.services.llm_errors import hint_for_http_error
from app.services.model_limits_service import ModelLimits, resolve_model_limits
from app.services.token_budget_service import (
    clamp_tool_content_by_tokens,
    plan_budget,
    select_history_by_budget,
)


@pytest.mark.asyncio
async def test_llm_client_chat_with_tools_sets_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_post(_api_key: str, _settings_row: object, *, body: dict[str, object]) -> dict[str, object]:
        captured["body"] = body
        return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": []}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_post", fake_post)
    row = llm_client.LlmProviderContext(
        provider_kind="openai",
        base_url="https://api.openai.com/v1",
        extras={},
        default_model="gpt-4o-mini",
        api_key="x",
    )
    await llm_client.LLMClient.chat_with_tools(
        "x",
        row,
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_tokens=777,
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 777


@pytest.mark.asyncio
async def test_llm_client_chat_completion_full_sets_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_post(_api_key: str, _settings_row: object, *, body: dict[str, object]) -> dict[str, object]:
        captured["body"] = body
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(llm_client.LLMClient, "_post", fake_post)
    row = llm_client.LlmProviderContext(
        provider_kind="openai",
        base_url="https://api.openai.com/v1",
        extras={},
        default_model="gpt-4o-mini",
        api_key="x",
    )
    await llm_client.LLMClient.chat_completion_full(
        "x",
        row,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=333,
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 333


def test_token_budget_and_selection() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u" * 4000},
        {"role": "assistant", "content": "a" * 4000},
        {"role": "user", "content": "latest"},
    ]
    limits = ModelLimits(context_window=4096, max_output_tokens_default=1024)
    budget = plan_budget(messages=msgs, limits=limits)
    assert budget.input_budget > 0
    history = [{"role": "user", "content": "x" * 1200} for _ in range(12)]
    trimmed = select_history_by_budget(history=history, budget_tokens=350)
    assert len(trimmed) < len(history)
    clamped = clamp_tool_content_by_tokens("z" * 2000, 50)
    assert len(clamped) < 2000


@pytest.mark.asyncio
async def test_model_limits_openrouter_fallback() -> None:
    class _Row:
        provider_kind = "openrouter"
        base_url = "https://openrouter.ai/api/v1"
        extras = {}

    out = await resolve_model_limits(
        api_key="",
        settings_row=_Row(),  # type: ignore[arg-type]
        model="minimax/minimax-m2.5:free",
    )
    assert out.context_window >= 32768
    assert out.max_output_tokens_default >= 1024


def test_overflow_hint_is_actionable() -> None:
    hint = hint_for_http_error(
        provider="openrouter",
        status_code=400,
        model="minimax/minimax-m2.5:free",
        body="This model's maximum context length is 32768 tokens. parameter=input_tokens",
    )
    assert "context window" in hint.lower()
