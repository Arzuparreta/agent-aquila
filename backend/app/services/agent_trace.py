"""Versioned trace events for observability and eval/replay (schema v1)."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentTraceEvent

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
