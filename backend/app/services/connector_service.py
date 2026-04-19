from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.schemas.connector import ConnectorConnectionCreate, ConnectorConnectionPatch, ConnectorConnectionRead
from app.services.oauth.google_oauth import GMAIL_REQUIRED_SCOPES


# Per-provider required-scope sets. When ``oauth_scopes`` on the connection
# row no longer cover this set, the connection is flagged ``needs_reauth``
# and the frontend nags the user to reconnect. We deliberately only check
# Gmail today — Calendar/Drive haven't grown new scopes — but the table
# format makes it trivial to extend later.
_REQUIRED_SCOPES_BY_PROVIDER: dict[str, frozenset[str]] = {
    "google_gmail": GMAIL_REQUIRED_SCOPES,
    "gmail": GMAIL_REQUIRED_SCOPES,
}


# Single source of truth: provider id -> (resource, initial-sync job name).
# Both the OAuth callback and the manual "submit credentials" path use this
# so that EVERY new connection automatically kicks off its initial sync —
# the artist should never need to wait for the next 5-minute cron tick to
# see their data appear, and we should never have a connection sitting in
# the DB without a corresponding sync job.
_INITIAL_SYNC_BY_PROVIDER: dict[str, tuple[str, str]] = {
    "google_gmail": ("gmail", "gmail_initial_sync"),
    "google_calendar": ("calendar", "calendar_initial_sync"),
    "google_drive": ("drive", "drive_initial_sync"),
    "graph_mail": ("graph_mail", "graph_mail_initial_sync"),
    "graph_calendar": ("graph_calendar", "graph_calendar_initial_sync"),
    "graph_onedrive": ("graph_drive", "graph_drive_initial_sync"),
}


async def enqueue_initial_sync_for_connection(connection: ConnectorConnection) -> bool:
    """Best-effort: enqueue the initial sync for a freshly-created connection.

    Returns ``True`` if a job was enqueued (or attempted), ``False`` if the
    provider has no associated sync (e.g. ``microsoft_teams``). Failures are
    swallowed and logged because a missing Redis or worker should never
    prevent the user from completing the connection setup itself.
    """
    mapping = _INITIAL_SYNC_BY_PROVIDER.get(connection.provider)
    if mapping is None:
        return False
    resource, job_name = mapping
    try:
        from app.services.job_queue import enqueue as enqueue_job

        await enqueue_job(
            job_name,
            connection.id,
            job_id=f"{resource}-initial-{connection.id}",
            allow_inline=False,
        )
        return True
    except Exception:  # pragma: no cover — best effort
        import logging

        logging.getLogger(__name__).warning(
            "failed to enqueue initial sync for connection %s/%s",
            connection.id,
            connection.provider,
            exc_info=True,
        )
        return False


class ConnectorService:
    @staticmethod
    def encrypt_credentials(data: dict[str, Any]) -> str:
        return encrypt_secret(json.dumps(data, ensure_ascii=False))

    @staticmethod
    def decrypt_credentials(row: ConnectorConnection) -> dict[str, Any]:
        raw = decrypt_secret(row.credentials_encrypted)
        if not raw:
            return {}
        return json.loads(raw)

    @staticmethod
    async def list_connections(db: AsyncSession, user: User) -> list[ConnectorConnection]:
        result = await db.execute(
            select(ConnectorConnection)
            .where(ConnectorConnection.user_id == user.id)
            .order_by(ConnectorConnection.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_connection(db: AsyncSession, user: User, payload: ConnectorConnectionCreate) -> ConnectorConnection:
        row = ConnectorConnection(
            user_id=user.id,
            provider=payload.provider,
            label=payload.label,
            credentials_encrypted=ConnectorService.encrypt_credentials(dict(payload.credentials)),
            meta=payload.meta,
            token_expires_at=payload.token_expires_at,
            oauth_scopes=list(payload.oauth_scopes) if payload.oauth_scopes is not None else None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        # Kick off an initial sync immediately so the artist sees their data
        # appear without waiting for the next cron tick. Best-effort: a
        # missing worker shouldn't fail the connection-create call.
        await enqueue_initial_sync_for_connection(row)
        return row

    @staticmethod
    async def delete_connection(db: AsyncSession, user: User, connection_id: int) -> None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        await db.delete(row)
        await db.commit()

    @staticmethod
    async def require_connection(db: AsyncSession, user: User, connection_id: int) -> ConnectorConnection:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        return row

    @staticmethod
    async def get_connection(db: AsyncSession, user: User, connection_id: int) -> ConnectorConnection | None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            return None
        return row

    @staticmethod
    async def patch_connection(
        db: AsyncSession, user: User, connection_id: int, payload: ConnectorConnectionPatch
    ) -> ConnectorConnection:
        row = await ConnectorService.require_connection(db, user, connection_id)
        if payload.label is not None:
            row.label = payload.label.strip()[:200]
        if payload.credentials_patch:
            creds = ConnectorService.decrypt_credentials(row)
            creds.update(dict(payload.credentials_patch))
            row.credentials_encrypted = ConnectorService.encrypt_credentials(creds)
        if payload.token_expires_at is not None:
            row.token_expires_at = payload.token_expires_at
        if payload.oauth_scopes is not None:
            row.oauth_scopes = list(payload.oauth_scopes)
        if payload.meta is not None:
            row.meta = payload.meta
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    def to_read(row: ConnectorConnection) -> ConnectorConnectionRead:
        scopes = row.oauth_scopes
        if scopes is not None and not isinstance(scopes, list):
            scopes = None
        # Compute reauth status: any required scope missing from the granted
        # set means the user has to walk through OAuth again. We treat
        # missing/null scope arrays as "needs reauth" only when the provider
        # actually has a required-scope set registered, so pure email/IMAP
        # connections (no oauth_scopes) aren't falsely flagged.
        required = _REQUIRED_SCOPES_BY_PROVIDER.get(row.provider)
        needs_reauth = False
        missing: list[str] | None = None
        if required is not None:
            granted = set(scopes or [])
            missing_set = required - granted
            if missing_set:
                needs_reauth = True
                missing = sorted(missing_set)
        return ConnectorConnectionRead(
            id=row.id,
            provider=row.provider,
            label=row.label,
            meta=row.meta,
            token_expires_at=row.token_expires_at,
            oauth_scopes=scopes,
            needs_reauth=needs_reauth,
            missing_scopes=missing,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
