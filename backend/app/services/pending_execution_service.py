"""Apply approved proposals.

Handles ``email_send`` / ``email_reply`` via ``email_adapters.send_email``,
``whatsapp_send`` via Meta WhatsApp Cloud API, and ``youtube_upload`` via
YouTube Data API resumable upload.
"""
from __future__ import annotations

import base64
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.connector_service import ConnectorService
from app.services.connectors.email_adapters import send_email as email_send
from app.services.connectors.whatsapp_client import WhatsAppClient
from app.services.connectors.youtube_client import YoutubeClient
from app.services.oauth import TokenManager


class PendingExecutionService:
    """Applies an approved pending proposal to the live provider."""

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
        if kind == "whatsapp_send":
            await PendingExecutionService._exec_whatsapp(db, user, payload)
            return
        if kind == "youtube_upload":
            await PendingExecutionService._exec_youtube_upload(db, user, payload)
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

    @staticmethod
    async def _exec_whatsapp(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        row = await ConnectorService.require_connection(db, user, conn_id)
        if row.provider != "whatsapp_business":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="connection_id is not a WhatsApp Business connection",
            )
        _token, creds, _prov = await TokenManager.get_valid_creds(db, row)
        pnid = str(creds.get("phone_number_id") or "")
        gver = str(creds.get("graph_api_version") or "v21.0")
        client = WhatsAppClient(_token, pnid, api_version=gver)
        to_e164 = str(payload.get("to_e164") or "").strip()
        if not to_e164:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="to_e164 is required in proposal payload",
            )
        tname = (payload.get("template_name") or "").strip() if payload.get("template_name") else None
        if tname:
            tlang = str(payload.get("template_language") or "en")
            result = await client.send_template(
                to_e164, template_name=tname, language_code=tlang, components=None
            )
        else:
            body = str(payload.get("body") or "")
            if not body.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="body is required for session (non-template) WhatsApp messages",
                )
            result = await client.send_text(to_e164, body)
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "whatsapp_send",
            {"to": to_e164, "result": result},
            user.id,
        )

    @staticmethod
    async def _exec_youtube_upload(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        row = await ConnectorService.require_connection(db, user, conn_id)
        if row.provider != "google_youtube":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="connection_id is not a YouTube (google_youtube) connection",
            )
        b64 = str(payload.get("content_base64") or "")
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64: {exc}",
            ) from exc
        max_bytes = 12 * 1024 * 1024
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Decoded upload exceeds {max_bytes} bytes",
            )
        token, _creds, _p = await TokenManager.get_valid_creds(db, row)
        client = YoutubeClient(token)
        title = str(payload.get("title") or "upload")[:100]
        desc = str(payload.get("description") or "")[:5000]
        priv = str(payload.get("privacy_status") or "private")
        if priv not in ("private", "unlisted", "public"):
            priv = "private"
        result = await client.resumable_upload_video(
            title=title,
            description=desc,
            video_bytes=raw,
            mime_type=str(payload.get("mime_type") or "video/mp4"),
            privacy_status=priv,
        )
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "youtube_upload",
            {"title": title, "result_keys": list(result.keys()) if isinstance(result, dict) else []},
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


def build_whatsapp_preview(payload: dict[str, Any]) -> dict[str, Any]:
    tname = (payload.get("template_name") or "").strip() if payload.get("template_name") else None
    return {
        "action": "whatsapp_send",
        "to_e164": str(payload.get("to_e164") or ""),
        "mode": "template" if tname else "session_text",
        "template_name": tname,
        "template_language": str(payload.get("template_language") or "en")
        if tname
        else None,
        "body_preview": (str(payload.get("body") or ""))[:2000] if not tname else None,
    }


def build_youtube_upload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    b64 = str(payload.get("content_base64") or "")
    # Avoid decoding huge payloads in the UI thread — approximate or sample.
    est_len = 0
    if b64 and len(b64) <= 1_200_000:  # ~< ~900 KiB decoded
        try:
            est_len = len(base64.b64decode(b64, validate=True))
        except Exception:  # noqa: BLE001
            est_len = 0
    elif b64:
        pad = b64.rstrip()[-2:].count("=") if b64 else 0
        est_len = max(0, (len(b64) * 3) // 4 - pad)
    return {
        "action": "youtube_upload",
        "title": str(payload.get("title") or "")[:200],
        "description_preview": (str(payload.get("description") or ""))[:2000],
        "mime_type": str(payload.get("mime_type") or ""),
        "privacy_status": str(payload.get("privacy_status") or "private"),
        "decoded_size_bytes": est_len,
    }


def preview_for_proposal_kind(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind in ("email_send", "email_reply"):
        return build_email_preview(payload)
    if kind == "whatsapp_send":
        return build_whatsapp_preview(payload)
    if kind == "youtube_upload":
        return build_youtube_upload_preview(payload)
    return {"action": kind, "payload": payload}
