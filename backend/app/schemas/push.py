from __future__ import annotations

from pydantic import BaseModel, Field


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(BaseModel):
    """Mirrors the ``PushSubscription.toJSON()`` payload the browser produces."""

    endpoint: str = Field(min_length=8, max_length=2048)
    keys: PushSubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=255)


class PushSubscriptionRead(BaseModel):
    id: int
    endpoint: str


class PushPublicKeyResponse(BaseModel):
    public_key: str
    enabled: bool
