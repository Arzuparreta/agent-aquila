from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.schemas.common import TimestampSchema


class EventCreate(BaseModel):
    deal_id: int | None = None
    venue_name: str
    event_date: date
    city: str | None = None
    status: str = "confirmed"
    notes: str | None = None


class EventUpdate(BaseModel):
    deal_id: int | None = None
    venue_name: str | None = None
    event_date: date | None = None
    city: str | None = None
    status: str | None = None
    notes: str | None = None


class EventRead(TimestampSchema):
    id: int
    deal_id: int | None = None
    venue_name: str
    event_date: date
    city: str | None = None
    status: str
    notes: str | None = None
