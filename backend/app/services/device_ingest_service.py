"""Store and list files ingested from the iOS/Shortcuts device bridge."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_device_file_ingest import UserDeviceFileIngest

MAX_INGEST_BYTES = 4 * 1024 * 1024
_MAX_AGENT_BASE64 = 1 * 1024 * 1024


class DeviceIngestService:
    @staticmethod
    async def ingest(
        db: AsyncSession,
        user: User,
        *,
        path_hint: str | None,
        filename: str,
        mime_type: str | None,
        body: bytes,
    ) -> dict[str, Any]:
        if len(body) > MAX_INGEST_BYTES:
            return {"error": f"file exceeds {MAX_INGEST_BYTES} bytes (device bridge limit)"}
        if not filename.strip():
            return {"error": "filename is required"}
        row = UserDeviceFileIngest(
            user_id=user.id,
            path_hint=(path_hint or "")[:1024] or None,
            filename=filename[:512],
            mime_type=(mime_type or None),
            size_bytes=len(body),
            sha256_hex=UserDeviceFileIngest.compute_sha256(body),
            body=body,
        )
        db.add(row)
        await db.flush()
        return {
            "id": row.id,
            "filename": row.filename,
            "path_hint": row.path_hint,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "sha256_hex": row.sha256_hex,
        }

    @staticmethod
    async def list_recent(db: AsyncSession, user: User, *, limit: int = 50) -> list[dict[str, Any]]:
        lim = min(max(1, limit), 200)
        stmt = (
            select(UserDeviceFileIngest)
            .where(UserDeviceFileIngest.user_id == user.id)
            .order_by(UserDeviceFileIngest.created_at.desc())
            .limit(lim)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "filename": r.filename,
                    "path_hint": r.path_hint,
                    "mime_type": r.mime_type,
                    "size_bytes": r.size_bytes,
                    "sha256_hex": r.sha256_hex,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out

    @staticmethod
    async def get_for_agent(
        db: AsyncSession, user: User, ingest_id: int
    ) -> dict[str, Any]:
        row = await db.get(UserDeviceFileIngest, ingest_id)
        if not row or row.user_id != user.id:
            return {"error": "ingest not found"}
        if row.size_bytes > _MAX_AGENT_BASE64:
            return {
                "id": row.id,
                "filename": row.filename,
                "path_hint": row.path_hint,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "sha256_hex": row.sha256_hex,
                "note": f"file too large to inline (>{_MAX_AGENT_BASE64} bytes); download via the device API",
            }
        b64 = base64.b64encode(row.body).decode("ascii")
        return {
            "id": row.id,
            "filename": row.filename,
            "path_hint": row.path_hint,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "sha256_hex": row.sha256_hex,
            "content_base64": b64,
        }
