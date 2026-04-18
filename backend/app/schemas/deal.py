from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import TimestampSchema


class DealCreate(BaseModel):
    contact_id: int
    title: str
    status: str = "new"
    amount: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


class DealUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


class DealRead(TimestampSchema):
    id: int
    contact_id: int
    title: str
    status: str
    amount: Decimal | None = None
    currency: str | None = None
    notes: str | None = None
