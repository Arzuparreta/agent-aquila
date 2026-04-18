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
        return ConnectorConnectionRead(
            id=row.id,
            provider=row.provider,
            label=row.label,
            meta=row.meta,
            token_expires_at=row.token_expires_at,
            oauth_scopes=scopes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
