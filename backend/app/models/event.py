from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Event(Base, TimestampMixin):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_event_id", name="uq_events_connection_provider_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True, index=True)
    venue_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="confirmed", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connector_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", server_default="manual", index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ical_uid: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attendees: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    recurrence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    all_day: Mapped[bool | None] = mapped_column(nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deal = relationship("Deal", back_populates="events")
