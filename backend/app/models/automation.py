"""Automations: user-defined rules that enqueue an agent run when an inbound event matches.

A rule consists of:
- A trigger (`email_received` for now; `event_created` / `file_modified` reserved for later).
- A JSON `conditions` dict with optional matchers (from_contains / subject_contains / body_contains
  / direction / provider). All supplied matchers must be true.
- A `prompt_template` string — a free-form instruction handed to the agent. `{subject}`, `{from}`,
  `{body}`, `{thread_id}`, `{email_id}` placeholders are interpolated before the run.
- An optional default `connection_id` + `auto_approve` switch (auto_approve=False is the safe
  default; the agent will still propose but not execute).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # email_received | ...
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prompt_template: Mapped[str] = mapped_column(String(8000), nullable=False)
    default_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("connector_connections.id", ondelete="SET NULL"), nullable=True
    )
    auto_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User")
