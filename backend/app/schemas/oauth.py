from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OAuthCredentialSource = Literal["database", "environment", "none"]


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


class GoogleOAuthAppCredentialsResponse(BaseModel):
    """Google Cloud *application* OAuth client — configured in-app, not per-user."""

    client_id: str
    redirect_base: str
    redirect_uri: str
    configured: bool
    has_saved_secret: bool
    client_id_source: OAuthCredentialSource
    client_secret_source: OAuthCredentialSource


class GoogleOAuthAppCredentialsUpdate(BaseModel):
    client_id: str = Field(default="", max_length=512)
    client_secret: str | None = Field(default=None, max_length=512)
    redirect_base: str = Field(default="", max_length=1024)


class MicrosoftOAuthAppCredentialsResponse(BaseModel):
    """Azure AD *application* OAuth client — configured in-app, not per-user."""

    client_id: str
    tenant: str
    redirect_base: str
    redirect_uri: str
    configured: bool
    has_saved_secret: bool
    client_id_source: OAuthCredentialSource
    client_secret_source: OAuthCredentialSource
    tenant_source: OAuthCredentialSource


class MicrosoftOAuthAppCredentialsUpdate(BaseModel):
    client_id: str = Field(default="", max_length=512)
    client_secret: str | None = Field(default=None, max_length=512)
    tenant: str = Field(default="common", max_length=64)
    redirect_base: str = Field(default="", max_length=1024)
