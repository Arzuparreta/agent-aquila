"""Tiny ARQ enqueue helper.

The worker registers ``agent_heartbeat`` and ``run_chat_agent_turn`` (see
``app.worker``). Chat enqueues ``run_chat_agent_turn`` when
``AGENT_ASYNC_RUNS`` is true and ``REDIS_URL`` is set so long agent turns
do not block the HTTP request through the Next.js dev proxy.
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
        logger.exception("failed to create ARQ pool")
        return None


async def enqueue(
    func: str, *args: Any, job_id: str | None = None
) -> dict[str, Any]:
    """Enqueue a worker function by name. Returns ``{queued: true}`` on success."""
    pool = await _get_pool()
    if pool is None:
        return {"queued": False, "error": "redis_not_configured"}
    kwargs: dict[str, Any] = {}
    if job_id:
        kwargs["_job_id"] = job_id
    job = await pool.enqueue_job(func, *args, **kwargs)
    return {"queued": True, "job_id": getattr(job, "job_id", None)}
