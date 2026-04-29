"""Versioned trace events for observability and eval/replay (schema v1)."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_run import AgentTraceEvent

_MAX_STEP_PAYLOAD_JSON_CHARS = 20_000

TRACE_SCHEMA_VERSION = 1

# Stable event_type strings for consumers (eval harness, OTEL bridges).
EV_RUN_STARTED = "run.started"
EV_LLM_REQUEST = "llm.request"
EV_LLM_RESPONSE = "llm.response"
EV_TOOL_STARTED = "tool.started"
EV_TOOL_FINISHED = "tool.finished"
EV_RUN_COMPLETED = "run.completed"
EV_RUN_FAILED = "run.failed"
# Post-turn durable memory extraction (correlates with run_id / root_trace_id).
EV_POST_TURN_STARTED = "post_turn.started"
EV_POST_TURN_SKIPPED = "post_turn.skipped"
EV_POST_TURN_COMPLETED = "post_turn.completed"


def tracing_enabled() -> bool:
    """Check if detailed trace event emission is enabled."""
    return getattr(settings, "agent_tracing_enabled", False)


def new_trace_id() -> str:
    """W3C-style 128-bit trace id as 32 lowercase hex chars."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """64-bit span id as 16 lowercase hex chars."""
    return secrets.token_hex(8)


def content_sha256_preview(text: str, *, max_bytes: int = 4096) -> str:
    """SHA-256 hex digest of UTF-8 prefix for PII-safe correlation in traces."""
    raw = (text or "").encode("utf-8")[:max_bytes]
    return hashlib.sha256(raw).hexdigest()


async def emit_trace_event(
    db: AsyncSession,
    *,
    run_id: int,
    event_type: str,
    trace_id: str,
    payload: dict[str, Any] | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    step_index: int | None = None,
) -> None:
    """Emit a trace event if tracing is enabled.

    This function checks the AGENT_TRACING_ENABLED setting before emitting
    events to avoid unnecessary database writes for single-user deployments.
    """
    if not tracing_enabled():
        return

    db.add(
        AgentTraceEvent(
            run_id=run_id,
            schema_version=TRACE_SCHEMA_VERSION,
            event_type=event_type,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            step_index=step_index,
            payload=payload,
        )
    )


# ---------------------------------------------------------------------------
# Helper functions for step/trace handling
# ---------------------------------------------------------------------------

def _conversation_trace_snapshot(
    conversation: list[dict[str, Any]], *, max_items: int = 8, max_content: int = 4000
) -> str:
    """Compact JSON of recent messages for AgentRunStep diagnostics."""
    tail = conversation[-max_items:]
    slim: list[dict[str, Any]] = []
    for m in tail:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str) and len(content) > max_content:
            content = content[:max_content] + "…"
        item: dict[str, Any] = {"role": role, "content": content}
        tcalls = m.get("tool_calls")
        if tcalls:
            item["tool_calls_preview"] = []
            for tc in tcalls[:16]:
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    item["tool_calls_preview"].append({"name": fn.get("name")})
        slim.append(item)
    try:
        return json.dumps(slim, ensure_ascii=False)[:12000]
    except (TypeError, ValueError):
        return "[]"


def _trim_step_payload_for_client(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shrink persisted step payloads before returning them over HTTP."""
    if payload is None:
        return None
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_serialization_error": True}
    if len(serialized) <= _MAX_STEP_PAYLOAD_JSON_CHARS:
        return payload
    if isinstance(payload, dict) and "result" in payload:
        slim = dict(payload)
        res = slim.get("result")
        if isinstance(res, (dict, list)):
            try:
                res_raw = json.dumps(res, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                slim["result"] = {"_truncated": True}
                return slim
            if len(res_raw) > 8000:
                slim["result"] = {
                    "_truncated": True,
                    "_approx_chars": len(res_raw),
                    "_preview": res_raw[:8000] + "…",
                }
            try:
                slim_raw = json.dumps(slim, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                pass
            else:
                if len(slim_raw) <= _MAX_STEP_PAYLOAD_JSON_CHARS:
                    return slim
    return {
        "_truncated": True,
        "_approx_chars": len(serialized),
        "_preview": serialized[:8000] + "…",
    }


def _approx_prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate for trace metrics (not billing-accurate)."""
    try:
        raw = json.dumps(messages, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = ""
    return max(1, len(raw) // 4)


class LLMProviderError(Exception):
    def __init__(self, provider, message, hint, detail=None):
        self.provider = provider
        self.message = message
        self.hint = hint
        self.detail = detail
    def to_dict(self):
        return {"provider": self.provider, "message": self.message, "hint": self.hint}


def _is_context_overflow(exc) -> bool:
    detail = str(exc.detail or "").lower()
    return any(
        marker in detail
        for marker in (
            "maximum context length",
            "context length",
            "requested",
            "input_tokens",
            "prompt is too long",
        )
    )


def _assistant_message_from(response) -> dict[str, Any]:
    """Re-encode an assistant ChatResponse into a chat-completions message."""
    msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
    if response.tool_calls:
        msg["tool_calls"] = [tc.to_message_dict() for tc in response.tool_calls]
    return msg


def _reduce_conversation_for_budget(
    conversation: list[dict[str, Any]],
    *,
    input_budget_tokens: int,
) -> tuple[list[dict[str, Any]], bool]:
    from app.services.token_budget_service import estimate_message_tokens, select_history_by_budget, clamp_tool_content_by_tokens
    if not conversation:
        return conversation, False
    if estimate_message_tokens(conversation) <= input_budget_tokens:
        return conversation, False
    reduced = list(conversation)
    changed = False
    # Keep system prompt + latest user turn, compact middle history first.
    if len(reduced) > 2:
        head = reduced[:1]
        middle = reduced[1:-1]
        tail = reduced[-1:]
        dropped_count = max(0, len(middle) - 8)
        compact_middle = select_history_by_budget(
            history=[
                {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
                for m in middle
                if isinstance(m.get("content"), str)
            ],
            budget_tokens=max(256, input_budget_tokens - estimate_message_tokens(head + tail)),
            keep_tail_messages=4,
        )
        if dropped_count > 0:
            summary = {
                "role": "system",
                "content": (
                    "Context compression summary:\n"
                    "- Active Task: Continue the current user request.\n"
                    f"- Completed Actions: Earlier exchanges compacted ({dropped_count} msgs).\n"
                ),
            }
            reduced = head + [summary] + compact_middle + tail
        else:
            reduced = head + compact_middle + tail
        changed = True
    # If still over budget, trim very large message contents.
    while estimate_message_tokens(reduced) > input_budget_tokens and len(reduced) > 1:
        idx = 1
        candidate = reduced[idx]
        content = candidate.get("content")
        if not isinstance(content, str) or len(content) < 600:
            if len(reduced) > 3:
                reduced.pop(idx)
                changed = True
                continue
            break
        candidate = dict(candidate)
        candidate["content"] = clamp_tool_content_by_tokens(content, max(100, len(content) // 10))
        reduced[idx] = candidate
        changed = True
    return reduced, changed
