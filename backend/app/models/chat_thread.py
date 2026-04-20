"""Chat threads — topic-grouped conversations between the artist and the agent.

Two kinds:
- ``general``: free-form chat. The client or ``POST /threads`` creates these;
  legacy rows may still have ``is_default = TRUE`` from the old auto-created
  landing thread (no longer inserted by ``GET /threads``).
- ``entity``: bound to a specific local entity. After the OpenClaw refactor
  no first-class entity kinds remain in our DB; external resources (Gmail
  messages, calendar events, Drive files) are referenced inside chat
  message attachments using their provider IDs rather than being mirrored.
  The ``entity_type`` / ``entity_id`` columns stay so future entity kinds
  can be reintroduced without a migration.

Two DB-level uniqueness guarantees keep idempotency races safe:
- ``(user_id, entity_type, entity_id)`` for the entity case (NULLs are
  distinct in Postgres, so this only constrains entity threads — exactly
  what we want).
- A partial unique index on ``(user_id) WHERE is_default = TRUE`` (legacy;
  see migration ``0015_chat_thread_default``).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatThread(Base):
    __tablename__ = "chat_threads"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_chat_threads_user_entity"),
        Index(
            "uq_chat_threads_user_default",
            "user_id",
            unique=True,
            postgresql_where="is_default = TRUE",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="general")  # general | entity
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="General")
    # Legacy: was used for the auto-created landing thread (one per user). New threads
    # from POST /threads use False; old default rows may still be True until removed.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages = relationship(
        "ChatMessage",
        back_populates="thread",
        order_by="ChatMessage.id",
        cascade="all, delete-orphan",
    )
