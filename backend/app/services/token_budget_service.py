from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.services.model_limits_service import ModelLimits

_CHARS_PER_TOKEN = 3.8
_MIN_RESERVED_OUTPUT = 256
_INPUT_SAFETY_MARGIN = 384


@dataclass(frozen=True)
class TokenBudget:
    input_budget: int
    reserved_output_tokens: int
    estimated_input_tokens: int
    compacted: bool


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        role = str(msg.get("role") or "")
        total += max(3, int(len(role) / _CHARS_PER_TOKEN))
        content = msg.get("content")
        if isinstance(content, str):
            total += max(1, int(len(content) / _CHARS_PER_TOKEN))
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                try:
                    raw = json.dumps(tc, ensure_ascii=False)
                except (TypeError, ValueError):
                    raw = str(tc)
                total += max(1, int(len(raw) / _CHARS_PER_TOKEN))
    return max(1, total)


def select_history_by_budget(
    *,
    history: list[dict[str, str]],
    budget_tokens: int,
    keep_tail_messages: int = 6,
) -> list[dict[str, str]]:
    if not history:
        return []
    if budget_tokens <= 0:
        return history[-keep_tail_messages:]
    tail = history[-keep_tail_messages:]
    tail_cost = estimate_message_tokens(tail)
    if tail_cost >= budget_tokens:
        return tail
    selected = list(tail)
    remaining = budget_tokens - tail_cost
    head = history[: len(history) - len(tail)]
    # Keep as much recent context as possible.
    for item in reversed(head):
        cost = estimate_message_tokens([item])
        if cost > remaining:
            break
        selected.insert(0, item)
        remaining -= cost
    return selected


def clamp_tool_content_by_tokens(content: str, token_limit: int) -> str:
    if token_limit <= 0:
        return ""
    max_chars = int(token_limit * _CHARS_PER_TOKEN)
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n...[tool result truncated for context budget]..."


def plan_budget(
    *,
    messages: list[dict[str, Any]],
    limits: ModelLimits,
    requested_output_tokens: int | None = None,
) -> TokenBudget:
    target_output = requested_output_tokens or limits.max_output_tokens_default
    reserved_output = max(_MIN_RESERVED_OUTPUT, min(target_output, limits.context_window // 2))
    input_budget = max(512, limits.context_window - reserved_output - _INPUT_SAFETY_MARGIN)
    est_input = estimate_message_tokens(messages)
    return TokenBudget(
        input_budget=input_budget,
        reserved_output_tokens=reserved_output,
        estimated_input_tokens=est_input,
        compacted=est_input > input_budget,
    )
