from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr

from app.schemas.common import ORMBaseModel


class EmailCreate(BaseModel):
    contact_id: int | None = None
    sender_email: EmailStr
    sender_name: str | None = None
    subject: str
    body: str
    received_at: datetime | None = None
    raw_headers: dict[str, Any] | None = None


class EmailRead(ORMBaseModel):
    id: int
    contact_id: int | None = None
    sender_email: EmailStr
    sender_name: str | None = None
    subject: str
    body: str
    received_at: datetime
    raw_headers: dict[str, Any] | None = None
    created_at: datetime
    triage_category: str | None = None
    triage_reason: str | None = None
    triage_source: str | None = None
    triage_at: datetime | None = None
