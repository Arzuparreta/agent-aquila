"""ARQ worker entrypoint: background sync for Gmail / Calendar / Drive.

Run with:
    arq app.worker.WorkerSettings

The worker shares the app's SQLAlchemy engine and DB URL (via `settings.database_url`).
"""
from __future__ import annotations

import logging
from typing import Any

from arq import cron  # type: ignore[import-not-found]
from arq.connections import RedisSettings  # type: ignore[import-not-found]

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")


async def gmail_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.gmail_sync_service import run_initial_sync

    async with AsyncSessionLocal() as db:
        return await run_initial_sync(db, connection_id)


async def gmail_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.gmail_sync_service import run_delta_sync

    async with AsyncSessionLocal() as db:
        return await run_delta_sync(db, connection_id)


async def gmail_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron tick: enqueue a delta sync for every active Gmail connection."""
    from app.services.gmail_sync_service import list_active_gmail_connections

    redis = ctx["redis"]
    enqueued: list[int] = []
    async with AsyncSessionLocal() as db:
        conns = await list_active_gmail_connections(db)
    for c in conns:
        await redis.enqueue_job("gmail_delta_sync", c.id, _job_id=f"gmail-delta-{c.id}")
        enqueued.append(c.id)
    return {"enqueued": enqueued}


async def calendar_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.calendar_sync_service import run_initial_sync

    async with AsyncSessionLocal() as db:
        return await run_initial_sync(db, connection_id)


async def calendar_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.calendar_sync_service import run_delta_sync

    async with AsyncSessionLocal() as db:
        return await run_delta_sync(db, connection_id)


async def calendar_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    from app.services.calendar_sync_service import list_active_calendar_connections

    redis = ctx["redis"]
    enqueued: list[int] = []
    async with AsyncSessionLocal() as db:
        conns = await list_active_calendar_connections(db)
    for c in conns:
        await redis.enqueue_job("calendar_delta_sync", c.id, _job_id=f"calendar-delta-{c.id}")
        enqueued.append(c.id)
    return {"enqueued": enqueued}


async def drive_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.drive_sync_service import run_initial_sync

    async with AsyncSessionLocal() as db:
        return await run_initial_sync(db, connection_id)


async def drive_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.drive_sync_service import run_delta_sync

    async with AsyncSessionLocal() as db:
        return await run_delta_sync(db, connection_id)


async def drive_extract_text(ctx: dict[str, Any], file_id: int) -> dict[str, Any]:
    from app.services.drive_sync_service import run_extract_text

    async with AsyncSessionLocal() as db:
        return await run_extract_text(db, file_id)


async def drive_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    from app.services.drive_sync_service import list_active_drive_connections

    redis = ctx["redis"]
    enqueued: list[int] = []
    async with AsyncSessionLocal() as db:
        conns = await list_active_drive_connections(db)
    for c in conns:
        await redis.enqueue_job("drive_delta_sync", c.id, _job_id=f"drive-delta-{c.id}")
        enqueued.append(c.id)
    return {"enqueued": enqueued}


async def graph_mail_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_mail_initial

    async with AsyncSessionLocal() as db:
        return await run_mail_initial(db, connection_id)


async def graph_mail_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_mail_delta

    async with AsyncSessionLocal() as db:
        return await run_mail_delta(db, connection_id)


async def graph_calendar_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_calendar_initial

    async with AsyncSessionLocal() as db:
        return await run_calendar_initial(db, connection_id)


async def graph_calendar_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_calendar_delta

    async with AsyncSessionLocal() as db:
        return await run_calendar_delta(db, connection_id)


async def graph_drive_initial_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_drive_initial

    async with AsyncSessionLocal() as db:
        return await run_drive_initial(db, connection_id)


async def graph_drive_delta_sync(ctx: dict[str, Any], connection_id: int) -> dict[str, Any]:
    from app.services.graph_sync_service import run_drive_delta

    async with AsyncSessionLocal() as db:
        return await run_drive_delta(db, connection_id)


async def graph_tick(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron tick: enqueue a delta sync for every active Microsoft Graph connection."""
    from app.services.graph_sync_service import list_active_connections

    redis = ctx["redis"]
    enqueued: list[tuple[str, int]] = []
    async with AsyncSessionLocal() as db:
        mail = await list_active_connections(db, {"graph_mail"})
        cal = await list_active_connections(db, {"graph_calendar"})
        drv = await list_active_connections(db, {"graph_onedrive"})
    for c in mail:
        await redis.enqueue_job("graph_mail_delta_sync", c.id, _job_id=f"graph-mail-delta-{c.id}")
        enqueued.append(("mail", c.id))
    for c in cal:
        await redis.enqueue_job("graph_calendar_delta_sync", c.id, _job_id=f"graph-calendar-delta-{c.id}")
        enqueued.append(("calendar", c.id))
    for c in drv:
        await redis.enqueue_job("graph_drive_delta_sync", c.id, _job_id=f"graph-drive-delta-{c.id}")
        enqueued.append(("drive", c.id))
    return {"enqueued": enqueued}


async def run_automation(ctx: dict[str, Any], automation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.automation_service import execute_automation

    async with AsyncSessionLocal() as db:
        return await execute_automation(db, automation_id, payload)


async def startup(ctx: dict[str, Any]) -> None:
    logger.info("worker started; redis=%s db=%s", settings.redis_url, settings.database_url.split("@")[-1])


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker shutdown")


class WorkerSettings:
    """ARQ discovers this class. Referenced as `app.worker.WorkerSettings`."""

    functions = [
        gmail_initial_sync,
        gmail_delta_sync,
        gmail_tick,
        calendar_initial_sync,
        calendar_delta_sync,
        calendar_tick,
        drive_initial_sync,
        drive_delta_sync,
        drive_extract_text,
        drive_tick,
        graph_mail_initial_sync,
        graph_mail_delta_sync,
        graph_calendar_initial_sync,
        graph_calendar_delta_sync,
        graph_drive_initial_sync,
        graph_drive_delta_sync,
        graph_tick,
        run_automation,
    ]
    cron_jobs = [
        cron(
            gmail_tick,
            minute=set(range(0, 60, max(1, settings.gmail_delta_poll_seconds // 60) or 2)),
            run_at_startup=True,
        ),
        cron(
            calendar_tick,
            minute=set(range(0, 60, max(1, settings.calendar_delta_poll_seconds // 60) or 5)),
            run_at_startup=True,
        ),
        cron(
            drive_tick,
            minute=set(range(0, 60, max(1, settings.drive_delta_poll_seconds // 60) or 5)),
            run_at_startup=True,
        ),
        cron(
            graph_tick,
            minute=set(range(0, 60, max(1, settings.gmail_delta_poll_seconds // 60) or 2)),
            run_at_startup=True,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 300
    redis_settings = _redis_settings()
