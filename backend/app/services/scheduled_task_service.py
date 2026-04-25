from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_task import ScheduledTask
from app.models.user import User


def _safe_tz(name: str | None) -> ZoneInfo:
    txt = str(name or "").strip()
    if not txt:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(txt)
    except Exception:
        return ZoneInfo("UTC")


def _next_daily_local_run(
    *,
    now_utc: datetime,
    timezone: str | None,
    hour_local: int,
    minute_local: int,
    weekdays: list[int] | None = None,
) -> datetime:
    tz = _safe_tz(timezone)
    local_now = now_utc.astimezone(tz)
    allowed = set(int(x) for x in (weekdays or []))
    for add_days in range(0, 14):
        d = (local_now + timedelta(days=add_days)).date()
        candidate = datetime(
            d.year, d.month, d.day, int(hour_local), int(minute_local), tzinfo=tz
        )
        if candidate <= local_now:
            continue
        if allowed and candidate.weekday() not in allowed:
            continue
        return candidate.astimezone(UTC)
    # Safety fallback: one day later at requested wall time.
    fallback = local_now + timedelta(days=1)
    return datetime(
        fallback.year,
        fallback.month,
        fallback.day,
        int(hour_local),
        int(minute_local),
        tzinfo=tz,
    ).astimezone(UTC)


class ScheduledTaskService:
    @staticmethod
    def normalize_schedule(
        *,
        schedule_type: str,
        timezone: str | None = None,
        interval_minutes: int | None = None,
        hour_local: int | None = None,
        minute_local: int | None = None,
        weekdays: list[int] | None = None,
    ) -> dict[str, Any]:
        st = str(schedule_type or "").strip().lower()
        if st not in {"interval", "daily"}:
            raise ValueError("schedule_type must be 'interval' or 'daily'")
        if st == "interval":
            mins = int(interval_minutes or 0)
            if mins < 1 or mins > 10080:
                raise ValueError("interval_minutes must be in [1, 10080]")
            return {
                "schedule_type": "interval",
                "timezone": None,
                "interval_minutes": mins,
                "hour_local": None,
                "minute_local": None,
                "weekdays": None,
            }
        h = int(hour_local if hour_local is not None else -1)
        m = int(minute_local if minute_local is not None else -1)
        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError("daily schedules require hour_local [0..23] and minute_local [0..59]")
        cleaned_weekdays: list[int] | None = None
        if weekdays is not None:
            cleaned_weekdays = []
            for x in weekdays:
                v = int(x)
                if v < 0 or v > 6:
                    raise ValueError("weekdays must contain integers in [0..6] (Mon=0)")
                if v not in cleaned_weekdays:
                    cleaned_weekdays.append(v)
        tz_name = str(timezone or "").strip() or "UTC"
        _safe_tz(tz_name)  # validate fallback-safe
        return {
            "schedule_type": "daily",
            "timezone": tz_name,
            "interval_minutes": None,
            "hour_local": h,
            "minute_local": m,
            "weekdays": cleaned_weekdays,
        }

    @staticmethod
    def compute_next_run(*, now_utc: datetime, task: ScheduledTask) -> datetime:
        st = (task.schedule_type or "").strip().lower()
        if st == "interval":
            mins = int(task.interval_minutes or 1)
            return now_utc + timedelta(minutes=max(1, mins))
        return _next_daily_local_run(
            now_utc=now_utc,
            timezone=task.timezone,
            hour_local=int(task.hour_local or 0),
            minute_local=int(task.minute_local or 0),
            weekdays=task.weekdays if isinstance(task.weekdays, list) else None,
        )

    @staticmethod
    async def create_task(
        db: AsyncSession,
        user: User,
        *,
        name: str,
        instruction: str,
        schedule_type: str,
        timezone: str | None = None,
        interval_minutes: int | None = None,
        hour_local: int | None = None,
        minute_local: int | None = None,
        weekdays: list[int] | None = None,
        enabled: bool = True,
        metadata_json: dict[str, Any] | None = None,
    ) -> ScheduledTask:
        now_utc = datetime.now(UTC)
        normalized = ScheduledTaskService.normalize_schedule(
            schedule_type=schedule_type,
            timezone=timezone,
            interval_minutes=interval_minutes,
            hour_local=hour_local,
            minute_local=minute_local,
            weekdays=weekdays,
        )
        row = ScheduledTask(
            user_id=user.id,
            name=name.strip()[:255] or "Scheduled task",
            instruction=instruction.strip(),
            schedule_type=normalized["schedule_type"],
            timezone=normalized["timezone"],
            interval_minutes=normalized["interval_minutes"],
            hour_local=normalized["hour_local"],
            minute_local=normalized["minute_local"],
            weekdays=normalized["weekdays"],
            metadata_json=metadata_json if isinstance(metadata_json, dict) else None,
            enabled=bool(enabled),
            next_run_at=now_utc,
        )
        row.next_run_at = ScheduledTaskService.compute_next_run(now_utc=now_utc, task=row)
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_tasks(db: AsyncSession, user: User, *, enabled_only: bool = False) -> list[ScheduledTask]:
        stmt = select(ScheduledTask).where(ScheduledTask.user_id == user.id)
        if enabled_only:
            stmt = stmt.where(ScheduledTask.enabled.is_(True))
        stmt = stmt.order_by(ScheduledTask.next_run_at.asc(), ScheduledTask.id.asc())
        rows = (await db.execute(stmt)).scalars().all()
        return list(rows)
