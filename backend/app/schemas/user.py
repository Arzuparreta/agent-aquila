from __future__ import annotations

from pydantic import EmailStr

from app.schemas.common import ORMBaseModel, TimestampSchema


class UserRead(TimestampSchema):
    id: int
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    is_admin: bool


class UserCreateRequest(ORMBaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class UserUpdateRequest(ORMBaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    password: str | None = None
