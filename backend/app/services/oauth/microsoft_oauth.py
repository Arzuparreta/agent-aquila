"""Microsoft Graph OAuth 2.0 (Azure AD v2.0 endpoint)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

AUTH_BASE = "https://login.microsoftonline.com"
USERINFO_URL = "https://graph.microsoft.com/v1.0/me"

SCOPES_MAIL = ["Mail.ReadWrite", "Mail.Send"]
SCOPES_CALENDAR = ["Calendars.ReadWrite"]
SCOPES_DRIVE = ["Files.ReadWrite.All"]
SCOPES_TEAMS = ["ChannelMessage.Send", "ChannelMessage.Read.All"]
SCOPES_IDENTITY = ["openid", "email", "profile", "offline_access", "User.Read"]


@dataclass(frozen=True)
class MicrosoftOAuthRuntimeConfig:
    client_id: str
    client_secret: str
    tenant: str


def runtime_config_from_env() -> MicrosoftOAuthRuntimeConfig:
    return MicrosoftOAuthRuntimeConfig(
        client_id=settings.microsoft_oauth_client_id,
        client_secret=settings.microsoft_oauth_client_secret,
        tenant=(settings.microsoft_oauth_tenant or "common").strip() or "common",
    )


def is_runtime_ready(config: MicrosoftOAuthRuntimeConfig) -> bool:
    return bool(config.client_id and config.client_secret)


def _tenant_normalized(config: MicrosoftOAuthRuntimeConfig) -> str:
    return (config.tenant or "common").strip() or "common"


def authorize_url_for_tenant(tenant: str) -> str:
    t = (tenant or "common").strip() or "common"
    return f"{AUTH_BASE}/{t}/oauth2/v2.0/authorize"


def token_url_for_tenant(tenant: str) -> str:
    t = (tenant or "common").strip() or "common"
    return f"{AUTH_BASE}/{t}/oauth2/v2.0/token"


def redirect_uri_for_base(base: str) -> str:
    return f"{base.rstrip('/')}/api/v1/oauth/microsoft/callback"


def redirect_uri() -> str:
    return redirect_uri_for_base(settings.google_oauth_redirect_base)


def is_configured() -> bool:
    return is_runtime_ready(runtime_config_from_env())


def scopes_for_intent(intent: str) -> list[str]:
    parts = {p.strip().lower() for p in (intent or "all").split(",") if p.strip()}
    if "all" in parts or not parts:
        parts = {"mail", "calendar", "drive"}
    selected: list[str] = list(SCOPES_IDENTITY)
    if "mail" in parts or "gmail" in parts:
        selected += SCOPES_MAIL
    if "calendar" in parts:
        selected += SCOPES_CALENDAR
    if "drive" in parts or "onedrive" in parts:
        selected += SCOPES_DRIVE
    if "teams" in parts:
        selected += SCOPES_TEAMS
    seen: set[str] = set()
    out: list[str] = []
    for s in selected:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def provider_ids_for_scopes(scopes: list[str]) -> list[str]:
    joined = " ".join(scopes)
    out: list[str] = []
    if "Mail." in joined:
        out.append("graph_mail")
    if "Calendars." in joined:
        out.append("graph_calendar")
    if "Files." in joined:
        out.append("graph_onedrive")
    if "ChannelMessage." in joined:
        out.append("graph_teams")
    return out


def build_authorize_url(
    state: str,
    scopes: list[str],
    config: MicrosoftOAuthRuntimeConfig | None = None,
    *,
    redirect_uri_override: str | None = None,
) -> str:
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError(
            "Microsoft OAuth is not configured. Add your Azure app Client ID and secret under Settings, "
            "or set MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET on the server."
        )
    redir = redirect_uri_override or redirect_uri()
    tenant = _tenant_normalized(cfg)
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "redirect_uri": redir,
        "response_mode": "query",
        "scope": " ".join(scopes),
        "state": state,
        "prompt": "consent",
    }
    return f"{authorize_url_for_tenant(tenant)}?{urlencode(params)}"


async def exchange_code(
    code: str,
    config: MicrosoftOAuthRuntimeConfig | None = None,
    *,
    redirect_uri_override: str | None = None,
) -> dict[str, Any]:
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError("Microsoft OAuth is not configured.")
    redir = redirect_uri_override or redirect_uri()
    tenant = _tenant_normalized(cfg)
    form = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redir,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(token_url_for_tenant(tenant), data=form)
    if r.status_code >= 300:
        raise OAuthError(f"Microsoft token exchange failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if "access_token" not in data:
        raise OAuthError(f"Microsoft token response missing access_token: {data}")
    return data


async def refresh_access_token(
    refresh_token: str,
    *,
    connection_id: int | None = None,
    config: MicrosoftOAuthRuntimeConfig | None = None,
) -> dict[str, Any]:
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError("Microsoft OAuth is not configured.")
    tenant = _tenant_normalized(cfg)
    form = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(token_url_for_tenant(tenant), data=form)
    if r.status_code in (400, 401):
        raise ConnectorNeedsReauth(connection_id, "microsoft", r.text[:300])
    if r.status_code >= 300:
        raise OAuthError(f"Microsoft token refresh failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if "access_token" not in data:
        raise OAuthError(f"Microsoft refresh response missing access_token: {data}")
    return data


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code >= 300:
        return {}
    return r.json()


def compute_expires_at(token_payload: dict[str, Any]) -> datetime | None:
    exp = token_payload.get("expires_in")
    if exp is None:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(exp) - 30)
    except (TypeError, ValueError):
        return None
