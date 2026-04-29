from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent_run import AgentRun, AgentTraceEvent, AgentRunStep


@dataclass(slots=True)
class AttentionSnapshot:
    stage: str
    last_event_at: datetime | None
    hint: str


def stage_from_event_type(event_type: str | None) -> str:
    et = (event_type or "").strip()
    if et == "run.started":
        return "queued"
    if et.startswith("llm."):
        return "waiting_llm"
    if et.startswith("tool."):
        return "waiting_tool"
    return "running"


def hint_for_stage(stage: str) -> str:
    if stage == "queued":
        return "Queued for worker execution."
    if stage == "waiting_llm":
        return "Waiting for model/provider response."
    if stage == "waiting_tool":
        return "Waiting for external tool/provider."
    return "Run is active but not reporting fresh progress."


async def latest_trace_event(db: AsyncSession, run_id: int) -> AgentTraceEvent | None:
    """Get the latest trace event for a run, or None if tracing is disabled."""
    if not getattr(settings, "agent_tracing_enabled", False):
        return None

    result = await db.execute(
        select(AgentTraceEvent)
        .where(AgentTraceEvent.run_id == run_id)
        .order_by(AgentTraceEvent.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_trace_event_at(db: AsyncSession, run_id: int) -> datetime | None:
    """Get the timestamp of the latest trace event, or None if tracing is disabled."""
    if not getattr(settings, "agent_tracing_enabled", False):
        return None

    result = await db.execute(
        select(func.max(AgentTraceEvent.created_at)).where(AgentTraceEvent.run_id == run_id)
    )
    return result.scalar_one_or_none()


async def build_attention_snapshot(db: AsyncSession, run: AgentRun) -> AttentionSnapshot:
    """Build attention snapshot using trace events if available, otherwise fallback to run status."""
    latest = await latest_trace_event(db, run.id)

    if latest:
        # Use trace events for detailed stage information
        stage = stage_from_event_type(latest.event_type)
        last_event_at = latest.created_at
    else:
        # Fallback: use run status and updated_at when tracing is disabled
        stage = run.status if run.status in {"queued", "running", "pending"} else "running"
        last_event_at = run.updated_at or run.created_at

    hint = hint_for_stage(stage)
    return AttentionSnapshot(stage=stage, last_event_at=last_event_at, hint=hint)


def stage_age_seconds(*, now: datetime, run: AgentRun, last_event_at: datetime | None) -> float:
    baseline = last_event_at or run.updated_at or run.created_at or now
    return max(0.0, (now - baseline).total_seconds())


def should_mark_needs_attention(
    *,
    run: AgentRun,
    stage: str,
    age_seconds: float,
    pending_sla_seconds: int,
    stage_sla_seconds: int,
    silence_seconds: int,
) -> bool:
    if run.status == "pending":
        return age_seconds >= float(pending_sla_seconds)
    if stage in {"waiting_llm", "waiting_tool"}:
        return age_seconds >= float(stage_sla_seconds)
    return age_seconds >= float(silence_seconds)


def build_attention_reason(*, stage: str, age_seconds: float) -> str:
    age_m = int(round(age_seconds / 60.0))
    return f"Run requires attention: no progress in stage '{stage}' for ~{age_m}m."

