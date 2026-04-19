"""Agent persistent-memory model.

This is the agent's *own* scratchpad — distinct from the chat history
(which is a transcript) and from the connector mirrors (which are gone
in the OpenClaw refactor). Each row is a key/value note the agent
wrote about the user, a recurring task, a preference, etc. The system
prompt is warmed with the most recent N memories on every chat turn,
and the ``recall_memory`` tool can search the rest by semantic
similarity over the optional embedding column.

Design notes:
- ``key`` is unique per user (UPSERT semantics). The agent picks short,
  human-readable keys like ``"prefers_concise_replies"`` or
  ``"weekly_review_day"`` — no namespacing required.
- ``content`` is free-form markdown. Keep it short; the system prompt
  injects them verbatim.
- ``embedding`` is optional. If the embedding service is down or the
  user has no embedding provider configured we still write the row,
  semantic recall just falls back to a recency-ordered list.
- ``importance`` lets the agent mark "do not forget" notes that should
  always show up in the system-prompt warmup, even when older.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_agent_memories_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
