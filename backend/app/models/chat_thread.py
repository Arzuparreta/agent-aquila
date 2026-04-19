"""Chat threads — topic-grouped conversations between the artist and the agent.

Two kinds:
- ``general``: free-form chat. The artist always has exactly one *default*
  general thread (``is_default = TRUE``) auto-created on first use, plus any
  number of additional manual general threads ("Nueva conversación").
- ``entity``: bound to a specific CRM entity (contact/deal/event/email). The
  agent reuses the same thread for ongoing activity about that entity, so the
  artist sees one continuous conversation per topic.

Two DB-level uniqueness guarantees keep idempotency races safe:
- ``(user_id, entity_type, entity_id)`` for the entity case (NULLs are
  distinct in Postgres, so this only constrains entity threads — exactly
  what we want).
- A partial unique index on ``(user_id) WHERE is_default = TRUE`` for the
  default general thread (see migration ``0015_chat_thread_default``).
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
    # True only for the auto-created landing thread (one per user). Free-form manual
    # general threads created via POST /threads stay False so they can coexist.
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
