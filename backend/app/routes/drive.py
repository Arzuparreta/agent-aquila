"""Live Google Drive proxy.

Lists & downloads through ``GoogleDriveClient``; uploads/share through
``file_adapters`` so writes share the same code as agent tools.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.drive_client import DriveAPIError, GoogleDriveClient
from app.services.connectors.file_adapters import share_file, upload_file
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

router = APIRouter(prefix="/drive", tags=["drive"], dependencies=[Depends(get_current_user)])

DRIVE_PROVIDERS = ("google_drive", "gdrive")


async def _resolve(db: AsyncSession, user: User, connection_id: int | None) -> ConnectorConnection:
    if connection_id is not None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.provider not in DRIVE_PROVIDERS:
            raise HTTPException(status_code=400, detail="Not a Google Drive connection.")
        return row
    stmt = select(ConnectorConnection).where(
        ConnectorConnection.user_id == user.id,
        ConnectorConnection.provider.in_(DRIVE_PROVIDERS),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(status_code=400, detail="No Google Drive connection.")
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Multiple connections — pass ?connection_id=... ({', '.join(str(r.id) for r in rows)})",
        )
    return rows[0]


async def _creds(db: AsyncSession, row: ConnectorConnection):
    try:
        return await TokenManager.get_valid_creds(db, row)
    except ConnectorNeedsReauth as exc:
        raise HTTPException(
            status_code=401,
            detail={"kind": "needs_reauth", "message": str(exc), "connection_id": row.id},
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/files")
async def list_files(
    connection_id: int | None = Query(default=None),
    q: str | None = Query(default=None, description="Drive search query"),
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token, _creds_dict, _provider = await _creds(db, row)
    client = GoogleDriveClient(token)
    try:
        return await client.list_files(page_token=page_token, q=q, page_size=page_size)
    except DriveAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail[:500])


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    row = await _resolve(db, current_user, connection_id)
    token, _creds_dict, _provider = await _creds(db, row)
    client = GoogleDriveClient(token)
    try:
        data = await client.download(file_id)
    except DriveAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail[:500])
    return Response(content=data, media_type="application/octet-stream")


@router.post("/files")
async def upload(
    upload: UploadFile,
    path: str = Query(..., description="Logical filename, e.g. 'reports/foo.pdf'"),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    body = await upload.read()
    return await upload_file(provider, creds, path, body, upload.content_type or "application/octet-stream")


@router.post("/files/{file_id}/share")
async def share(
    file_id: str,
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    email = str(payload.get("email") or "").strip()
    role = str(payload.get("role") or "reader")
    if not email:
        raise HTTPException(status_code=400, detail="payload.email is required")
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    return await share_file(provider, creds, file_id, email, role)
