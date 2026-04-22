"""Ingest files from the device bridge (e.g. iOS Shortcuts)."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.device_ingest_service import DeviceIngestService

router = APIRouter(prefix="/device-files", tags=["device-files"], dependencies=[Depends(get_current_user)])


class DeviceFileIngestBody(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    path_hint: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=128)
    content_base64: str = Field(min_length=1)


@router.post("/ingest", status_code=201)
async def ingest_device_file(
    body: DeviceFileIngestBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        raw = base64.b64decode(body.content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}") from exc
    res = await DeviceIngestService.ingest(
        db,
        user,
        path_hint=body.path_hint,
        filename=body.filename,
        mime_type=body.mime_type,
        body=raw,
    )
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    await db.commit()
    return res
