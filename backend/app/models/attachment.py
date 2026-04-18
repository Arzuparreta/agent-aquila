"""Attachments / Archivos — files the artist uploaded directly to the agent.

Distinct from ``DriveFile`` (mirrored from Google/Microsoft cloud drives).
Stored locally on disk for now (``storage_uri`` is a relative path under the
configured upload directory). When ``extracted_text`` is present, the chunking
pipeline embeds it into ``rag_chunks`` so the agent can RAG over uploads.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
