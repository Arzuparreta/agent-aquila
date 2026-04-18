from __future__ import annotations

import base64
from typing import Any

from fastapi import HTTPException, status

from app.services.connectors.calendar_adapters import create_calendar_event as cal_create
from app.services.connectors.email_adapters import send_email as email_send
from app.services.connectors.file_adapters import upload_file as file_upload
from app.services.connectors.teams_adapter import post_channel_message as teams_post

ACTION_TO_KIND: dict[str, str] = {
    "email_send": "connector_email_send",
    "calendar_create": "connector_calendar_create",
    "file_upload": "connector_file_upload",
    "teams_message": "connector_teams_message",
}


class ConnectorDryRunService:
    """Validates connector credentials and payloads without performing external writes."""

    @staticmethod
    async def run(provider: str, creds: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "email_send":
            to_raw = payload.get("to")
            to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)] if to_raw else []
            to_list = [str(x) for x in to_list]
            return await email_send(
                provider,
                creds,
                to_list,
                str(payload.get("subject") or ""),
                str(payload.get("body") or ""),
                content_type=str(payload.get("content_type") or "text"),
                dry_run=True,
            )
        if action == "calendar_create":
            return await cal_create(provider, creds, payload, dry_run=True)
        if action == "file_upload":
            path = str(payload.get("path") or "")
            mime = str(payload.get("mime_type") or "application/octet-stream")
            if payload.get("content_base64"):
                raw = base64.b64decode(str(payload["content_base64"]))
            elif payload.get("content_text") is not None:
                raw = str(payload["content_text"]).encode("utf-8")
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="file_upload dry-run needs content_text or content_base64",
                )
            return await file_upload(provider, creds, path, raw, mime, dry_run=True)
        if action == "teams_message":
            return await teams_post(
                provider,
                creds,
                str(payload.get("team_id") or ""),
                str(payload.get("channel_id") or ""),
                str(payload.get("body") or ""),
                dry_run=True,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {action}",
        )
