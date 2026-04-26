"""ARQ worker entrypoint — scheduled jobs (heartbeat, memory consolidation, etc.).

Run with::

    arq app.worker.WorkerSettings

The worker does not mirror Gmail/Calendar/Drive locally. The optional **heartbeat** cron wakes the
agent with ``turn_profile=heartbeat`` (compact palette by default). Gmail is not in the default
prompt (``AGENT_HEARTBEAT_CHECK_GMAIL``) to protect quota. Heartbeat is **off by default**
(``AGENT_HEARTBEAT_ENABLED``) so local clones do not spawn surprise LLM calls.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

from arq import cron  # type: ignore[import-not-found]
from arq.connections import RedisSettings  # type: ignore[import-not-found]
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.channel_thread_binding import ChannelThreadBinding
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.core.schema_probe import fail_fast_if_schema_stale
from app.services.agent_event_bus import publish_run_status_event
from app.services.agent_memory_post_turn_service import (
    maybe_ingest_post_turn_memory,
)
from app.services.agent_skill_autogenesis import maybe_record_skill_autogenesis_candidate
from app.services.agent_memory_consolidation import run_consolidation_for_all_active_users
from app.services.chat_thread_title_service import maybe_generate_thread_title
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.agent_run_attention import (
    build_attention_reason,
    build_attention_snapshot,
    should_mark_needs_attention,
    stage_age_seconds,
)
from app.schemas.agent_turn_profile import TURN_PROFILE_AUTOMATION, TURN_PROFILE_HEARTBEAT
from app.services.agent_service import AgentService
from app.services.scheduled_task_service import ScheduledTaskService
from app.services.chat_service import apply_agent_run_to_placeholder, append_message
from app.services.llm_client import aclose_llm_http_client
from app.services.telegram_notify import notify_telegram_for_completed_run, notify_user_telegram, send_telegram_text
from app.services.telegram_poller import run_telegram_long_poll_supervisor
from app.services.telegram_integration_service import get_effective_bot_token_for_user
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

_telegram_poll_task: asyncio.Task[None] | None = None
_telegram_poll_stop: asyncio.Event | None = None


async def _get_telegram_token(db: AsyncSession, user_id: int) -> str | None:
    """Get effective Telegram bot token for user."""
    user = await db.get(User, user_id)
    if not user:
        return None
    return await get_effective_bot_token_for_user(db, user)


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
                    db,
                    user,
                    _heartbeat_prompt(check_gmail=rt.agent_heartbeat_check_gmail),
                    turn_profile=TURN_PROFILE_HEARTBEAT,
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
    global _telegram_poll_task, _telegram_poll_stop
    await fail_fast_if_schema_stale()
    logger.info(
        "worker started; redis=%s heartbeat=%s every=%dm",
        settings.redis_url,
        settings.agent_heartbeat_enabled,
        settings.agent_heartbeat_minutes,
    )
    if settings.telegram_polling_enabled:
        _telegram_poll_stop = asyncio.Event()
        _telegram_poll_task = asyncio.create_task(
            run_telegram_long_poll_supervisor(_telegram_poll_stop),
            name="telegram_long_poll",
        )


async def shutdown(ctx: dict[str, Any]) -> None:
    del ctx
    global _telegram_poll_task, _telegram_poll_stop
    if _telegram_poll_stop is not None:
        _telegram_poll_stop.set()
    if _telegram_poll_task is not None:
        _telegram_poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _telegram_poll_task
        _telegram_poll_task = None
        _telegram_poll_stop = None
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
            if run_row.status == "cancelled":
                return {"ok": True, "reason": "cancelled", "status": "cancelled"}
            if run_row.status != "pending":
                return {"ok": True, "reason": "already_started", "status": run_row.status}
            await db.refresh(run_row)
            if run_row.cancel_requested:
                run_row.cancel_requested = False
                run_row.status = "cancelled"
                run_row.assistant_reply = (run_row.assistant_reply or "").strip() or "Stopped."
                await db.commit()
                read = await AgentService.get_run(db, user, run_id)
                tid = run_row.chat_thread_id
                if read and tid is not None:
                    thread = await db.get(ChatThread, tid)
                    if thread and thread.user_id == user_id:
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
                await publish_run_status_event(
                    user_id=user_id,
                    run_id=run_id,
                    status="cancelled",
                    error=None,
                    step_count=0,
                    chat_thread_id=tid,
                    terminal=True,
                )
                return {"ok": True, "run_id": run_id, "status": "cancelled"}

            run_row.status = "running"
            await db.commit()
            await publish_run_status_event(
                user_id=user_id,
                run_id=run_id,
                status="running",
                error=None,
                step_count=0,
                chat_thread_id=run_row.chat_thread_id,
                terminal=False,
            )
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
                await publish_run_status_event(
                    user_id=user_id,
                    run_id=run_id,
                    status=read.status,
                    error=read.error,
                    step_count=len(read.steps),
                    chat_thread_id=None,
                    terminal=True,
                )
                return {"ok": True, "run_id": run_id, "status": read.status}
            thread = await db.get(ChatThread, tid)
            if not thread or thread.user_id != user_id:
                logger.warning("run_chat_agent_turn: thread %s missing for run %s", tid, run_id)
                await publish_run_status_event(
                    user_id=user_id,
                    run_id=run_id,
                    status=read.status,
                    error=read.error,
                    step_count=len(read.steps),
                    chat_thread_id=tid,
                    terminal=True,
                )
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
            await publish_run_status_event(
                user_id=user_id,
                run_id=run_id,
                status=read.status,
                error=read.error,
                step_count=len(read.steps),
                chat_thread_id=tid,
                terminal=True,
            )
            if read.status == "completed":
                await maybe_generate_thread_title(
                    db,
                    user,
                    tid,
                    user_message=run_row.user_message or "",
                    assistant_message=read.assistant_reply or "",
                    run_status=read.status,
                )
                result = await maybe_ingest_post_turn_memory(
                    db,
                    user,
                    user_message=run_row.user_message or "",
                    assistant_message=read.assistant_reply or "",
                    run_id=run_id,
                )
                if result and result.stored_keys and tid is not None:
                    thread = await db.get(ChatThread, tid)
                    if thread and thread.user_id == user_id:
                        from app.services.chat_service import inject_memory_receipt

                        await inject_memory_receipt(db, thread, result.stored_items)
                await maybe_record_skill_autogenesis_candidate(db, run_row)
            return {"ok": True, "run_id": run_id, "status": read.status}
    except Exception as exc:
        logger.exception("run_chat_agent_turn failed run_id=%s", run_id)
        try:
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                run_row = await db.get(AgentRun, run_id)
                if run_row and run_row.status not in ("completed", "failed", "cancelled"):
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
                        await publish_run_status_event(
                            user_id=user_id,
                            run_id=run_id,
                            status=read.status,
                            error=read.error,
                            step_count=len(read.steps),
                            chat_thread_id=run_row.chat_thread_id,
                            terminal=True,
                        )
        except Exception:
            logger.exception("run_chat_agent_turn cleanup failed run_id=%s", run_id)
        return {"ok": False, "run_id": run_id, "error": str(exc)[:200]}


async def flag_stuck_agent_runs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark long-silent pending/running runs as needs_attention and publish updates."""
    del ctx
    if not settings.agent_run_attention_enabled:
        return {"skipped": True, "reason": "AGENT_RUN_ATTENTION_ENABLED=false"}

    now = datetime.now(UTC)
    touched = 0
    touched_run_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(AgentRun).where(AgentRun.status.in_(("pending", "running"))).order_by(AgentRun.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for run in rows:
            snap = await build_attention_snapshot(db, run)
            age_s = stage_age_seconds(now=now, run=run, last_event_at=snap.last_event_at)
            if not should_mark_needs_attention(
                run=run,
                stage=snap.stage,
                age_seconds=age_s,
                pending_sla_seconds=settings.agent_run_attention_pending_seconds,
                stage_sla_seconds=settings.agent_run_attention_stage_seconds,
                silence_seconds=settings.agent_run_attention_silence_seconds,
            ):
                continue

            run.status = "needs_attention"
            run.error = build_attention_reason(stage=snap.stage, age_seconds=age_s)
            run.updated_at = now
            touched += 1
            touched_run_ids.append(run.id)
            if run.chat_thread_id is not None:
                thread = await db.get(ChatThread, run.chat_thread_id)
                if thread and thread.user_id == run.user_id:
                    user = await db.get(User, run.user_id)
                    if user is not None:
                        read = await AgentService.get_run(db, user, run.id)
                        if read is not None:
                            await apply_agent_run_to_placeholder(
                                db, thread, agent_run_id=run.id, run_read=read
                            )
        if touched:
            await db.commit()
        else:
            await db.rollback()

    if not touched:
        return {"ok": True, "updated": 0}

    async with AsyncSessionLocal() as db:
        runs = list(
            (await db.execute(select(AgentRun).where(AgentRun.id.in_(touched_run_ids)))).scalars().all()
        )
        for run in runs:
            snap = await build_attention_snapshot(db, run)
            await publish_run_status_event(
                user_id=run.user_id,
                run_id=run.id,
                status=run.status,
                error=run.error,
                step_count=0,
                chat_thread_id=run.chat_thread_id,
                terminal=False,
                attention={
                    "stage": snap.stage,
                    "last_event_at": snap.last_event_at.isoformat() if snap.last_event_at else None,
                    "hint": snap.hint,
                },
            )
    return {"ok": True, "updated": touched}


def _heartbeat_minutes() -> set[int]:
    step = max(1, min(60, settings.agent_heartbeat_minutes))
    return set(range(0, 60, step))


def _scheduled_task_prompt(task: ScheduledTask, *, now_utc: datetime) -> str:
    return (
        f"SCHEDULED_TASK_RUN id={task.id} name={task.name}\n"
        f"now_utc={now_utc.isoformat()}\n"
        "Execute this user-defined recurring task instruction:\n"
        f"{task.instruction}\n\n"
        "Rules: run the requested workflow using available tools; "
        "if one source fails, continue with partial output and explicitly mention gaps. "
        "Use the user's preferred delivery channel if specified in the instruction."
    )


def _parse_delivery_preference(instruction: str) -> str | None:
    """Parse delivery channel preference from task instruction.
    
    Returns: 'telegram', 'email', or None for default (web thread).
    """
    text = instruction.lower()
    if "send to telegram" in text or "notify via telegram" in text or "telegram me" in text:
        return "telegram"
    if "send to email" in text or "email me" in text or "notify via email" in text:
        return "email"
    return None


async def _deliver_to_channel(
    db: AsyncSession,
    task: ScheduledTask,
    run_result: str,
    *,
    target_channel: str,
    telegram_chat_id: str | None = None,
) -> None:
    """Deliver task result to specified channel."""
    if target_channel == "telegram" and telegram_chat_id:
        tok = await _get_telegram_token(db, task.user_id)
        if tok:
            await send_telegram_text(telegram_chat_id, run_result, bot_token=tok)


async def run_scheduled_tasks(ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    now_utc = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        due_ids = list(
            (
                await db.execute(
                    select(ScheduledTask.id)
                    .where(
                        ScheduledTask.enabled.is_(True),
                        ScheduledTask.next_run_at <= now_utc,
                    )
                    .order_by(ScheduledTask.next_run_at.asc(), ScheduledTask.id.asc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
    if not due_ids:
        return {"ok": True, "processed": 0}

    processed = 0
    failures = 0
    for task_id in due_ids:
        try:
            async with AsyncSessionLocal() as db:
                task = await db.get(ScheduledTask, task_id)
                if task is None or not task.enabled or task.next_run_at > datetime.now(UTC):
                    continue
                task.next_run_at = ScheduledTaskService.compute_next_run(now_utc=datetime.now(UTC), task=task)
                if task.schedule_type == "once":
                    task.enabled = False
                task.last_status = "running"
                task.last_error = None
                await db.commit()

                user = await db.get(User, task.user_id)
                if user is None or not user.is_active:
                    task.enabled = False
                    task.last_status = "disabled"
                    task.last_error = "User is inactive or missing."
                    await db.commit()
                    continue

                instruction_preference = _parse_delivery_preference(task.instruction)
                delivery_channel = instruction_preference or task.source_channel or "web"

                thread = ChatThread(
                    user_id=user.id,
                    kind="automation",
                    title=task.name[:255],
                )
                db.add(thread)
                await db.flush()

                run = await AgentService.run_agent(
                    db,
                    user,
                    _scheduled_task_prompt(task, now_utc=datetime.now(UTC)),
                    turn_profile=TURN_PROFILE_AUTOMATION,
                    thread_id=thread.id,
                    agent_ctx={"source_channel": delivery_channel},
                )

                asst_msg = await append_message(
                    db,
                    thread,
                    role="assistant",
                    content=run.assistant_reply or run.error or "",
                    agent_run_id=run.id,
                )
                thread.last_message_at = datetime.now(UTC)

                telegram_chat_id = None
                if delivery_channel == "telegram":
                    result = await db.execute(
                        select(ChannelThreadBinding.external_key).where(
                            ChannelThreadBinding.user_id == user.id,
                            ChannelThreadBinding.channel == "telegram",
                        ).limit(1)
                    )
                    binding = result.scalar_one_or_none()
                    if binding:
                        telegram_chat_id = binding
                        await send_telegram_text(
                            telegram_chat_id,
                            run.assistant_reply or run.error or "(no output)",
                        )
                else:
                    logger.info(
                        "Scheduled task completed for user_id=%s, agent handles delivery",
                        user.id,
                    )

                await db.refresh(task)
                task.last_run_at = datetime.now(UTC)
                task.run_count = int(task.run_count or 0) + 1
                task.last_status = run.status
                task.last_error = (run.error or "")[:2000] if run.status != "completed" else None
                await db.commit()
                processed += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.exception("scheduled task execution failed task_id=%s: %s", task_id, exc)
            try:
                async with AsyncSessionLocal() as db:
                    task = await db.get(ScheduledTask, task_id)
                    if task is not None:
                        task.last_status = "failed"
                        task.last_error = str(exc)[:2000]
                        await db.commit()
            except Exception:
                logger.exception("scheduled task failure-state update failed task_id=%s", task_id)
    return {"ok": True, "processed": processed, "failures": failures}


async def agent_memory_consolidation_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Minute-level cron: run global consolidation when the time slot matches ``AGENT_MEMORY_CONSOLIDATION_MINUTES``."""
    del ctx
    if not getattr(settings, "agent_memory_consolidation_enabled", True):
        return {"skipped": True, "reason": "disabled"}
    interval = max(1, int(getattr(settings, "agent_memory_consolidation_minutes", 360)))
    if int(time.time() // 60) % interval != 0:
        return {"skipped": True, "reason": "not_due"}
    return await run_consolidation_for_all_active_users()


class WorkerSettings:
    """ARQ discovers this class. Referenced as ``app.worker.WorkerSettings``."""

    functions = [
        agent_heartbeat,
        run_chat_agent_turn,
        flag_stuck_agent_runs,
        agent_memory_consolidation_tick,
        run_scheduled_tasks,
    ]
    cron_jobs = [
        cron(agent_heartbeat, minute=_heartbeat_minutes(), run_at_startup=False),
        cron(run_scheduled_tasks, minute=set(range(60)), run_at_startup=False),
        cron(flag_stuck_agent_runs, minute=set(range(60)), run_at_startup=False),
        cron(agent_memory_consolidation_tick, minute=set(range(60)), run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 300
    redis_settings = _redis_settings()
