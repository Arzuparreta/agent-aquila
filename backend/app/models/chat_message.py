"""Chat messages persisted within a ChatThread.

Roles:
- ``user``: the artist's input (typed message, optionally with @references in ``attachments``).
- ``assistant``: the agent's reply.
- ``system``: server-generated context (e.g. "Connected to Gmail", "Setup completed").
- ``event``: proactive notifications injected by the worker ("Nuevo correo entrante de X").

``agent_run_id`` ties an assistant message back to the run that produced it (for the
inline trace dropdown). ``attachments`` carries a JSON list of structured side data,
e.g. inline action cards (kind=approval/setup) or @references the user attached.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # Client-generated idempotency token for deduplicating retried HTTP sends.
    client_token: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    thread = relationship("ChatThread", back_populates="messages")
