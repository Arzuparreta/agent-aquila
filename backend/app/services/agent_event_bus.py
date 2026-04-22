"""Publish agent run lifecycle events to Redis (and optional DB outbox) for WebSocket fan-out."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent_user_event import AgentUserEvent

logger = logging.getLogger(__name__)

AGENT_EVENTS_CHANNEL = "aquila:agent_events"

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
    global _redis
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    if _redis is None:
        _redis = redis.from_url(url, decode_responses=True)
    return _redis


async def publish_run_status_event(
    *,
    user_id: int,
    run_id: int,
    status: str,
    error: str | None = None,
    step_count: int = 0,
    chat_thread_id: int | None = None,
    terminal: bool = False,
    persist_outbox: bool = True,
    attention: dict[str, Any] | None = None,
) -> None:
    """Emit a versioned JSON event to Redis and append ``agent_user_events`` (when enabled).

    Call **after** the database transaction that changed run state has committed.
    """
    payload: dict[str, Any] = {
        "v": 1,
        "t": "run.status",
        "user_id": user_id,
        "run_id": run_id,
        "status": status,
        "error": error,
        "step_count": step_count,
        "chat_thread_id": chat_thread_id,
        "terminal": terminal,
    }
    if attention is not None:
        payload["attention"] = attention
    if persist_outbox:
        try:
            async with AsyncSessionLocal() as db:
                db.add(
                    AgentUserEvent(
                        user_id=user_id,
                        run_id=run_id,
                        kind="run.status",
                        payload=payload,
                    )
                )
                await db.commit()
        except Exception:
            logger.exception("agent_user_events insert failed run_id=%s", run_id)

    r = _get_redis()
    if r is None:
        return
    try:
        await r.publish(AGENT_EVENTS_CHANNEL, json.dumps(payload, default=str))
    except Exception:
        logger.exception("Redis publish failed run_id=%s", run_id)


async def close_event_bus_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            logger.exception("closing event bus redis")
        _redis = None
