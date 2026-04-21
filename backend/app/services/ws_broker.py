"""In-process WebSocket registry + Redis subscriber fan-out (one per API process)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import redis.asyncio as redis
from fastapi import WebSocket

from app.core.config import settings
from app.services.agent_event_bus import AGENT_EVENTS_CHANNEL, close_event_bus_redis

logger = logging.getLogger(__name__)


class WsConnectionManager:
    def __init__(self) -> None:
        self._by_user: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._by_user.setdefault(user_id, set()).add(ws)

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            s = self._by_user.get(user_id)
            if s and ws in s:
                s.discard(ws)
                if not s:
                    self._by_user.pop(user_id, None)

    async def send_to_user(self, user_id: int, text: str) -> None:
        async with self._lock:
            targets = list(self._by_user.get(user_id, ()))
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                with contextlib.suppress(Exception):
                    await self.disconnect(user_id, ws)


ws_manager = WsConnectionManager()

_subscriber_client: redis.Redis | None = None


async def run_redis_subscriber_loop() -> None:
    """Subscribes to :data:`AGENT_EVENTS_CHANNEL` and forwards JSON to the user's WebSockets."""
    if not (settings.redis_url or "").strip():
        logger.info("ws broker: no REDIS_URL, skipping Redis subscriber")
        return
    global _subscriber_client
    _subscriber_client = redis.from_url(settings.redis_url, decode_responses=True)
    r = _subscriber_client
    pubsub = r.pubsub()
    await pubsub.subscribe(AGENT_EVENTS_CHANNEL)
    logger.info("ws broker: subscribed to %s", AGENT_EVENTS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            try:
                payload = json.loads(data)
                uid = int(payload.get("user_id", 0))
            except (ValueError, TypeError, json.JSONDecodeError, KeyError):
                continue
            if uid:
                await ws_manager.send_to_user(uid, data)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(AGENT_EVENTS_CHANNEL)
        with contextlib.suppress(Exception):
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await r.aclose()
        _subscriber_client = None
        raise
    except Exception:
        logger.exception("ws broker: Redis subscriber crashed")
        with contextlib.suppress(Exception):
            await pubsub.aclose()  # type: ignore[has-type]
        with contextlib.suppress(Exception):
            await r.aclose()
        _subscriber_client = None


async def aclose_subscriber_redis() -> None:
    global _subscriber_client
    if _subscriber_client is not None:
        with contextlib.suppress(Exception):
            await _subscriber_client.aclose()
        _subscriber_client = None
    await close_event_bus_redis()
