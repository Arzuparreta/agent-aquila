"""Initial and incremental Gmail sync drivers.

- `run_initial_sync(connection_id)` — paginate messages.list newest-first, fetch each full message,
  upsert into the mirror, stop when cap reached. Saves the current historyId when done.
- `run_delta_sync(connection_id)` — apply Gmail `history.list` deltas from the saved cursor forward.
  Re-runs a full sync when the cursor is too old (404 from Gmail).

Both functions are safe to call outside the worker (e.g. from a manual /sync endpoint).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.gmail_client import GmailAPIError, GmailClient
from app.services.gmail_mirror_service import GmailMirrorService
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth
from app.services.sync_state_service import SyncStateService

logger = logging.getLogger(__name__)

GMAIL_RESOURCE = "gmail"


async def _load_connection(db: AsyncSession, connection_id: int) -> tuple[ConnectorConnection, User] | None:
    row = await db.get(ConnectorConnection, connection_id)
    if not row or row.provider not in ("google_gmail", "gmail"):
        return None
    user = await db.get(User, row.user_id)
    if not user:
        return None
    return row, user


async def run_initial_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load_connection(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not gmail"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, GMAIL_RESOURCE)
    await SyncStateService.mark_running(db, state)
    await db.commit()

    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}

    client = GmailClient(token)
    try:
        profile = await client.get_profile()
        history_id = str(profile.get("historyId") or "")
        cap = app_settings.gmail_initial_sync_max_messages or 0
        ingested = 0
        page_token: str | None = None
        while True:
            listing = await client.list_messages(
                page_token=page_token, max_results=100, label_ids=None
            )
            message_refs = listing.get("messages") or []
            if not message_refs:
                break
            for ref in message_refs:
                if cap and ingested >= cap:
                    break
                try:
                    full = await client.get_message(str(ref["id"]), format="full")
                    await GmailMirrorService.upsert_message(db, user, connection, full)
                    await db.commit()
                    ingested += 1
                except GmailAPIError as exc:
                    logger.warning("gmail get_message failed %s: %s", ref.get("id"), exc)
                    await db.rollback()
            if cap and ingested >= cap:
                break
            page_token = listing.get("nextPageToken")
            if not page_token:
                break

        await SyncStateService.mark_success_full(db, state, cursor=history_id or None)
        await db.commit()
        return {"ok": True, "ingested": ingested, "history_id": history_id}
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}
    except GmailAPIError as exc:
        await SyncStateService.mark_failed(db, state, error=f"gmail_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("gmail initial sync crashed for connection %s", connection_id)
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_delta_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load_connection(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not gmail"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, GMAIL_RESOURCE)
    if not state.cursor:
        # First pass: do a full sync instead.
        return await run_initial_sync(db, connection_id)

    await SyncStateService.mark_running(db, state)
    await db.commit()

    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}

    client = GmailClient(token)
    changes_applied = 0
    latest_history_id = state.cursor
    try:
        page_token: str | None = None
        while True:
            page = await client.list_history(
                start_history_id=str(state.cursor),
                page_token=page_token,
                history_types=["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
            )
            latest_history_id = str(page.get("historyId") or latest_history_id)
            for entry in page.get("history") or []:
                # Additions
                for add in entry.get("messagesAdded") or []:
                    msg_ref = add.get("message") or {}
                    msg_id = str(msg_ref.get("id") or "")
                    if not msg_id:
                        continue
                    try:
                        full = await client.get_message(msg_id, format="full")
                        await GmailMirrorService.upsert_message(db, user, connection, full)
                        changes_applied += 1
                    except GmailAPIError as exc:
                        logger.warning("gmail add fetch failed %s: %s", msg_id, exc)
                # Deletions
                for rem in entry.get("messagesDeleted") or []:
                    msg_ref = rem.get("message") or {}
                    msg_id = str(msg_ref.get("id") or "")
                    if msg_id:
                        await GmailMirrorService.delete_message(db, connection, msg_id)
                        changes_applied += 1
                # Label changes — refetch full message to apply new labels/state.
                for la in (entry.get("labelsAdded") or []) + (entry.get("labelsRemoved") or []):
                    msg_ref = la.get("message") or {}
                    msg_id = str(msg_ref.get("id") or "")
                    if not msg_id:
                        continue
                    try:
                        full = await client.get_message(msg_id, format="full")
                        await GmailMirrorService.upsert_message(db, user, connection, full, run_triage=False)
                        changes_applied += 1
                    except GmailAPIError as exc:
                        logger.warning("gmail label refetch failed %s: %s", msg_id, exc)
                await db.commit()
            page_token = page.get("nextPageToken")
            if not page_token:
                break

        await SyncStateService.mark_success_delta(db, state, cursor=latest_history_id)
        await db.commit()
        return {"ok": True, "changes": changes_applied, "history_id": latest_history_id}
    except GmailAPIError as exc:
        if exc.status_code == 404:
            # Cursor too old — fall back to full sync.
            logger.info("gmail history cursor stale for connection %s; running initial sync", connection_id)
            state.cursor = None
            await db.commit()
            return await run_initial_sync(db, connection_id)
        await SyncStateService.mark_failed(db, state, error=f"gmail_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("gmail delta sync crashed for connection %s", connection_id)
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def list_active_gmail_connections(db: AsyncSession) -> list[ConnectorConnection]:
    r = await db.execute(
        select(ConnectorConnection).where(ConnectorConnection.provider.in_(["google_gmail", "gmail"]))
    )
    out: list[ConnectorConnection] = []
    for row in r.scalars().all():
        meta = row.meta or {}
        if str(meta.get("status") or "") == "needs_reauth":
            continue
        out.append(row)
    return out
