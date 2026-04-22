from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentRunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=16000)


class AgentStepRead(BaseModel):
    step_index: int
    kind: str
    name: str | None = None
    payload: dict[str, Any] | None = None


class AgentTraceEventRead(BaseModel):
    """Versioned trace row (OTEL-friendly) for evals and dashboards."""

    id: int
    schema_version: int
    event_type: str
    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    step_index: int | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class PendingProposalRead(BaseModel):
    id: int
    kind: str
    summary: str | None = None
    risk_tier: str | None = None
    idempotency_key: str | None = None
    status: str
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class PendingOperationPreviewRead(BaseModel):
    """Structured preview for cockpit / clients (no side effects)."""

    kind: str
    risk_tier: str
    summary: str | None = None
    preview: dict[str, Any]


# Same shape as pending proposals; list endpoint alias uses this name in OpenAPI.
PendingOperationRead = PendingProposalRead


class AgentRunAttentionRead(BaseModel):
    stage: str
    last_event_at: datetime | None = None
    hint: str | None = None


class AgentRunRead(BaseModel):
    id: int
    status: str
    user_message: str
    assistant_reply: str | None = None
    error: str | None = None
    root_trace_id: str | None = None
    chat_thread_id: int | None = None
    attention: AgentRunAttentionRead | None = None
    steps: list[AgentStepRead]
    pending_proposals: list[PendingProposalRead]


class AgentRunSummaryRead(BaseModel):
    """Lightweight row for dashboards (no steps / proposals)."""

    id: int
    status: str
    user_message_preview: str
    created_at: datetime
    root_trace_id: str | None = None
    chat_thread_id: int | None = None


class ProposalResolve(BaseModel):
    note: str | None = Field(default=None, max_length=500)
