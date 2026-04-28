from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GooglePeopleClient

# From agent_service.py (Phase 5 refactor)

) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    tid = str(args["thread_id"])
    fmt = str(args.get("format") or "metadata")
    if fmt == "metadata":
        cached = gmail_cache_get_thread(row.id, tid, fmt)
        if cached is not None:
            return cached
    client = await _gmail_client(db, row)
    payload = await client.get_thread(tid, format=fmt)
    if fmt == "metadata":
        gmail_cache_put_thread(row.id, tid, fmt, payload)

