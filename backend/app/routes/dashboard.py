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
from app.services.job_queue import _get_pool

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
