from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ScheduledTask(Base, TimestampMixin):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # schedule_type:
    # - interval: every N minutes
    # - daily: once per day at hh:mm in timezone (optionally restricted weekdays)
    # - cron: cron expression evaluated in timezone
    # - rrule: iCalendar RRULE string
    # - once: single future execution at scheduled_at
    schedule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hour_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minute_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rrule_expr: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekdays: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # source_channel: where the user made the request (e.g. 'web', 'telegram', 'email')
    source_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
