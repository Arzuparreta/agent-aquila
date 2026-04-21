"""First-run checklist for operators (non-technical friendly)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.schemas.cockpit import OnboardingStatusRead
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.user_ai_settings_service import UserAISettingsService

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(get_current_user)])


@router.get("/status", response_model=OnboardingStatusRead)
async def onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OnboardingStatusRead:
    db_ok = False
    try:
        await db.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = False
    if (settings.redis_url or "").strip():
        try:
            import redis.asyncio as redis

            r = redis.from_url(settings.redis_url, decode_responses=True)
            await r.ping()
            await r.aclose()
            redis_ok = True
        except Exception:
            redis_ok = False

    prefs = await UserAISettingsService.get_or_create(db, current_user)
    rt = await resolve_for_user(db, current_user)
    has_ai_provider = bool(prefs.active_provider_kind) and not prefs.ai_disabled

    cc = await db.execute(
        select(func.count())
        .select_from(ConnectorConnection)
        .where(ConnectorConnection.user_id == current_user.id)
    )
    connector_count = int(cc.scalar_one() or 0)

    return OnboardingStatusRead(
        database_ok=db_ok,
        redis_ok=redis_ok,
        has_ai_provider=has_ai_provider,
        connector_count=connector_count,
        telegram_configured=bool((settings.telegram_bot_token or "").strip()),
        agent_async_runs=bool(rt.agent_async_runs and (settings.redis_url or "").strip()),
    )
