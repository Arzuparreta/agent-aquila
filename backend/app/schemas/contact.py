from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.common import TimestampSchema


class ContactCreate(BaseModel):
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    role: str = "other"
    notes: str | None = None


class ContactUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    role: str | None = None
    notes: str | None = None


class ContactRead(TimestampSchema):
    id: int
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    role: str
    notes: str | None = None
