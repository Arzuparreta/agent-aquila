"""Executed agent actions — the audit + undo trail for auto-applied operations.

When the agent runs an ``auto_apply=True`` capability (internal CRM writes), the action
is performed immediately and a row is recorded here with:
- ``kind``: same identifier used by pending proposals (e.g. ``create_deal``).
- ``payload``: the original arguments the agent supplied.
- ``reversal_payload``: enough state to undo the action. For deletes this captures the
  pre-image; for creates this is just the new entity id; for updates we keep the
  pre-image of the patched fields.
- ``reversible_until``: the cutoff after which the UNDO endpoint refuses (the FE shows a
  10-second countdown by default).
- ``reversed_at``: set when the user actually undoes.

Externally-visible failed executions also land here with ``status="failed"`` so the
artist sees what didn't work in their chat thread.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExecutedAction(Base):
    __tablename__ = "executed_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="executed", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reversal_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reversible_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
