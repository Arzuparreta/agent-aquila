"""Artist-uploaded files (Archivos).

Storage:
- Files land under ``settings.upload_dir`` in a per-user subfolder, named with a UUID +
  the original sanitized filename (so duplicates don't clobber).
- We extract text best-effort (.txt / .md / .csv directly; .pdf if pypdf is installed) and
  push it through ``RagIndexService.index_text(entity_type="attachment", entity_id=...)``
  so the agent can RAG over uploads alongside CRM data.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.attachment import Attachment
from app.models.user import User

logger = logging.getLogger(__name__)

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "file").strip() or "file"
    return _FILENAME_SAFE.sub("_", base)[:200]


def _user_dir(user_id: int) -> str:
    root = os.path.abspath(os.path.expanduser(settings.upload_dir or "./uploads"))
    sub = os.path.join(root, f"user_{user_id}")
    os.makedirs(sub, exist_ok=True)
    return sub


def _maybe_extract_text(path: str, mime: str) -> Optional[str]:
    """Best-effort text extraction. Returns ``None`` on failure or unsupported type."""
    try:
        if mime.startswith("text/") or mime in {
            "application/json",
            "application/xml",
            "application/csv",
        }:
            with open(path, "rb") as fh:
                raw = fh.read(1_000_000)
            return raw.decode("utf-8", errors="ignore")
        if mime == "application/pdf":
            try:
                from pypdf import PdfReader  # type: ignore[import-not-found]
            except Exception:
                return None
            reader = PdfReader(path)
            parts: list[str] = []
            for page in reader.pages[:200]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001
                    continue
            return "\n\n".join(p for p in parts if p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("text extraction failed for %s (%s): %s", path, mime, exc)
    return None


async def store_upload(
    db: AsyncSession,
    user: User,
    *,
    filename: str,
    mime_type: str,
    data: bytes,
    thread_id: int | None = None,
) -> Attachment:
    """Persist bytes to disk + DB row, then trigger best-effort text extraction + RAG indexing."""
    dest_dir = _user_dir(user.id)
    safe_name = _sanitize_filename(filename)
    storage_name = f"{uuid.uuid4().hex}_{safe_name}"
    storage_uri = os.path.join(dest_dir, storage_name)
    with open(storage_uri, "wb") as fh:
        fh.write(data)

    text = _maybe_extract_text(storage_uri, mime_type or "application/octet-stream")

    row = Attachment(
        user_id=user.id,
        thread_id=thread_id,
        filename=safe_name,
        mime_type=mime_type or "application/octet-stream",
        size_bytes=len(data),
        storage_uri=storage_uri,
        extracted_text=text,
        embedded=False,
    )
    db.add(row)
    await db.flush()

    if text:
        try:
            from app.services.rag_index_service import RagIndexService

            await RagIndexService.index_text(
                db,
                user_id=user.id,
                entity_type="attachment",
                entity_id=row.id,
                title=safe_name,
                text=text,
            )
            row.embedded = True
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG indexing failed for attachment %s: %s", row.id, exc)
    return row


async def list_attachments(db: AsyncSession, user: User) -> list[Attachment]:
    r = await db.execute(
        select(Attachment).where(Attachment.user_id == user.id).order_by(Attachment.id.desc())
    )
    return list(r.scalars().all())


async def get_attachment(db: AsyncSession, user: User, attachment_id: int) -> Attachment | None:
    row = await db.get(Attachment, attachment_id)
    if not row or row.user_id != user.id:
        return None
    return row
