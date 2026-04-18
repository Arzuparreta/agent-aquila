"""Microsoft Graph initial + delta sync drivers for mail, calendar, and OneDrive.

All three resources share the same delta pagination shape — pages contain `@odata.nextLink`
until the final page, which contains `@odata.deltaLink`. We store the final `deltaLink` as
the cursor in `ConnectionSyncState.cursor`, then start from it on subsequent runs.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.graph_client import GraphAPIError, GraphClient
from app.services.graph_mirror_service import GraphMirrorService
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth
from app.services.sync_state_service import SyncStateService

logger = logging.getLogger(__name__)

RESOURCE_MAIL = "graph_mail"
RESOURCE_CALENDAR = "graph_calendar"
RESOURCE_DRIVE = "graph_drive"


async def _load(db: AsyncSession, connection_id: int, providers: set[str]) -> tuple[ConnectorConnection, User] | None:
    row = await db.get(ConnectorConnection, connection_id)
    if not row or row.provider not in providers:
        return None
    user = await db.get(User, row.user_id)
    if not user:
        return None
    return row, user


# --------------------------------------------------------------------- Mail
async def _run_mail(
    db: AsyncSession, connection_id: int, *, from_cursor: bool
) -> dict[str, Any]:
    loaded = await _load(db, connection_id, {"graph_mail"})
    if not loaded:
        return {"ok": False, "error": "connection not found or not graph_mail"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, RESOURCE_MAIL)
    await SyncStateService.mark_running(db, state)
    await db.commit()

    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}

    client = GraphClient(token)
    processed = 0
    delta_link: str | None = state.cursor if from_cursor and state.cursor else None

    try:
        next_url: str | None = None
        first = True
        final_delta_link: str | None = None
        while True:
            if first and delta_link:
                page = await client.messages_delta(delta_link=delta_link)
            elif first:
                page = await client.messages_delta()
            else:
                assert next_url is not None
                page = await client.messages_delta(delta_link=next_url)
            first = False
            for msg in page.get("value") or []:
                await GraphMirrorService.upsert_mail(db, user, connection, msg)
                processed += 1
            await db.commit()
            nl = page.get("@odata.nextLink")
            dl = page.get("@odata.deltaLink")
            if nl:
                next_url = nl
                continue
            if dl:
                final_delta_link = dl
            break

        if from_cursor and delta_link:
            await SyncStateService.mark_success_delta(db, state, cursor=final_delta_link or delta_link)
        else:
            await SyncStateService.mark_success_full(db, state, cursor=final_delta_link)
        await db.commit()
        return {"ok": True, "processed": processed}
    except GraphAPIError as exc:
        # 410 Gone → cursor expired; fall back to a full re-sync.
        if exc.status_code == 410 and from_cursor:
            logger.info("graph mail delta cursor stale for %s; re-running initial", connection_id)
            state.cursor = None
            await db.commit()
            return await _run_mail(db, connection_id, from_cursor=False)
        await SyncStateService.mark_failed(db, state, error=f"graph_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph mail sync crashed for %s", connection_id)
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_mail_initial(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_mail(db, connection_id, from_cursor=False)


async def run_mail_delta(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_mail(db, connection_id, from_cursor=True)


# --------------------------------------------------------------------- Calendar
async def _run_calendar(db: AsyncSession, connection_id: int, *, from_cursor: bool) -> dict[str, Any]:
    loaded = await _load(db, connection_id, {"graph_calendar"})
    if not loaded:
        return {"ok": False, "error": "connection not found or not graph_calendar"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, RESOURCE_CALENDAR)
    await SyncStateService.mark_running(db, state)
    await db.commit()

    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}

    client = GraphClient(token)
    processed = 0
    delta_link: str | None = state.cursor if from_cursor and state.cursor else None

    start = (datetime.now(UTC) - timedelta(days=180)).isoformat()
    end = (datetime.now(UTC) + timedelta(days=365)).isoformat()

    try:
        first = True
        next_url: str | None = None
        final_delta_link: str | None = None
        while True:
            if first and delta_link:
                page = await client.events_delta(delta_link=delta_link)
            elif first:
                page = await client.events_delta(start=start, end=end)
            else:
                assert next_url is not None
                page = await client.events_delta(delta_link=next_url)
            first = False
            for ev in page.get("value") or []:
                await GraphMirrorService.upsert_event(db, user, connection, ev)
                processed += 1
            await db.commit()
            nl = page.get("@odata.nextLink")
            dl = page.get("@odata.deltaLink")
            if nl:
                next_url = nl
                continue
            if dl:
                final_delta_link = dl
            break

        if from_cursor and delta_link:
            await SyncStateService.mark_success_delta(db, state, cursor=final_delta_link or delta_link)
        else:
            await SyncStateService.mark_success_full(db, state, cursor=final_delta_link)
        await db.commit()
        return {"ok": True, "processed": processed}
    except GraphAPIError as exc:
        if exc.status_code == 410 and from_cursor:
            state.cursor = None
            await db.commit()
            return await _run_calendar(db, connection_id, from_cursor=False)
        await SyncStateService.mark_failed(db, state, error=f"graph_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph calendar sync crashed for %s", connection_id)
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_calendar_initial(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_calendar(db, connection_id, from_cursor=False)


async def run_calendar_delta(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_calendar(db, connection_id, from_cursor=True)


# --------------------------------------------------------------------- OneDrive
async def _run_drive(db: AsyncSession, connection_id: int, *, from_cursor: bool) -> dict[str, Any]:
    loaded = await _load(db, connection_id, {"graph_onedrive"})
    if not loaded:
        return {"ok": False, "error": "connection not found or not graph_onedrive"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, RESOURCE_DRIVE)
    await SyncStateService.mark_running(db, state)
    await db.commit()

    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}

    client = GraphClient(token)
    processed = 0
    delta_link: str | None = state.cursor if from_cursor and state.cursor else None

    try:
        first = True
        next_url: str | None = None
        final_delta_link: str | None = None
        while True:
            if first and delta_link:
                page = await client.drive_delta(delta_link=delta_link)
            elif first:
                page = await client.drive_delta()
            else:
                assert next_url is not None
                page = await client.drive_delta(delta_link=next_url)
            first = False
            for it in page.get("value") or []:
                if it.get("folder"):
                    continue
                await GraphMirrorService.upsert_drive_item(db, user, connection, it)
                processed += 1
            await db.commit()
            nl = page.get("@odata.nextLink")
            dl = page.get("@odata.deltaLink")
            if nl:
                next_url = nl
                continue
            if dl:
                final_delta_link = dl
            break

        if from_cursor and delta_link:
            await SyncStateService.mark_success_delta(db, state, cursor=final_delta_link or delta_link)
        else:
            await SyncStateService.mark_success_full(db, state, cursor=final_delta_link)
        await db.commit()
        return {"ok": True, "processed": processed}
    except GraphAPIError as exc:
        if exc.status_code == 410 and from_cursor:
            state.cursor = None
            await db.commit()
            return await _run_drive(db, connection_id, from_cursor=False)
        await SyncStateService.mark_failed(db, state, error=f"graph_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph drive sync crashed for %s", connection_id)
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_drive_initial(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_drive(db, connection_id, from_cursor=False)


async def run_drive_delta(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    return await _run_drive(db, connection_id, from_cursor=True)


async def list_active_connections(db: AsyncSession, providers: set[str]) -> list[ConnectorConnection]:
    r = await db.execute(select(ConnectorConnection).where(ConnectorConnection.provider.in_(providers)))
    out: list[ConnectorConnection] = []
    for row in r.scalars().all():
        meta = row.meta or {}
        if str(meta.get("status") or "") == "needs_reauth":
            continue
        out.append(row)
    return out
