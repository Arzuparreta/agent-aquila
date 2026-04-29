"""Drive tool handlers."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.drive_client import GoogleDriveClient
from app.services.connectors.file_adapters import upload_file
from app.services.oauth import TokenManager

from .base import provider_connection


@provider_connection("drive")
async def _tool_drive_list_files(
    db: AsyncSession, user: User, client: GoogleDriveClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_files(
        page_token=args.get("page_token"),
        q=args.get("q"),
        page_size=int(args.get("page_size") or 50),
    )


@provider_connection("drive", pass_row=True)
async def _tool_drive_upload_file(
    db: AsyncSession, user: User, client: GoogleDriveClient, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)
    path = str(args.get("path") or "").strip()
    mime = str(args.get("mime_type") or "application/octet-stream")
    if args.get("content_base64"):
        try:
            body = base64.b64decode(str(args["content_base64"]))
        except Exception as exc: # noqa: BLE001
            return {"error": f"invalid base64: {exc}"}
    elif args.get("content_text") is not None:
        body = str(args["content_text"]).encode("utf-8")
    else:
        return {"error": "either content_text or content_base64 is required"}
    return await upload_file(provider, creds, path, body, mime)
