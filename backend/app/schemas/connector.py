from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConnectorConnectionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    credentials: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] | None = None
    token_expires_at: datetime | None = None
    oauth_scopes: list[str] | None = None


class ConnectorConnectionRead(BaseModel):
    id: int
    provider: str
    label: str
    meta: dict[str, Any] | None
    token_expires_at: datetime | None = None
    oauth_scopes: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorConnectionPatch(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    credentials_patch: dict[str, Any] | None = None
    token_expires_at: datetime | None = None
    oauth_scopes: list[str] | None = None
    meta: dict[str, Any] | None = None


class ConnectorPreviewRequest(BaseModel):
    connection_id: int
    action: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class ConnectorPreviewResponse(BaseModel):
    provider: str
    action: str
    risk_tier: str
    preview: dict[str, Any]


class ConnectorDryRunResponse(BaseModel):
    ok: bool
    provider: str
    action: str
    risk_tier: str
    result: dict[str, Any]
