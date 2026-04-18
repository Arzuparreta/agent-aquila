from __future__ import annotations

import base64
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.contact import ContactCreate, ContactUpdate
from app.schemas.deal import DealCreate, DealUpdate
from app.schemas.event import EventCreate, EventUpdate
from app.services.audit_service import create_audit_log
from app.services.connector_service import ConnectorService
from app.services.contact_service import ContactService
from app.services.deal_service import DealService
from app.services.event_service import EventService
from app.services.connectors.calendar_adapters import create_calendar_event as cal_create
from app.services.connectors.email_adapters import send_email as email_send
from app.services.connectors.file_adapters import upload_file as file_upload
from app.services.connectors.teams_adapter import post_channel_message as teams_post


class PendingExecutionService:
    """Applies an approved pending proposal to CRM or external connectors."""

    @staticmethod
    async def execute(db: AsyncSession, user: User, kind: str, payload: dict[str, Any], *, commit: bool = True) -> None:
        uid = user.id
        if kind == "create_deal":
            deal_in = DealCreate(**payload)
            await DealService.create_deal(db, deal_in, uid, commit=commit)
            return
        if kind == "update_deal":
            deal_id = int(payload["deal_id"])
            data = {k: v for k, v in payload.items() if k != "deal_id"}
            if "amount" in data and data["amount"] is not None:
                data["amount"] = Decimal(str(data["amount"]))
            await DealService.update_deal(db, deal_id, DealUpdate(**data), uid, commit=commit)
            return
        if kind == "create_contact":
            await ContactService.create_contact(db, ContactCreate(**payload), uid, commit=commit)
            return
        if kind == "update_contact":
            contact_id = int(payload["contact_id"])
            data = {k: v for k, v in payload.items() if k != "contact_id"}
            await ContactService.update_contact(
                db, contact_id, ContactUpdate(**data), uid, commit=commit
            )
            return
        if kind == "create_event":
            await EventService.create_event(db, EventCreate(**payload), uid, commit=commit)
            return
        if kind == "update_event":
            event_id = int(payload["event_id"])
            data = {k: v for k, v in payload.items() if k != "event_id"}
            await EventService.update_event(
                db, event_id, EventUpdate(**data), uid, commit=commit
            )
            return

        if kind == "connector_email_send":
            await PendingExecutionService._exec_connector_email(db, user, payload)
            return
        if kind == "connector_calendar_create":
            await PendingExecutionService._exec_connector_calendar(db, user, payload)
            return
        if kind == "connector_file_upload":
            await PendingExecutionService._exec_connector_file(db, user, payload)
            return
        if kind == "connector_teams_message":
            await PendingExecutionService._exec_connector_teams(db, user, payload)
            return

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown proposal kind: {kind}")

    @staticmethod
    async def _exec_connector_email(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        to_list = payload["to"]
        if not isinstance(to_list, list):
            to_list = [str(to_list)]
        to_list = [str(x) for x in to_list]
        subject = str(payload["subject"])
        body = str(payload["body"])
        content_type = str(payload.get("content_type") or "text")
        row = await ConnectorService.require_connection(db, user, conn_id)
        creds = ConnectorService.decrypt_credentials(row)
        result = await email_send(
            row.provider, creds, to_list, subject, body, content_type=content_type, dry_run=False
        )
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "email_send",
            {"provider": row.provider, "to": to_list, "subject": subject, "result": result},
            user.id,
        )

    @staticmethod
    async def _exec_connector_calendar(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        row = await ConnectorService.require_connection(db, user, conn_id)
        creds = ConnectorService.decrypt_credentials(row)
        result = await cal_create(row.provider, creds, payload, dry_run=False)
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "calendar_create",
            {"provider": row.provider, "payload_keys": list(payload.keys()), "result": result},
            user.id,
        )

    @staticmethod
    async def _exec_connector_file(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        path = str(payload["path"])
        mime = str(payload.get("mime_type") or "application/octet-stream")
        raw: bytes
        if "content_base64" in payload and payload["content_base64"]:
            raw = base64.b64decode(str(payload["content_base64"]))
        elif "content_text" in payload:
            raw = str(payload["content_text"]).encode("utf-8")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file payload needs content_base64 or content_text")
        row = await ConnectorService.require_connection(db, user, conn_id)
        creds = ConnectorService.decrypt_credentials(row)
        result = await file_upload(row.provider, creds, path, raw, mime, dry_run=False)
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "file_upload",
            {"provider": row.provider, "path": path, "bytes": len(raw), "result": result},
            user.id,
        )

    @staticmethod
    async def _exec_connector_teams(db: AsyncSession, user: User, payload: dict[str, Any]) -> None:
        conn_id = int(payload["connection_id"])
        team_id = str(payload["team_id"])
        channel_id = str(payload["channel_id"])
        text = str(payload["body"])
        row = await ConnectorService.require_connection(db, user, conn_id)
        creds = ConnectorService.decrypt_credentials(row)
        result = await teams_post(row.provider, creds, team_id, channel_id, text, dry_run=False)
        await create_audit_log(
            db,
            "connector_action",
            conn_id,
            "teams_message",
            {"team_id": team_id, "channel_id": channel_id, "result": result},
            user.id,
        )


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
    }


def build_calendar_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "calendar_create",
        "summary": str(payload.get("summary") or payload.get("title") or ""),
        "start": str(payload.get("start_iso") or payload.get("start") or ""),
        "end": str(payload.get("end_iso") or payload.get("end") or ""),
        "description_preview": str(payload.get("description") or "")[:1500],
    }


def build_file_preview(payload: dict[str, Any]) -> dict[str, Any]:
    raw_len = 0
    if payload.get("content_base64"):
        try:
            raw_len = len(base64.b64decode(str(payload["content_base64"])))
        except Exception:
            raw_len = -1
    elif payload.get("content_text"):
        raw_len = len(str(payload["content_text"]).encode("utf-8"))
    return {"action": "file_upload", "path": str(payload.get("path") or ""), "bytes": raw_len, "mime_type": payload.get("mime_type")}


def build_teams_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "teams_message",
        "team_id": str(payload.get("team_id") or ""),
        "channel_id": str(payload.get("channel_id") or ""),
        "body_preview": str(payload.get("body") or "")[:2000],
    }


def build_create_deal_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "create_deal",
        "title": str(payload.get("title") or ""),
        "contact_id": payload.get("contact_id"),
        "status": str(payload.get("status") or "new"),
        "amount": payload.get("amount"),
        "currency": payload.get("currency"),
        "notes_preview": str(payload.get("notes") or "")[:1500],
    }


def build_update_deal_preview(payload: dict[str, Any]) -> dict[str, Any]:
    patch = {k: v for k, v in payload.items() if k != "deal_id"}
    return {"action": "update_deal", "deal_id": payload.get("deal_id"), "patch": patch}


def build_create_contact_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "create_contact",
        "name": str(payload.get("name") or ""),
        "email": payload.get("email"),
        "phone": payload.get("phone"),
        "role": str(payload.get("role") or "other"),
        "notes_preview": str(payload.get("notes") or "")[:1500],
    }


def build_update_contact_preview(payload: dict[str, Any]) -> dict[str, Any]:
    patch = {k: v for k, v in payload.items() if k != "contact_id"}
    return {"action": "update_contact", "contact_id": payload.get("contact_id"), "patch": patch}


def build_create_event_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "create_event",
        "venue_name": str(payload.get("venue_name") or ""),
        "event_date": str(payload.get("event_date") or ""),
        "deal_id": payload.get("deal_id"),
        "city": payload.get("city"),
        "status": str(payload.get("status") or "confirmed"),
        "notes_preview": str(payload.get("notes") or "")[:1500],
    }


def build_update_event_preview(payload: dict[str, Any]) -> dict[str, Any]:
    patch = {k: v for k, v in payload.items() if k != "event_id"}
    return {"action": "update_event", "event_id": payload.get("event_id"), "patch": patch}


def preview_for_proposal_kind(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "create_deal":
        return build_create_deal_preview(payload)
    if kind == "update_deal":
        return build_update_deal_preview(payload)
    if kind == "create_contact":
        return build_create_contact_preview(payload)
    if kind == "update_contact":
        return build_update_contact_preview(payload)
    if kind == "create_event":
        return build_create_event_preview(payload)
    if kind == "update_event":
        return build_update_event_preview(payload)
    if kind == "connector_email_send":
        return build_email_preview(payload)
    if kind == "connector_calendar_create":
        return build_calendar_preview(payload)
    if kind == "connector_file_upload":
        return build_file_preview(payload)
    if kind == "connector_teams_message":
        return build_teams_preview(payload)
    return {"action": kind, "payload": payload}
