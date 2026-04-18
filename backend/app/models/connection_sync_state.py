from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConnectionSyncState(Base):
    """Per-(connection, resource) incremental-sync cursor + health state.

    `cursor` stores whichever opaque token the upstream API uses
    (Gmail `historyId`, Calendar `syncToken`, Drive `pageToken`, Graph `@odata.deltaLink`).
    """

    __tablename__ = "connection_sync_state"
    __table_args__ = (PrimaryKeyConstraint("connection_id", "resource", name="pk_connection_sync_state"),)

    connection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False
    )
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle", server_default="idle")
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
