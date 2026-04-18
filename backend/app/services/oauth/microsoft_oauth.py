"""Microsoft Graph OAuth 2.0 (Azure AD v2.0 endpoint)."""
from __future__ import annotations

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


def is_configured() -> bool:
    return bool(settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret)


def _tenant() -> str:
    return (settings.microsoft_oauth_tenant or "common").strip() or "common"


def _authorize_url() -> str:
    return f"{AUTH_BASE}/{_tenant()}/oauth2/v2.0/authorize"


def _token_url() -> str:
    return f"{AUTH_BASE}/{_tenant()}/oauth2/v2.0/token"


def redirect_uri() -> str:
    base = settings.google_oauth_redirect_base.rstrip("/")
    return f"{base}/api/v1/oauth/microsoft/callback"


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


def build_authorize_url(state: str, scopes: list[str]) -> str:
    if not is_configured():
        raise OAuthError("Microsoft OAuth is not configured. Set MICROSOFT_OAUTH_CLIENT_ID / SECRET.")
    params = {
        "client_id": settings.microsoft_oauth_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "response_mode": "query",
        "scope": " ".join(scopes),
        "state": state,
        "prompt": "consent",
    }
    return f"{_authorize_url()}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    if not is_configured():
        raise OAuthError("Microsoft OAuth is not configured.")
    form = {
        "client_id": settings.microsoft_oauth_client_id,
        "client_secret": settings.microsoft_oauth_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(_token_url(), data=form)
    if r.status_code >= 300:
        raise OAuthError(f"Microsoft token exchange failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if "access_token" not in data:
        raise OAuthError(f"Microsoft token response missing access_token: {data}")
    return data


async def refresh_access_token(refresh_token: str, *, connection_id: int | None = None) -> dict[str, Any]:
    if not is_configured():
        raise OAuthError("Microsoft OAuth is not configured.")
    form = {
        "client_id": settings.microsoft_oauth_client_id,
        "client_secret": settings.microsoft_oauth_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(_token_url(), data=form)
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
