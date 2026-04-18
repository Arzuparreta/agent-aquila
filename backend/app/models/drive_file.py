from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DriveFile(Base):
    """Metadata mirror for a Google Drive / OneDrive file. Binary content is fetched lazily."""

    __tablename__ = "drive_files"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_file_id", name="uq_drive_files_connection_provider_file"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="google_drive", server_default="google_drive")
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parents: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    owners: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    web_view_link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
