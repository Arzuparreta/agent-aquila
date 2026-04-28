from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GoogleTasksClient

# From agent_service.py (Phase 5 refactor)



class AgentService:
@staticmethod
def _scheduled_task_to_dict(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,

        "instruction": task.instruction,
        "schedule_type": task.schedule_type,
        "timezone": task.timezone,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "interval_minutes": task.interval_minutes,
        "hour_local": task.hour_local,
        "minute_local": task.minute_local,
        "cron_expr": task.cron_expr,
        "rrule_expr": task.rrule_expr,
        "weekdays": task.weekdays,
        "enabled": bool(task.enabled),
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "run_count": int(task.run_count or 0),
        "last_status": task.last_status,
        "last_error": task.last_error,

    }

# ------------------------------------------------------------------
# Gmail tools
# ------------------------------------------------------------------
@staticmethod
async def _tool_gmail_list_messages(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    return await client.list_messages(
        page_token=args.get("page_token"),

        q=args.get("q"),
        label_ids=args.get("label_ids"),
        max_results=int(args.get("max_results") or 25),
    )

@staticmethod
async def _tool_gmail_get_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    mid = str(args["message_id"])
    fmt = str(args.get("format") or "full")
    if fmt == "metadata":
        cached = get_message_metadata(row.id, mid)
        if cached is not None:
            return cached
    client = await _gmail_client(db, row)

    payload = await client.get_message(mid, format=fmt)
    if fmt == "metadata":
        put_message_metadata(row.id, mid, payload)
    return payload

@staticmethod
async def _tool_gmail_get_thread(
    db: AsyncSession, user: User, args: dict[str, Any]

