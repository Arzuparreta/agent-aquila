from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.scheduled_task_service import ScheduledTaskService


def test_normalize_interval_schedule() -> None:
    out = ScheduledTaskService.normalize_schedule(schedule_type="interval", interval_minutes=30)
    assert out["schedule_type"] == "interval"
    assert out["interval_minutes"] == 30


def test_normalize_daily_schedule() -> None:
    out = ScheduledTaskService.normalize_schedule(
        schedule_type="daily",
        hour_local=21,
        minute_local=15,
        timezone="Europe/Madrid",
        weekdays=[0, 2, 4],
    )
    assert out["schedule_type"] == "daily"
    assert out["timezone"] == "Europe/Madrid"
    assert out["weekdays"] == [0, 2, 4]


def test_compute_next_run_interval() -> None:
    task = SimpleNamespace(schedule_type="interval", interval_minutes=10)
    now = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    nxt = ScheduledTaskService.compute_next_run(now_utc=now, task=task)  # type: ignore[arg-type]
    assert int((nxt - now).total_seconds()) == 600
