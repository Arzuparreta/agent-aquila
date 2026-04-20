"""ARQ worker entrypoint — OpenClaw-style heartbeat only.

Run with::

    arq app.worker.WorkerSettings

After the OpenClaw refactor we no longer ingest Gmail / Calendar / Drive
mirrors. The worker exists solely to give the agent a periodic
heartbeat — a tiny prompt that wakes the agent on a schedule. Gmail is
**not** part of the default prompt (see ``AGENT_HEARTBEAT_CHECK_GMAIL``);
that avoids burning Gmail API quota in the background. The heartbeat is
**off by default** (``AGENT_HEARTBEAT_ENABLED``) so dev setups never spawn
surprise LLM calls.
"""
from __future__ import annotations

import logging
from typing import Any

from arq import cron  # type: ignore[import-not-found]
from arq.connections import RedisSettings  # type: ignore[import-not-found]
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")


HEARTBEAT_PROMPT_WITH_GMAIL = (
    "Heartbeat tick. Take a quick look at the user's inbox using your "
    "Gmail tools. If anything obviously needs the user's attention "
    "(a real reply or a decision), record a short note via "
    "``upsert_memory`` so it surfaces in the next chat. If nothing is "
    "urgent, simply reply 'nothing to do'."
)

HEARTBEAT_PROMPT_LIGHT = (
    "Heartbeat tick. Briefly check whether anything needs follow-up: "
    "use ``recall_memory`` for open items, and calendar tools if the user "
    "cares about upcoming events. Do **not** open Gmail unless the user "
    "has previously asked for proactive mail checks. If nothing needs "
    "attention, reply with exactly: nothing to do"
)


def _heartbeat_prompt() -> str:
    if settings.agent_heartbeat_check_gmail:
        return HEARTBEAT_PROMPT_WITH_GMAIL
    return HEARTBEAT_PROMPT_LIGHT


async def agent_heartbeat(ctx: dict[str, Any]) -> dict[str, Any]:
    """Tiny periodic agent run.

    For every active user, run a one-shot agent turn with the heartbeat
    prompt. The run can call any tool (Gmail, memory, skills) but
    cannot send email without an approval (so even a misbehaving
    heartbeat can't auto-send replies).
    """
    if not settings.agent_heartbeat_enabled:
        return {"skipped": True, "reason": "AGENT_HEARTBEAT_ENABLED=false"}

    del ctx
    summaries: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        users = list(
            (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
        )
        for user in users:
            if not AgentRateLimitService.try_consume_heartbeat(user.id):
                summaries.append({"user_id": user.id, "status": "rate_limited"})
                continue
            try:
                run = await AgentService.run_agent(db, user, _heartbeat_prompt())
                summaries.append(
                    {
                        "user_id": user.id,
                        "run_id": run.id,
                        "status": run.status,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — heartbeat must keep going
                logger.exception("heartbeat failed for user %s: %s", user.id, exc)
                summaries.append({"user_id": user.id, "status": "failed", "error": str(exc)[:200]})
    return {"runs": summaries}


async def startup(ctx: dict[str, Any]) -> None:
    del ctx
    logger.info(
        "worker started; redis=%s heartbeat=%s every=%dm",
        settings.redis_url,
        settings.agent_heartbeat_enabled,
        settings.agent_heartbeat_minutes,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    del ctx
    logger.info("worker shutdown")


def _heartbeat_minutes() -> set[int]:
    step = max(1, min(60, settings.agent_heartbeat_minutes))
    return set(range(0, 60, step))


class WorkerSettings:
    """ARQ discovers this class. Referenced as ``app.worker.WorkerSettings``."""

    functions = [agent_heartbeat]
    cron_jobs = [
        cron(agent_heartbeat, minute=_heartbeat_minutes(), run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 300
    redis_settings = _redis_settings()
