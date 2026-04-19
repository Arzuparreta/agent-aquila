"""Dry-run validator for outbound email proposals.

After the OpenClaw refactor only outbound email is proposal-gated, so
the dry-run service exposes a single ``email_send`` action used by the
chat UI to preflight an approval card without actually sending.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.services.connectors.email_adapters import send_email as email_send

ACTION_TO_KIND: dict[str, str] = {
    "email_send": "email_send",
    "email_reply": "email_reply",
}


class ConnectorDryRunService:
    @staticmethod
    async def run(
        provider: str,
        creds: dict[str, Any],
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action not in ACTION_TO_KIND:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown action: {action}",
            )
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
            thread_id=str(payload.get("thread_id")) if payload.get("thread_id") else None,
            in_reply_to=str(payload.get("in_reply_to")) if payload.get("in_reply_to") else None,
            references=str(payload.get("references")) if payload.get("references") else None,
        )
