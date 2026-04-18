"""Initial + incremental Google Calendar sync."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.calendar_mirror_service import CalendarMirrorService
from app.services.connectors.gcal_client import CalendarAPIError, GoogleCalendarClient
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth
from app.services.sync_state_service import SyncStateService

logger = logging.getLogger(__name__)

CALENDAR_RESOURCE = "calendar"
DEFAULT_CAL_ID = "primary"


async def _load(db: AsyncSession, connection_id: int) -> tuple[ConnectorConnection, User] | None:
    row = await db.get(ConnectorConnection, connection_id)
    if not row or row.provider not in ("google_calendar", "gcal"):
        return None
    user = await db.get(User, row.user_id)
    if not user:
        return None
    return row, user


async def _drain_pages(
    client: GoogleCalendarClient,
    db: AsyncSession,
    user: User,
    connection: ConnectorConnection,
    *,
    sync_token: str | None = None,
) -> tuple[str | None, int]:
    """Return (new_sync_token, changes_applied)."""
    page_token: str | None = None
    changes = 0
    next_sync_token: str | None = None
    while True:
        page = await client.list_events(
            page_token=page_token, sync_token=sync_token, show_deleted=True
        )
        for item in page.get("items") or []:
            try:
                await CalendarMirrorService.upsert_event(db, user, connection, item)
                changes += 1
            except Exception:
                logger.exception("calendar upsert failed for item %s", item.get("id"))
        await db.commit()
        if page.get("nextPageToken"):
            page_token = str(page["nextPageToken"])
            continue
        next_sync_token = str(page.get("nextSyncToken") or "") or None
        break
    return next_sync_token, changes


async def run_initial_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not calendar"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, CALENDAR_RESOURCE)
    await SyncStateService.mark_running(db, state)
    await db.commit()
    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}
    client = GoogleCalendarClient(token)
    try:
        new_token, changes = await _drain_pages(client, db, user, connection)
        await SyncStateService.mark_success_full(db, state, cursor=new_token)
        await db.commit()
        return {"ok": True, "changes": changes, "sync_token": new_token}
    except CalendarAPIError as exc:
        await SyncStateService.mark_failed(db, state, error=f"calendar_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("calendar initial sync crashed")
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_delta_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not calendar"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, CALENDAR_RESOURCE)
    if not state.cursor:
        return await run_initial_sync(db, connection_id)
    await SyncStateService.mark_running(db, state)
    await db.commit()
    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}
    client = GoogleCalendarClient(token)
    try:
        new_token, changes = await _drain_pages(client, db, user, connection, sync_token=state.cursor)
        await SyncStateService.mark_success_delta(db, state, cursor=new_token or state.cursor)
        await db.commit()
        return {"ok": True, "changes": changes, "sync_token": new_token}
    except CalendarAPIError as exc:
        if exc.status_code == 410:
            state.cursor = None
            await db.commit()
            return await run_initial_sync(db, connection_id)
        await SyncStateService.mark_failed(db, state, error=f"calendar_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("calendar delta sync crashed")
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def list_active_calendar_connections(db: AsyncSession) -> list[ConnectorConnection]:
    r = await db.execute(
        select(ConnectorConnection).where(ConnectorConnection.provider.in_(["google_calendar", "gcal"]))
    )
    out: list[ConnectorConnection] = []
    for row in r.scalars().all():
        if str((row.meta or {}).get("status") or "") == "needs_reauth":
            continue
        out.append(row)
    return out
