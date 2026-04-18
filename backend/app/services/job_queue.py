"""Enqueue ARQ jobs from the web process (FastAPI).

Falls back to running the job inline if Redis isn't configured. Inline runs block the request,
so they're primarily a dev convenience — set REDIS_URL + run the worker for production.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Any = None


async def _get_pool() -> Any | None:
    global _pool
    if not settings.redis_url:
        return None
    if _pool is not None:
        return _pool
    try:
        from arq import create_pool  # type: ignore[import-not-found]
        from arq.connections import RedisSettings  # type: ignore[import-not-found]

        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        return _pool
    except Exception:
        logger.exception("failed to create ARQ pool; falling back to inline")
        return None


async def enqueue(
    func: str, *args: Any, job_id: str | None = None, allow_inline: bool = True
) -> dict[str, Any]:
    """Enqueue a worker function by name. Returns {queued: true, job_id} on success.

    When Redis is not configured and `allow_inline` is True, the job runs synchronously in this
    process (dev convenience). Set `allow_inline=False` for request paths that must not block,
    such as the OAuth callback.
    """
    pool = await _get_pool()
    if pool is None:
        if not allow_inline:
            return {"queued": False, "error": "redis_not_configured"}
        from app.core.database import AsyncSessionLocal

        inline_map = {
            "gmail_initial_sync": ("app.services.gmail_sync_service", "run_initial_sync"),
            "gmail_delta_sync": ("app.services.gmail_sync_service", "run_delta_sync"),
            "calendar_initial_sync": ("app.services.calendar_sync_service", "run_initial_sync"),
            "calendar_delta_sync": ("app.services.calendar_sync_service", "run_delta_sync"),
            "drive_initial_sync": ("app.services.drive_sync_service", "run_initial_sync"),
            "drive_delta_sync": ("app.services.drive_sync_service", "run_delta_sync"),
            "drive_extract_text": ("app.services.drive_sync_service", "run_extract_text"),
            "run_automation": ("app.services.automation_service", "execute_automation"),
        }
        if func not in inline_map:
            return {"queued": False, "error": f"unknown inline job {func}"}
        module_name, attr = inline_map[func]
        mod = __import__(module_name, fromlist=[attr])
        fn = getattr(mod, attr)
        async with AsyncSessionLocal() as db:
            result = await fn(db, *args)
        return {"queued": False, "ran_inline": True, "result": result}
    kwargs: dict[str, Any] = {}
    if job_id:
        kwargs["_job_id"] = job_id
    job = await pool.enqueue_job(func, *args, **kwargs)
    return {"queued": True, "job_id": getattr(job, "job_id", None)}
