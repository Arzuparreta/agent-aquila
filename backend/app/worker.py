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
from app.models.agent_run import AgentRun
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.core.schema_probe import fail_fast_if_schema_stale
from app.services.agent_memory_post_turn_service import maybe_ingest_post_turn_memory
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.agent_service import AgentService
from app.services.chat_service import apply_agent_run_to_placeholder
from app.services.llm_client import aclose_llm_http_client
from app.services.telegram_notify import notify_telegram_for_completed_run
from app.services.user_ai_settings_service import UserAISettingsService

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


def _heartbeat_prompt(*, check_gmail: bool) -> str:
    if check_gmail:
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
            rt = await resolve_for_user(db, user)
            if not rt.agent_heartbeat_enabled:
                continue
            if not AgentRateLimitService.try_consume_heartbeat(
                user.id, heartbeat_burst_per_hour=rt.agent_heartbeat_burst_per_hour
            ):
                summaries.append({"user_id": user.id, "status": "rate_limited"})
                continue
            prefs = await UserAISettingsService.get_or_create(db, user)
            if getattr(prefs, "agent_processing_paused", False):
                summaries.append({"user_id": user.id, "status": "paused"})
                continue
            try:
                run = await AgentService.run_agent(
                    db, user, _heartbeat_prompt(check_gmail=rt.agent_heartbeat_check_gmail)
                )
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
    await fail_fast_if_schema_stale()
    logger.info(
        "worker started; redis=%s heartbeat=%s every=%dm",
        settings.redis_url,
        settings.agent_heartbeat_enabled,
        settings.agent_heartbeat_minutes,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    del ctx
    await aclose_llm_http_client()
    logger.info("worker shutdown")


async def run_chat_agent_turn(
    ctx: dict[str, Any],
    run_id: int,
    user_id: int,
    prior_messages: list[dict[str, str]] | None,
    thread_context_hint: str | None,
) -> dict[str, Any]:
    """Background completion for ``POST /threads/{id}/messages`` (long agent turns)."""
    del ctx
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            run_row = await db.get(AgentRun, run_id)
            if not user or not run_row or run_row.user_id != user_id:
                logger.warning("run_chat_agent_turn skipped: missing user or run mismatch")
                return {"ok": False, "reason": "not_found"}
            if run_row.status != "pending":
                return {"ok": True, "reason": "already_started", "status": run_row.status}
            run_row.status = "running"
            await db.commit()
            read = await AgentService._execute_agent_loop(
                db,
                user,
                run_row,
                prior_messages=prior_messages,
                thread_context_hint=thread_context_hint,
                replay=None,
            )
            tid = run_row.chat_thread_id
            if tid is None:
                return {"ok": True, "run_id": run_id, "status": read.status}
            thread = await db.get(ChatThread, tid)
            if not thread or thread.user_id != user_id:
                logger.warning("run_chat_agent_turn: thread %s missing for run %s", tid, run_id)
                return {"ok": True, "run_id": run_id, "status": read.status}
            await apply_agent_run_to_placeholder(
                db, thread, agent_run_id=run_id, run_read=read
            )
            await notify_telegram_for_completed_run(
                db,
                user_id=user_id,
                thread_id=tid,
                assistant_reply=read.assistant_reply,
                error=read.error,
            )
            await db.commit()
            if read.status == "completed":
                await maybe_ingest_post_turn_memory(
                    db,
                    user,
                    user_message=run_row.user_message or "",
                    assistant_message=read.assistant_reply or "",
                )
            return {"ok": True, "run_id": run_id, "status": read.status}
    except Exception as exc:
        logger.exception("run_chat_agent_turn failed run_id=%s", run_id)
        try:
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                run_row = await db.get(AgentRun, run_id)
                if run_row and run_row.status not in ("completed", "failed"):
                    run_row.status = "failed"
                    run_row.error = (str(exc) or "Background agent job crashed.")[:2000]
                    await db.commit()
                if user and run_row and run_row.chat_thread_id:
                    read = await AgentService.get_run(db, user, run_id)
                    thread = await db.get(ChatThread, run_row.chat_thread_id)
                    if read and thread and thread.user_id == user_id:
                        await apply_agent_run_to_placeholder(
                            db, thread, agent_run_id=run_id, run_read=read
                        )
                        await db.commit()
        except Exception:
            logger.exception("run_chat_agent_turn cleanup failed run_id=%s", run_id)
        return {"ok": False, "run_id": run_id, "error": str(exc)[:200]}


def _heartbeat_minutes() -> set[int]:
    step = max(1, min(60, settings.agent_heartbeat_minutes))
    return set(range(0, 60, step))


class WorkerSettings:
    """ARQ discovers this class. Referenced as ``app.worker.WorkerSettings``."""

    functions = [agent_heartbeat, run_chat_agent_turn]
    cron_jobs = [
        cron(agent_heartbeat, minute=_heartbeat_minutes(), run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 300
    redis_settings = _redis_settings()
