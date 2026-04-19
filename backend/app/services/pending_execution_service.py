"""Apply approved proposals.

After the OpenClaw refactor only outbound email is gated, so this
module exclusively handles ``email_send`` and ``email_reply``. Both
funnel through ``email_adapters.send_email`` (which speaks Gmail or
Graph depending on the connection provider).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.connector_service import ConnectorService
from app.services.connectors.email_adapters import send_email as email_send
from app.services.oauth import TokenManager


class PendingExecutionService:
    """Applies an approved pending proposal to the live email provider."""

    @staticmethod
    async def execute(
        db: AsyncSession,
        user: User,
        kind: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        del commit  # always commits via the adapter
        if kind in ("email_send", "email_reply"):
            await PendingExecutionService._exec_email(db, user, payload, kind=kind)
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown proposal kind: {kind}",
        )

    @staticmethod
    async def _exec_email(
        db: AsyncSession, user: User, payload: dict[str, Any], *, kind: str
    ) -> None:
        conn_id = int(payload["connection_id"])
        to_list = payload["to"]
        if not isinstance(to_list, list):
            to_list = [str(to_list)]
        to_list = [str(x) for x in to_list]
        subject = str(payload.get("subject") or "")
        body = str(payload["body"])
        content_type = str(payload.get("content_type") or "text")
        thread_id = payload.get("thread_id")
        in_reply_to = payload.get("in_reply_to")
        references = payload.get("references")

        row = await ConnectorService.require_connection(db, user, conn_id)
        _, creds, provider = await TokenManager.get_valid_creds(db, row)
        result = await email_send(
            provider,
            creds,
            to_list,
            subject,
            body,
            content_type=content_type,
            dry_run=False,
            thread_id=str(thread_id) if thread_id else None,
            in_reply_to=str(in_reply_to) if in_reply_to else None,
            references=str(references) if references else None,
        )
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            kind,
            {"provider": provider, "to": to_list, "subject": subject, "result": result},
            user.id,
        )


# ---------------------------------------------------------------------------
# Lightweight previews used by the chat UI to render the approval card.
# ---------------------------------------------------------------------------


def build_email_preview(payload: dict[str, Any]) -> dict[str, Any]:
    to_list = payload.get("to")
    if not isinstance(to_list, list):
        to_list = [to_list] if to_list else []
    return {
        "action": "email_send",
        "to": [str(x) for x in to_list],
        "subject": str(payload.get("subject") or ""),
        "body_preview": (str(payload.get("body") or ""))[:2000],
        "content_type": str(payload.get("content_type") or "text"),
        "thread_id": payload.get("thread_id"),
    }


def preview_for_proposal_kind(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind in ("email_send", "email_reply"):
        return build_email_preview(payload)
    return {"action": kind, "payload": payload}
