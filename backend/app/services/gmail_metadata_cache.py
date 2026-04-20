"""In-process TTL cache for Gmail metadata reads.

Shared by FastAPI ``/gmail`` routes and agent Gmail tools so duplicate
``messages.get(format=metadata)`` and ``threads.get(format=metadata)``
calls coalesce within TTL. Full-format bodies are never cached here.
"""
from __future__ import annotations

import time
from typing import Any

_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_TTL_SECONDS = 5 * 60
_MAX_ENTRIES = 2_000


def get_message_metadata(connection_id: int, message_id: str) -> dict[str, Any] | None:
    key = (connection_id, "m", message_id)
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return payload


def put_message_metadata(connection_id: int, message_id: str, payload: dict[str, Any]) -> None:
    _evict_if_needed()
    key = (connection_id, "m", message_id)
    _CACHE[key] = (time.monotonic() + _TTL_SECONDS, payload)


def get_thread(connection_id: int, thread_id: str, format: str) -> dict[str, Any] | None:
    if format != "metadata":
        return None
    key = (connection_id, "t", thread_id, format)
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return payload


def put_thread(connection_id: int, thread_id: str, format: str, payload: dict[str, Any]) -> None:
    if format != "metadata":
        return
    _evict_if_needed()
    key = (connection_id, "t", thread_id, format)
    _CACHE[key] = (time.monotonic() + _TTL_SECONDS, payload)


def invalidate_message(connection_id: int, message_id: str) -> None:
    _CACHE.pop((connection_id, "m", message_id), None)


def invalidate_connection(connection_id: int) -> None:
    for k in [k for k in _CACHE if k[0] == connection_id]:
        _CACHE.pop(k, None)


def _evict_if_needed() -> None:
    if len(_CACHE) < _MAX_ENTRIES:
        return
    ordered = sorted(_CACHE.items(), key=lambda kv: kv[1][0], reverse=True)
    keep = dict(ordered[: int(_MAX_ENTRIES * 0.9)])
    _CACHE.clear()
    _CACHE.update(keep)
