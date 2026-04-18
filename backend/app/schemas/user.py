from __future__ import annotations

from pydantic import EmailStr

from app.schemas.common import TimestampSchema


class UserRead(TimestampSchema):
    id: int
    email: EmailStr
    full_name: str | None = None
    is_active: bool
