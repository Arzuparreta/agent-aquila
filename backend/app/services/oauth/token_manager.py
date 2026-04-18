"""Single entry point every adapter must use to obtain a valid access token.

Refreshes the token in-place (via the stored refresh_token) if it is expired or about to expire,
persists the rotated credentials back into the encrypted `ConnectorConnection.credentials_encrypted`
column, and returns the fresh access token.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.services.connector_service import ConnectorService
from app.services.instance_oauth_service import get_google_runtime_config, get_microsoft_runtime_config
from app.services.oauth import google_oauth, microsoft_oauth
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

_GOOGLE_PROVIDERS = {"google_gmail", "gmail", "google_calendar", "gcal", "google_drive", "gdrive"}
_MICROSOFT_PROVIDERS = {"graph_mail", "graph_calendar", "graph_onedrive", "graph_teams", "ms_teams"}
_REFRESH_SKEW = timedelta(seconds=90)


class TokenManager:
    @staticmethod
    def is_google(provider: str) -> bool:
        return provider in _GOOGLE_PROVIDERS

    @staticmethod
    def is_microsoft(provider: str) -> bool:
        return provider in _MICROSOFT_PROVIDERS

    @staticmethod
    def _needs_refresh(row: ConnectorConnection) -> bool:
        if not row.token_expires_at:
            return False
        expires_at = row.token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return datetime.now(UTC) + _REFRESH_SKEW >= expires_at

    @staticmethod
    async def get_valid_creds(db: AsyncSession, row: ConnectorConnection) -> tuple[str, dict, str]:
        """Return (access_token, creds_dict, provider), refreshing and persisting when required."""
        creds = ConnectorService.decrypt_credentials(row)
        provider = row.provider

        if TokenManager.is_google(provider):
            oauth_mod = google_oauth
            refresher_name = "google"
            google_cfg = await get_google_runtime_config(db)
        elif TokenManager.is_microsoft(provider):
            oauth_mod = microsoft_oauth
            refresher_name = "microsoft"
            ms_cfg = await get_microsoft_runtime_config(db)
        else:
            token = str(creds.get("access_token") or creds.get("token") or "")
            return token, creds, provider

        access_token = str(creds.get("access_token") or "")
        refresh_token = str(creds.get("refresh_token") or "")

        if access_token and not TokenManager._needs_refresh(row):
            return access_token, creds, provider

        if not refresh_token:
            raise ConnectorNeedsReauth(
                row.id, provider, f"No refresh_token stored. Reconnect {refresher_name} from Settings."
            )

        try:
            if TokenManager.is_google(provider):
                refreshed = await google_oauth.refresh_access_token(
                    refresh_token, connection_id=row.id, config=google_cfg
                )
            else:
                refreshed = await microsoft_oauth.refresh_access_token(
                    refresh_token, connection_id=row.id, config=ms_cfg
                )
        except ConnectorNeedsReauth:
            row.meta = {**(row.meta or {}), "status": "needs_reauth"}
            await db.commit()
            raise

        new_access = str(refreshed["access_token"])
        creds["access_token"] = new_access
        if refreshed.get("refresh_token"):
            creds["refresh_token"] = str(refreshed["refresh_token"])
        row.credentials_encrypted = ConnectorService.encrypt_credentials(creds)
        row.token_expires_at = oauth_mod.compute_expires_at(refreshed)
        scopes_str = refreshed.get("scope")
        if isinstance(scopes_str, str) and scopes_str.strip():
            row.oauth_scopes = scopes_str.split()
        row.meta = {**(row.meta or {}), "status": "active", "last_refresh_at": datetime.now(UTC).isoformat()}
        await db.commit()
        await db.refresh(row)
        return new_access, creds, provider

    @staticmethod
    async def get_valid_access_token(db: AsyncSession, row: ConnectorConnection) -> str:
        token, _creds, _provider = await TokenManager.get_valid_creds(db, row)
        if not token:
            raise OAuthError(f"No access token available for connection #{row.id} ({row.provider})")
        return token
