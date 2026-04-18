from __future__ import annotations

from pydantic import BaseModel, Field


class OAuthStartRequest(BaseModel):
    intent: str = Field(default="all", max_length=64, description="`gmail`, `calendar`, `drive`, `all`, or comma list")
    redirect_after: str | None = Field(default=None, max_length=500)


class OAuthStartResponse(BaseModel):
    authorize_url: str
    state: str
    scopes: list[str]
    configured: bool


class OAuthStatusResponse(BaseModel):
    configured: bool
    redirect_uri: str
    providers: list[str]
