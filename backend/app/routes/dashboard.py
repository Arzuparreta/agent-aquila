"""Control-plane dashboard APIs: health + run metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.agent_run import AgentRun
from app.models.user import User
from app.schemas.cockpit import DashboardMetricsRead, DashboardStatusRead
from app.schemas.cockpit import ContextBudgetDebugRead
from app.services.job_queue import _get_pool
from app.services.model_limits_service import resolve_model_limits
from app.services.token_budget_service import plan_budget
from app.services.user_ai_settings_service import UserAISettingsService
from app.services.agent_runtime_config_service import resolve_for_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/status", response_model=DashboardStatusRead)
async def dashboard_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardStatusRead:
    del current_user
    db_ok = False
    try:
        await db.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False
    redis_url = bool((settings.redis_url or "").strip())
    redis_ping = False
    if redis_url:
        try:
            import redis.asyncio as redis

            r = redis.from_url(settings.redis_url, decode_responses=True)
            await r.ping()
            await r.aclose()
            redis_ping = True
        except Exception:
            redis_ping = False
    pool_ok = False
    try:
        pool = await _get_pool()
        pool_ok = pool is not None
    except Exception:
        pool_ok = False
    return DashboardStatusRead(
        database_ok=db_ok,
        redis_configured=redis_url,
        redis_ping_ok=redis_ping,
        arq_pool_ok=pool_ok,
    )


@router.get("/metrics", response_model=DashboardMetricsRead)
async def dashboard_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardMetricsRead:
    since = datetime.now(UTC) - timedelta(hours=24)
    uid = current_user.id
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.user_id == uid, AgentRun.created_at >= since)
            )
        ).scalar_one()
        or 0
    )
    done = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.user_id == uid,
                    AgentRun.created_at >= since,
                    AgentRun.status == "completed",
                )
            )
        ).scalar_one()
        or 0
    )
    failed = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.user_id == uid,
                    AgentRun.created_at >= since,
                    AgentRun.status == "failed",
                )
            )
        ).scalar_one()
        or 0
    )
    needs_attention = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.user_id == uid,
                    AgentRun.created_at >= since,
                    AgentRun.status == "needs_attention",
                )
            )
        ).scalar_one()
        or 0
    )
    return DashboardMetricsRead(
        agent_runs_last_24h=total,
        agent_runs_completed_last_24h=done,
        agent_runs_failed_last_24h=failed,
        agent_runs_needs_attention_last_24h=needs_attention,
    )


@router.get("/context-budget", response_model=ContextBudgetDebugRead)
async def dashboard_context_budget(
    message: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContextBudgetDebugRead:
    settings_row = await UserAISettingsService.get_or_create(db, current_user)
    runtime = await resolve_for_user(db, current_user)
    api_key = await UserAISettingsService.get_api_key(db, current_user)
    model = settings_row.chat_model
    limits = await resolve_model_limits(
        api_key=api_key or "",
        settings_row=settings_row,
        model=model,
    )
    sample_messages = [
        {"role": "system", "content": "Context-budget debug request for dashboard introspection."},
        {"role": "user", "content": message or "Quick budget check"},
    ]
    budget = plan_budget(messages=sample_messages, limits=limits)
    return ContextBudgetDebugRead(
        provider_kind=settings_row.provider_kind,
        model=model,
        model_limits_source=limits.source,
        context_window=limits.context_window,
        max_output_tokens_default=limits.max_output_tokens_default,
        estimated_input_tokens=budget.estimated_input_tokens,
        input_budget_tokens=budget.input_budget,
        reserved_output_tokens=budget.reserved_output_tokens,
        would_compact=budget.compacted,
        runtime_flags={
            "context_budget_v2": runtime.context_budget_v2,
            "token_aware_history": runtime.token_aware_history,
            "dynamic_model_limits": runtime.dynamic_model_limits,
        },
    )
