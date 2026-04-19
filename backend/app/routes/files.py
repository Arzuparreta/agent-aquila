"""Archivos endpoints: artist-uploaded files attached to chat / RAG.

Endpoints:
- ``POST /files`` (multipart) — upload a file. Optional form field ``thread_id`` binds it to a chat thread.
- ``GET  /files`` — list the artist's uploaded attachments (newest first).
- ``GET  /files/{id}`` — read one attachment's metadata.
- ``GET  /files/{id}/download`` — stream the file back (for previews / re-downloads).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.chat import StartChatResponse
from app.schemas.file import AttachmentRead
from app.services.attachment_service import get_attachment, list_attachments, store_upload
from app.services.chat_service import start_entity_chat

router = APIRouter(prefix="/files", tags=["files"])


def _to_read(row) -> AttachmentRead:
    return AttachmentRead(
        id=row.id,
        filename=row.filename,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        thread_id=row.thread_id,
        created_at=row.created_at,
        embedded=row.embedded,
        has_text=bool(row.extracted_text),
    )


@router.get("", response_model=list[AttachmentRead])
async def get_files(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AttachmentRead]:
    rows = await list_attachments(db, current_user)
    return [_to_read(r) for r in rows]


@router.post("", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    thread_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttachmentRead:
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large; max {settings.max_upload_bytes} bytes",
        )
    row = await store_upload(
        db,
        current_user,
        filename=file.filename or "file",
        mime_type=file.content_type or "application/octet-stream",
        data=data,
        thread_id=thread_id,
    )
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.get("/{attachment_id}", response_model=AttachmentRead)
async def read_file_meta(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttachmentRead:
    row = await get_attachment(db, current_user, attachment_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return _to_read(row)


@router.post("/{attachment_id}/start-chat", response_model=StartChatResponse)
async def start_chat_from_file(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartChatResponse:
    """Create (or reuse) an entity-bound chat thread for this file and seed it with
    a single ``event`` announcement. Mirrors ``POST /emails/{id}/start-chat``. Uses
    ``entity_type='attachment'`` to match the library drawer's tab mapping.
    """
    row = await get_attachment(db, current_user, attachment_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    title = f"Archivo · {row.filename}"[:255]
    size_kb = (row.size_bytes or 0) / 1024
    detail_bits = [
        f"Tipo: {row.mime_type}" if row.mime_type else None,
        f"Tamaño: {size_kb:.1f} KB",
    ]
    details = " · ".join(b for b in detail_bits if b)
    preview = (row.extracted_text or "")[:600]
    announcement = (
        f"📎 Archivo referenciado\n"
        f"Nombre: {row.filename}\n"
        f"{details}\n\n"
        f"{preview}"
    )
    thread = await start_entity_chat(
        db,
        current_user,
        entity_type="attachment",
        entity_id=row.id,
        title=title,
        announcement=announcement,
        event_attachments=[{"event_kind": "file_referenced", "attachment_id": row.id}],
    )
    await db.commit()
    return StartChatResponse(thread_id=thread.id)


@router.get("/{attachment_id}/download")
async def download_file(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    row = await get_attachment(db, current_user, attachment_id)
    if not row or not os.path.exists(row.storage_uri):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return FileResponse(
        row.storage_uri,
        media_type=row.mime_type or "application/octet-stream",
        filename=row.filename,
    )
