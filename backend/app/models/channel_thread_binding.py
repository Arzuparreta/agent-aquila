"""Map external channel conversations to Aquila :class:`ChatThread` rows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChannelThreadBinding(Base):
    __tablename__ = "channel_thread_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "external_key", name="uq_channel_thread_binding_user_channel_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # e.g. telegram, slack, gateway_stub — keep short stable identifiers.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # Stable id from the channel (chat id, channel+ts, etc.); max 512.
    external_key: Mapped[str] = mapped_column(String(512), nullable=False)
    chat_thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chat_thread = relationship("ChatThread", foreign_keys=[chat_thread_id])
