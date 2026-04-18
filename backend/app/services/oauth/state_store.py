"""Short-lived OAuth `state` storage.

Uses Redis when `REDIS_URL` is set. Falls back to an in-process dict for single-user / dev.
The fallback is safe for self-hosted single-user but NOT for multi-process deployments.
"""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

_STATE_TTL_SECONDS = 600


@dataclass
class StatePayload:
    user_id: int
    provider: str
    intent: str
    scopes: list[str]
    redirect_after: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_id": self.user_id,
                "provider": self.provider,
                "intent": self.intent,
                "scopes": self.scopes,
                "redirect_after": self.redirect_after,
            }
        )

    @staticmethod
    def from_json(raw: str) -> "StatePayload":
        data = json.loads(raw)
        return StatePayload(
            user_id=int(data["user_id"]),
            provider=str(data["provider"]),
            intent=str(data["intent"]),
            scopes=list(data.get("scopes") or []),
            redirect_after=data.get("redirect_after"),
        )


class _InMemoryStateStore:
    """Dev-only fallback. TTL enforced lazily on read."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, str]] = {}

    def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self._entries[key] = (time.time() + ttl_seconds, value)

    def pop(self, key: str) -> str | None:
        entry = self._entries.pop(key, None)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            return None
        return value


class _RedisStateStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # type: ignore[import-not-found]

        self._redis = redis.from_url(url, decode_responses=True)

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.setex(f"oauth:state:{key}", ttl_seconds, value)

    async def pop(self, key: str) -> str | None:
        pipe = self._redis.pipeline()
        pipe.get(f"oauth:state:{key}")
        pipe.delete(f"oauth:state:{key}")
        got, _ = await pipe.execute()
        return got


_memory_store = _InMemoryStateStore()
_redis_store: _RedisStateStore | None = None


def _store() -> Any:
    global _redis_store
    if settings.redis_url and _redis_store is None:
        try:
            _redis_store = _RedisStateStore(settings.redis_url)
        except Exception:
            _redis_store = None
    return _redis_store or _memory_store


async def create_state(payload: StatePayload) -> str:
    state = secrets.token_urlsafe(32)
    store = _store()
    value = payload.to_json()
    put_result = store.put(state, value, _STATE_TTL_SECONDS)
    if hasattr(put_result, "__await__"):
        await put_result  # type: ignore[misc]
    return state


async def consume_state(state: str) -> StatePayload | None:
    if not state:
        return None
    store = _store()
    raw = store.pop(state)
    if hasattr(raw, "__await__"):
        raw = await raw  # type: ignore[assignment]
    if not raw:
        return None
    try:
        return StatePayload.from_json(raw)
    except (ValueError, KeyError):
        return None
