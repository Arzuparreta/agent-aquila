"""Tiny helper around `ConnectionSyncState` rows."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection_sync_state import ConnectionSyncState


class SyncStateService:
    @staticmethod
    async def get_or_create(
        db: AsyncSession, connection_id: int, resource: str
    ) -> ConnectionSyncState:
        r = await db.execute(
            select(ConnectionSyncState).where(
                ConnectionSyncState.connection_id == connection_id,
                ConnectionSyncState.resource == resource,
            )
        )
        row = r.scalar_one_or_none()
        if row:
            return row
        row = ConnectionSyncState(connection_id=connection_id, resource=resource, status="idle")
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_for_connection(
        db: AsyncSession, connection_id: int
    ) -> list[ConnectionSyncState]:
        r = await db.execute(
            select(ConnectionSyncState).where(ConnectionSyncState.connection_id == connection_id)
        )
        return list(r.scalars().all())

    @staticmethod
    async def list_by_resource(db: AsyncSession, resource: str) -> list[ConnectionSyncState]:
        r = await db.execute(
            select(ConnectionSyncState).where(ConnectionSyncState.resource == resource)
        )
        return list(r.scalars().all())

    @staticmethod
    async def mark_running(db: AsyncSession, row: ConnectionSyncState) -> None:
        row.status = "running"
        row.last_error = None
        await db.flush()

    @staticmethod
    async def mark_success_full(db: AsyncSession, row: ConnectionSyncState, *, cursor: str | None) -> None:
        row.status = "idle"
        row.error_count = 0
        row.last_error = None
        row.cursor = cursor
        row.last_full_sync_at = datetime.now(UTC)
        row.last_delta_at = datetime.now(UTC)
        await db.flush()

    @staticmethod
    async def mark_success_delta(db: AsyncSession, row: ConnectionSyncState, *, cursor: str | None) -> None:
        row.status = "idle"
        row.error_count = 0
        row.last_error = None
        row.cursor = cursor
        row.last_delta_at = datetime.now(UTC)
        await db.flush()

    @staticmethod
    async def mark_failed(db: AsyncSession, row: ConnectionSyncState, *, error: str) -> None:
        row.status = "error"
        row.error_count = (row.error_count or 0) + 1
        row.last_error = error[:2000]
        await db.flush()
