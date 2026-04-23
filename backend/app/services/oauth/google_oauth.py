"""Google OAuth 2.0 auth-code flow + token refresh.

Reference: https://developers.google.com/identity/protocols/oauth2/web-server
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Google Workspace scope groups. Request as a flat space-separated list.
#
# ``gmail.modify`` covers nearly every Gmail mutation the agent runs (label,
# trash/untrash, mark read/unread, send). ``gmail.settings.basic`` is the
# extra grant required by the new "create / list / delete filter" tools —
# without it the filter endpoints return 403 even though everything else
# keeps working. Existing connections from before this scope was added need
# to re-authorize once; the frontend surfaces that via a banner driven by
# ``GET /connectors`` (each row carries a ``needs_reauth`` flag derived
# from the comparison below).
SCOPES_GMAIL = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]
GMAIL_REQUIRED_SCOPES: frozenset[str] = frozenset(SCOPES_GMAIL)
SCOPES_CALENDAR = [
    "https://www.googleapis.com/auth/calendar",
]
SCOPES_DRIVE = [
    "https://www.googleapis.com/auth/drive",
]
# YouTube Data API v3 — readonly + manage + upload (upload is quota-heavy; gate uploads via proposals).
SCOPES_YOUTUBE = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]
SCOPES_TASKS = [
    "https://www.googleapis.com/auth/tasks",
]
# People API — read-only contact search for resolution (email/phone hints).
SCOPES_PEOPLE = [
    "https://www.googleapis.com/auth/contacts.readonly",
]
# Sheets — read + append (narrow write surface).
SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets",
]
# Docs — read structured content only.
SCOPES_DOCS = [
    "https://www.googleapis.com/auth/documents.readonly",
]
SCOPES_IDENTITY = ["openid", "email", "profile"]


@dataclass(frozen=True)
class GoogleOAuthRuntimeConfig:
    client_id: str
    client_secret: str
    redirect_base: str


def runtime_config_from_env() -> GoogleOAuthRuntimeConfig:
    """Env-only snapshot (used by the provider registry and legacy call sites)."""
    return GoogleOAuthRuntimeConfig(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        redirect_base=settings.google_oauth_redirect_base,
    )


def is_runtime_ready(config: GoogleOAuthRuntimeConfig) -> bool:
    return bool(config.client_id and config.client_secret)


def redirect_uri_for(config: GoogleOAuthRuntimeConfig) -> str:
    base = config.redirect_base.rstrip("/")
    return f"{base}/api/v1/oauth/google/callback"


def redirect_uri() -> str:
    return redirect_uri_for(runtime_config_from_env())


def is_configured() -> bool:
    return is_runtime_ready(runtime_config_from_env())


def build_authorize_url(
    state: str, scopes: list[str], config: GoogleOAuthRuntimeConfig | None = None
) -> str:
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError(
            "Google OAuth is not configured. Add your Google app Client ID and secret under Settings, "
            "or set GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET on the server."
        )
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri_for(cfg),
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def scopes_for_intent(intent: str) -> list[str]:
    """Translate an `intent` string from the UI into the concrete scope list."""
    parts = {p.strip().lower() for p in (intent or "all").split(",") if p.strip()}
    if "all" in parts or not parts:
        parts = {"gmail", "calendar", "drive", "youtube", "tasks", "people", "sheets", "docs"}
    selected: list[str] = list(SCOPES_IDENTITY)
    if "gmail" in parts:
        selected += SCOPES_GMAIL
    if "calendar" in parts:
        selected += SCOPES_CALENDAR
    if "drive" in parts:
        selected += SCOPES_DRIVE
    if "youtube" in parts:
        selected += SCOPES_YOUTUBE
    if "tasks" in parts:
        selected += SCOPES_TASKS
    if "people" in parts:
        selected += SCOPES_PEOPLE
    if "sheets" in parts:
        selected += SCOPES_SHEETS
    if "docs" in parts:
        selected += SCOPES_DOCS
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for s in selected:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def provider_ids_for_scopes(scopes: list[str]) -> list[str]:
    """Map granted scopes → per-product connector provider ids we create in the DB."""
    out: list[str] = []
    joined = " ".join(scopes)
    if "/auth/gmail" in joined:
        out.append("google_gmail")
    if "/auth/calendar" in joined:
        out.append("google_calendar")
    if "/auth/drive" in joined:
        out.append("google_drive")
    if "/auth/youtube" in joined:
        out.append("google_youtube")
    if "/auth/tasks" in joined:
        out.append("google_tasks")
    if "/auth/contacts" in joined:
        out.append("google_people")
    if "/auth/spreadsheets" in joined:
        out.append("google_sheets")
    if "/auth/documents" in joined:
        out.append("google_docs")
    return out


async def exchange_code(code: str, config: GoogleOAuthRuntimeConfig | None = None) -> dict[str, Any]:
    """Trade an auth code for access + refresh tokens. Returns the raw Google JSON."""
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError("Google OAuth is not configured.")
    form = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri_for(cfg),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(TOKEN_URL, data=form)
    if r.status_code >= 300:
        raise OAuthError(f"Google token exchange failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if "access_token" not in data:
        raise OAuthError(f"Google token response missing access_token: {data}")
    return data


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code >= 300:
        return {}
    return r.json()


async def refresh_access_token(
    refresh_token: str,
    *,
    connection_id: int | None = None,
    config: GoogleOAuthRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Use a stored refresh_token to mint a fresh access_token. Raises ConnectorNeedsReauth on 400/401."""
    cfg = config or runtime_config_from_env()
    if not is_runtime_ready(cfg):
        raise OAuthError("Google OAuth is not configured.")
    form = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(TOKEN_URL, data=form)
    if r.status_code in (400, 401):
        raise ConnectorNeedsReauth(connection_id, "google", r.text[:300])
    if r.status_code >= 300:
        raise OAuthError(f"Google token refresh failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    if "access_token" not in data:
        raise OAuthError(f"Google refresh response missing access_token: {data}")
    return data


def compute_expires_at(token_payload: dict[str, Any]) -> datetime | None:
    """Google returns `expires_in` seconds. Convert to an absolute UTC timestamp."""
    exp = token_payload.get("expires_in")
    if exp is None:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(exp) - 30)
    except (TypeError, ValueError):
        return None
