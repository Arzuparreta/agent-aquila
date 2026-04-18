"""Google Drive metadata mirror + on-demand text extraction.

Files are mirrored by metadata first. A separate job fetches the body when needed
(Google Docs → export `text/plain`; plain text / CSV → raw download). Binary files we skip.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.drive_file import DriveFile
from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.connectors.drive_client import DriveAPIError, GoogleDriveClient
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth
from app.services.rag_index_service import RagIndexService
from app.services.sync_state_service import SyncStateService
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

DRIVE_RESOURCE = "drive"
# MIME types we consider "text-exportable".
GOOGLE_DOC_EXPORTS: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
TEXT_MIMES_DIRECT: set[str] = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "text/html",
}
MAX_EXTRACT_BYTES = 2_000_000


async def _load(db: AsyncSession, connection_id: int) -> tuple[ConnectorConnection, User] | None:
    row = await db.get(ConnectorConnection, connection_id)
    if not row or row.provider not in ("google_drive", "gdrive"):
        return None
    user = await db.get(User, row.user_id)
    if not user:
        return None
    return row, user


def _parse_modified(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


async def _upsert_file(
    db: AsyncSession, connection: ConnectorConnection, file_obj: dict[str, Any]
) -> DriveFile | None:
    fid = str(file_obj.get("id") or "")
    if not fid:
        return None
    r = await db.execute(
        select(DriveFile).where(
            DriveFile.connection_id == connection.id, DriveFile.provider_file_id == fid
        )
    )
    existing = r.scalar_one_or_none()

    size_raw = file_obj.get("size")
    try:
        size_bytes = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_bytes = None

    parents = file_obj.get("parents") or None
    owners = file_obj.get("owners") or None
    trashed = bool(file_obj.get("trashed") or False)
    modified = _parse_modified(file_obj.get("modifiedTime"))

    if existing:
        existing.name = str(file_obj.get("name") or existing.name)[:512]
        existing.mime_type = file_obj.get("mimeType") or existing.mime_type
        existing.size_bytes = size_bytes
        existing.parents = list(parents) if parents else existing.parents
        existing.owners = list(owners) if owners else existing.owners
        existing.web_view_link = file_obj.get("webViewLink") or existing.web_view_link
        existing.modified_time = modified or existing.modified_time
        existing.is_trashed = trashed
        await db.flush()
        return existing

    row = DriveFile(
        connection_id=connection.id,
        provider="google_drive",
        provider_file_id=fid,
        name=str(file_obj.get("name") or "(unnamed)")[:512],
        mime_type=file_obj.get("mimeType"),
        size_bytes=size_bytes,
        parents=list(parents) if parents else None,
        owners=list(owners) if owners else None,
        web_view_link=file_obj.get("webViewLink"),
        modified_time=modified,
        is_trashed=trashed,
    )
    db.add(row)
    await db.flush()
    return row


async def _delete_file(
    db: AsyncSession, connection: ConnectorConnection, provider_file_id: str
) -> None:
    r = await db.execute(
        select(DriveFile).where(
            DriveFile.connection_id == connection.id, DriveFile.provider_file_id == provider_file_id
        )
    )
    row = r.scalar_one_or_none()
    if row:
        await RagIndexService.delete_entity_chunks(db, "drive_file", row.id)
        await db.delete(row)


async def run_initial_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not drive"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, DRIVE_RESOURCE)
    await SyncStateService.mark_running(db, state)
    await db.commit()
    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth as exc:
        await SyncStateService.mark_failed(db, state, error=f"needs_reauth: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": "needs_reauth"}
    client = GoogleDriveClient(token)
    try:
        # Capture a starting change token before we page through files, so later deltas don't miss
        # changes that happened during initial sync.
        start_token_resp = await client.get_start_page_token()
        start_token = str(start_token_resp.get("startPageToken") or "")

        page_token: str | None = None
        count = 0
        while True:
            listing = await client.list_files(page_token=page_token, page_size=200)
            for f in listing.get("files") or []:
                try:
                    await _upsert_file(db, connection, f)
                    count += 1
                except Exception:
                    logger.exception("drive upsert failed for %s", f.get("id"))
            await db.commit()
            page_token = listing.get("nextPageToken")
            if not page_token:
                break
        await SyncStateService.mark_success_full(db, state, cursor=start_token or None)
        await db.commit()
        return {"ok": True, "files": count, "start_token": start_token}
    except DriveAPIError as exc:
        await SyncStateService.mark_failed(db, state, error=f"drive_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("drive initial sync crashed")
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_delta_sync(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    loaded = await _load(db, connection_id)
    if not loaded:
        return {"ok": False, "error": "connection not found or not drive"}
    connection, user = loaded
    state = await SyncStateService.get_or_create(db, connection.id, DRIVE_RESOURCE)
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
    client = GoogleDriveClient(token)
    try:
        page_token = state.cursor
        applied = 0
        while True:
            page = await client.list_changes(page_token=page_token)
            for change in page.get("changes") or []:
                if change.get("removed") or (change.get("file") or {}).get("trashed"):
                    fid = str(change.get("fileId") or (change.get("file") or {}).get("id") or "")
                    if fid:
                        await _delete_file(db, connection, fid)
                        applied += 1
                elif change.get("file"):
                    await _upsert_file(db, connection, change["file"])
                    applied += 1
            await db.commit()
            if page.get("nextPageToken"):
                page_token = str(page["nextPageToken"])
                continue
            new_start = str(page.get("newStartPageToken") or page_token)
            await SyncStateService.mark_success_delta(db, state, cursor=new_start)
            await db.commit()
            return {"ok": True, "applied": applied, "cursor": new_start}
    except DriveAPIError as exc:
        if exc.status_code in (404, 410):
            state.cursor = None
            await db.commit()
            return await run_initial_sync(db, connection_id)
        await SyncStateService.mark_failed(db, state, error=f"drive_api_{exc.status_code}: {exc.detail}")
        await db.commit()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("drive delta sync crashed")
        await SyncStateService.mark_failed(db, state, error=repr(exc))
        await db.commit()
        return {"ok": False, "error": repr(exc)}


async def run_extract_text(db: AsyncSession, file_row_id: int) -> dict[str, Any]:
    row = await db.get(DriveFile, file_row_id)
    if not row:
        return {"ok": False, "error": "file not found"}
    connection = await db.get(ConnectorConnection, row.connection_id)
    if not connection:
        return {"ok": False, "error": "connection not found"}
    user = await db.get(User, connection.user_id)
    if not user:
        return {"ok": False, "error": "user not found"}
    try:
        token = await TokenManager.get_valid_access_token(db, connection)
    except ConnectorNeedsReauth:
        return {"ok": False, "error": "needs_reauth"}
    client = GoogleDriveClient(token)
    mime = str(row.mime_type or "").lower()

    body: bytes = b""
    try:
        if mime in GOOGLE_DOC_EXPORTS:
            body = await client.export(row.provider_file_id, GOOGLE_DOC_EXPORTS[mime])
        elif mime in TEXT_MIMES_DIRECT:
            body = await client.download(row.provider_file_id)
        else:
            return {"ok": False, "error": f"extraction not supported for mime {mime}"}
    except DriveAPIError as exc:
        return {"ok": False, "error": f"drive_api_{exc.status_code}"}

    if len(body) > MAX_EXTRACT_BYTES:
        body = body[:MAX_EXTRACT_BYTES]
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        text = ""

    row.content_text = text
    row.content_text_updated_at = datetime.now(UTC)
    await db.flush()

    # RAG indexing: reuse existing chunker via RagIndexService with a new entity_type "drive_file".
    try:
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if not settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "drive_file", row.id)
            await RagIndexService.index_text(
                db,
                user_id=user.id,
                entity_type="drive_file",
                entity_id=row.id,
                title=row.name,
                text=text,
            )
            row.embedding_model = settings_row.embedding_model
            row.embedding_updated_at = datetime.now(UTC)
    except Exception:
        logger.exception("RAG index failed for drive file %s", row.id)

    await create_audit_log(
        db, "drive_file", row.id, "text_extracted", {"bytes": len(body), "mime": mime}, user.id
    )
    await db.commit()
    return {"ok": True, "bytes": len(body), "mime": mime}


async def list_active_drive_connections(db: AsyncSession) -> list[ConnectorConnection]:
    r = await db.execute(
        select(ConnectorConnection).where(ConnectorConnection.provider.in_(["google_drive", "gdrive"]))
    )
    out: list[ConnectorConnection] = []
    for row in r.scalars().all():
        if str((row.meta or {}).get("status") or "") == "needs_reauth":
            continue
        out.append(row)
    return out
