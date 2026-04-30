from __future__ import annotations

import ipaddress
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

OAuthCredentialSource = Literal["database", "environment", "none"]


class OAuthStartRequest(BaseModel):
    intent: str = Field(
        default="all",
        max_length=64,
        description="`gmail`, `calendar`, `drive`, `youtube`, `tasks`, `people`, `sheets`, `docs`, `all`, or comma list",
    )
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

    @model_validator(mode="after")
    def validate_google_redirect_base(self) -> "GoogleOAuthAppCredentialsUpdate":
        raw = self.redirect_base.strip()
        if not raw:
            return self
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise ValueError("Google OAuth redirect base must include a valid host.")
        if host == "localhost":
            return self
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError(
                    "Google OAuth redirect base must use a public domain (for example: https://app.example.com)."
                )
            return self
        if ip.is_loopback:
            return self
        raise ValueError(
            "Google OAuth redirect base cannot use an IP address. Use a public domain, or localhost for local dev."
        )


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
