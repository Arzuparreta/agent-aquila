"""Scheduled task tool handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.services.scheduled_task_service import ScheduledTaskService
from app.services.user_ai_settings_service import UserAISettingsService


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


async def _tool_scheduled_task_create(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    from contextvars import ContextVar
    from app.services.agent.handlers.loop import _agent_ctx

    name = str(args.get("name") or "").strip()
    instruction = str(args.get("instruction") or "").strip()
    schedule_type = str(args.get("schedule_type") or "").strip().lower()
    if not name or not instruction:
        return {"error": "name and instruction are required"}
    prefs = await UserAISettingsService.get_or_create(db, user)
    user_timezone = getattr(prefs, "user_timezone", None)
    scheduled_at = None
    if args.get("scheduled_at"):
        from dateutil.parser import parse as parse_dt
        from zoneinfo import ZoneInfo
        from app.services.user_time_context import resolve_user_zone
        raw_scheduled = str(args.get("scheduled_at"))
        scheduled_at = parse_dt(raw_scheduled)
        if scheduled_at.tzinfo is None:
            if user_timezone:
                user_zone = resolve_user_zone(user_timezone)
                scheduled_at = scheduled_at.replace(tzinfo=user_zone)
            else:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
        scheduled_at = scheduled_at.astimezone(UTC)

    source_channel = _agent_ctx.get().get("source_channel")
    try:
        task = await ScheduledTaskService.create_task(
            db, user, name=name, instruction=instruction,
            schedule_type=schedule_type, timezone=args.get("timezone"),
            interval_minutes=args.get("interval_minutes"),
            hour_local=args.get("hour_local"),
            minute_local=args.get("minute_local"),
            cron_expr=args.get("cron_expr"),
            rrule_expr=args.get("rrule_expr"),
            weekdays=args.get("weekdays") if isinstance(args.get("weekdays"), list) else None,
            scheduled_at=scheduled_at,
            enabled=bool(args.get("enabled", True)),
            source_channel=source_channel,
        )
        await db.commit()
        await db.refresh(task)
        return {"task": _scheduled_task_to_dict(task)}
    except ValueError as exc:
        await db.rollback()
        return {"error": str(exc)}


async def _tool_scheduled_task_list(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    tasks = await ScheduledTaskService.list_tasks(
        db, user, enabled_only=bool(args.get("enabled_only", False)),
    )
    return {"tasks": [_scheduled_task_to_dict(t) for t in tasks]}


async def _tool_scheduled_task_update(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    tid_raw = args.get("task_id")
    try:
        tid = int(tid_raw)
    except (TypeError, ValueError):
        return {"error": "task_id is required"}
    task = await db.get(ScheduledTask, tid)
    if task is None or task.user_id != user.id:
        return {"error": "task_not_found"}
    if "name" in args:
        task.name = str(args.get("name") or "").strip()[:255] or task.name
    if "instruction" in args:
        instr = str(args.get("instruction") or "").strip()
        if instr:
            task.instruction = instr
    if "enabled" in args:
        task.enabled = bool(args.get("enabled"))

    schedule_fields = {
        k: args.get(k)
        for k in (
            "schedule_type", "timezone", "interval_minutes",
            "hour_local", "minute_local", "cron_expr",
            "rrule_expr", "weekdays", "scheduled_at",
        )
        if k in args
    }
    if schedule_fields:
        try:
            from dateutil.parser import parse as parse_dt
            scheduled_at_arg = None
            if schedule_fields.get("scheduled_at") is not None:
                scheduled_at_arg = parse_dt(str(schedule_fields.get("scheduled_at")))
                if scheduled_at_arg.tzinfo is None:
                    scheduled_at_arg = scheduled_at_arg.replace(tzinfo=UTC)
            normalized = ScheduledTaskService.normalize_schedule(
                schedule_type=str(schedule_fields.get("schedule_type") or task.schedule_type),
                timezone=(
                    str(schedule_fields.get("timezone"))
                    if schedule_fields.get("timezone") is not None
                    else task.timezone
                ),
                interval_minutes=(
                    int(schedule_fields.get("interval_minutes"))
                    if schedule_fields.get("interval_minutes") is not None
                    else task.interval_minutes
                ),
                hour_local=(
                    int(schedule_fields.get("hour_local"))
                    if schedule_fields.get("hour_local") is not None
                    else task.hour_local
                ),
                minute_local=(
                    int(schedule_fields.get("minute_local"))
                    if schedule_fields.get("minute_local") is not None
                    else task.minute_local
                ),
                cron_expr=(
                    str(schedule_fields.get("cron_expr"))
                    if schedule_fields.get("cron_expr") is not None
                    else task.cron_expr
                ),
                rrule_expr=(
                    str(schedule_fields.get("rrule_expr"))
                    if schedule_fields.get("rrule_expr") is not None
                    else task.rrule_expr
                ),
                weekdays=(
                    schedule_fields.get("weekdays")
                    if isinstance(schedule_fields.get("weekdays"), list)
                    else task.weekdays
                ),
                scheduled_at=scheduled_at_arg if scheduled_at_arg is not None else task.scheduled_at,
            )
        except (TypeError, ValueError) as exc:
            await db.rollback()
            return {"error": str(exc)}
        task.schedule_type = normalized["schedule_type"]
        task.timezone = normalized["timezone"]
        task.interval_minutes = normalized["interval_minutes"]
        task.hour_local = normalized["hour_local"]
        task.minute_local = normalized["minute_local"]
        task.cron_expr = normalized["cron_expr"]
        task.rrule_expr = normalized["rrule_expr"]
        task.weekdays = normalized["weekdays"]
        task.scheduled_at = normalized.get("scheduled_at")
        task.next_run_at = ScheduledTaskService.compute_next_run(now_utc=datetime.now(UTC), task=task)
    await db.commit()
    await db.refresh(task)
    return {"task": _scheduled_task_to_dict(task)}


async def _tool_scheduled_task_delete(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    tid_raw = args.get("task_id")
    try:
        tid = int(tid_raw)
    except (TypeError, ValueError):
        return {"error": "task_id is required"}
    task = await db.get(ScheduledTask, tid)
    if task is None or task.user_id != user.id:
        return {"error": "task_not_found"}
    await db.delete(task)
    await db.commit()
    return {"ok": True, "deleted_task_id": tid}
