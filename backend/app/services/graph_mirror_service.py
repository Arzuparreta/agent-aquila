"""Map Microsoft Graph resources into our existing mirror tables (Email, Event, DriveFile).

Re-uses the same downstream pipelines (contact resolution, embeddings) as GmailMirrorService so
the agent's RAG and relational queries work the same way for Outlook/Teams data.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.contact import Contact
from app.models.drive_file import DriveFile
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def _parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _address_from_graph(field: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not field:
        return None, None
    addr = field.get("emailAddress") or {}
    return (addr.get("name") or None, (addr.get("address") or "").lower() or None)


class GraphMirrorService:
    # ------------------------- Mail -------------------------
    @staticmethod
    async def _upsert_contact(db: AsyncSession, name: str | None, addr: str | None) -> Contact | None:
        if not addr:
            return None
        r = await db.execute(select(Contact).where(Contact.email == addr))
        contact = r.scalar_one_or_none()
        if contact:
            return contact
        contact = Contact(name=name or addr, email=addr, role="other")
        db.add(contact)
        await db.flush()
        await create_audit_log(db, "contact", contact.id, "created_from_graph", {"email": addr}, None)
        return contact

    @staticmethod
    async def upsert_mail(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        message: dict[str, Any],
    ) -> Email | None:
        """Idempotent on (connection_id, provider_message_id). Skips items marked as `@removed`."""
        if message.get("@removed"):
            mid = str(message.get("id") or "")
            if mid:
                await GraphMirrorService.delete_mail(db, connection, mid)
            return None

        from app.services.email_service import EmailService
        from app.services.triage_service import TriageService

        msg_id = str(message.get("id") or "")
        if not msg_id:
            return None

        subject = str(message.get("subject") or "(no subject)")
        sender_name, sender_email = _address_from_graph(message.get("from") or message.get("sender"))
        to_recipients = message.get("toRecipients") or []
        received_at = _parse_graph_datetime(message.get("receivedDateTime")) or datetime.now(UTC)
        body_obj = message.get("body") or {}
        content_type = str(body_obj.get("contentType") or "text").lower()
        raw_body = str(body_obj.get("content") or "")
        body_html = raw_body if content_type == "html" else None
        body_text = raw_body if content_type != "html" else ""
        snippet = str(message.get("bodyPreview") or "")[:4000]
        is_read = bool(message.get("isRead", True))
        thread_id = str(message.get("conversationId") or "") or None

        # Direction heuristic: outlook doesn't give us "SENT" labels on /me/messages, but if the
        # sender address matches the user we treat as outbound.
        direction = "inbound"
        if sender_email and sender_email.lower() == (user.email or "").lower():
            direction = "outbound"

        link_name, link_addr = sender_name, sender_email
        if direction == "outbound" and to_recipients:
            link_name, link_addr = _address_from_graph(to_recipients[0])
        contact = await GraphMirrorService._upsert_contact(db, link_name, link_addr)

        existing_res = await db.execute(
            select(Email).where(
                Email.connection_id == connection.id,
                Email.provider_message_id == msg_id,
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.is_read = is_read
            existing.snippet = snippet or existing.snippet
            if body_text and not existing.body:
                existing.body = body_text
            if body_html is not None:
                existing.body_html = body_html
            existing.provider_thread_id = thread_id or existing.provider_thread_id
            existing.direction = direction
            if contact and not existing.contact_id:
                existing.contact_id = contact.id
            await db.flush()
            return existing

        email = Email(
            contact_id=contact.id if contact else None,
            connection_id=connection.id,
            provider="graph_mail",
            provider_message_id=msg_id,
            provider_thread_id=thread_id,
            direction=direction,
            labels=[],
            in_reply_to=str(message.get("internetMessageId") or "") or None,
            snippet=snippet or None,
            body_html=body_html,
            internal_date=received_at,
            is_read=is_read,
            sender_email=(sender_email or "unknown@unknown"),
            sender_name=sender_name,
            subject=subject[:500],
            body=body_text or snippet or "",
            received_at=received_at,
            raw_headers={"source": "graph", "parent_folder_id": message.get("parentFolderId")},
        )
        db.add(email)
        await db.flush()

        await create_audit_log(
            db,
            "email",
            email.id,
            "ingested_from_graph",
            {"message_id": msg_id, "thread_id": thread_id, "direction": direction},
            user.id,
        )

        if direction == "inbound" and contact:
            try:
                triage = await TriageService.evaluate(db, user.id, email.subject, email.body)
                await create_audit_log(db, "email", email.id, "ai_triage", triage, user.id)
                await EmailService._apply_ingestion_rules(db, email, contact.id, user.id, triage)
            except Exception:
                logger.exception("graph mail triage failed for %s", email.id)

        try:
            await EmbeddingService.sync_email(db, user.id, email.id)
            if contact:
                await EmbeddingService.sync_contact(db, user.id, contact.id)
        except Exception:
            logger.exception("graph mail embedding failed for %s", email.id)

        if direction == "inbound":
            try:
                from app.services.automation_service import dispatch_email_received

                await dispatch_email_received(db, user, email)
            except Exception:
                logger.exception("graph automation dispatch failed for email %s", email.id)

            try:
                from app.services.proactive_service import notify_email_received

                await notify_email_received(db, user, email)
            except Exception:
                logger.exception("graph proactive notification failed for email %s", email.id)

        return email

    @staticmethod
    async def delete_mail(db: AsyncSession, connection: ConnectorConnection, provider_message_id: str) -> None:
        r = await db.execute(
            select(Email).where(
                Email.connection_id == connection.id, Email.provider_message_id == provider_message_id
            )
        )
        row = r.scalar_one_or_none()
        if row:
            await db.delete(row)

    # ------------------------- Calendar -------------------------
    @staticmethod
    async def upsert_event(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        event: dict[str, Any],
    ) -> Event | None:
        if event.get("@removed"):
            eid = str(event.get("id") or "")
            if eid:
                await GraphMirrorService.delete_event(db, connection, eid)
            return None

        evid = str(event.get("id") or "")
        if not evid:
            return None
        start_dt = _parse_graph_datetime((event.get("start") or {}).get("dateTime"))
        end_dt = _parse_graph_datetime((event.get("end") or {}).get("dateTime"))
        if not start_dt:
            return None
        all_day = bool(event.get("isAllDay"))
        location = (event.get("location") or {}).get("displayName")
        attendees_raw = event.get("attendees") or []
        attendees = [
            {
                "email": (a.get("emailAddress") or {}).get("address"),
                "name": (a.get("emailAddress") or {}).get("name"),
                "status": (a.get("status") or {}).get("response"),
            }
            for a in attendees_raw
        ]

        existing_res = await db.execute(
            select(Event).where(
                Event.connection_id == connection.id, Event.provider_event_id == evid
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.summary = str(event.get("subject") or existing.summary or "")
            existing.description = str(event.get("bodyPreview") or existing.description or "")
            existing.location = location
            existing.start_utc = start_dt
            existing.end_utc = end_dt
            existing.all_day = all_day
            existing.attendees = attendees
            existing.html_link = str(event.get("webLink") or existing.html_link or "")
            existing.ical_uid = str(event.get("iCalUId") or existing.ical_uid or "")
            await db.flush()
            return existing

        row = Event(
            connection_id=connection.id,
            provider="graph_calendar",
            provider_event_id=evid,
            provider_calendar_id="primary",
            ical_uid=str(event.get("iCalUId") or "") or None,
            summary=str(event.get("subject") or "(no title)"),
            description=str(event.get("bodyPreview") or ""),
            location=location,
            html_link=str(event.get("webLink") or "") or None,
            attendees=attendees,
            start_utc=start_dt,
            end_utc=end_dt,
            all_day=all_day,
            venue_name=location or str(event.get("subject") or "(no title)"),
            event_date=start_dt,
            city=None,
            status="confirmed",
        )
        db.add(row)
        await db.flush()
        await create_audit_log(
            db, "event", row.id, "ingested_from_graph", {"provider_event_id": evid}, user.id
        )
        try:
            await EmbeddingService.sync_event(db, user.id, row.id)
        except Exception:
            logger.exception("graph event embedding failed for %s", row.id)
        try:
            from app.services.proactive_service import notify_calendar_event

            await notify_calendar_event(db, user, row, action="created")
        except Exception:
            logger.exception("graph proactive notification failed for event %s", row.id)
        return row

    @staticmethod
    async def delete_event(db: AsyncSession, connection: ConnectorConnection, provider_event_id: str) -> None:
        r = await db.execute(
            select(Event).where(
                Event.connection_id == connection.id, Event.provider_event_id == provider_event_id
            )
        )
        row = r.scalar_one_or_none()
        if row:
            await db.delete(row)

    # ------------------------- OneDrive -------------------------
    @staticmethod
    async def upsert_drive_item(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        item: dict[str, Any],
    ) -> DriveFile | None:
        if item.get("deleted") or item.get("@removed"):
            fid = str(item.get("id") or "")
            if fid:
                await GraphMirrorService.delete_drive_item(db, connection, fid)
            return None

        fid = str(item.get("id") or "")
        if not fid:
            return None
        name = str(item.get("name") or "")
        mime = (item.get("file") or {}).get("mimeType") if item.get("file") else None
        size = int(item.get("size") or 0) or None
        parent_ref = item.get("parentReference") or {}
        parents = [parent_ref.get("id")] if parent_ref.get("id") else []
        modified_time = _parse_graph_datetime(item.get("lastModifiedDateTime"))
        web_view = str(item.get("webUrl") or "") or None
        is_trashed = bool((item.get("deleted") or {}).get("state"))
        owners = []
        created_by = (item.get("createdBy") or {}).get("user")
        if created_by and created_by.get("email"):
            owners.append({"emailAddress": created_by.get("email"), "displayName": created_by.get("displayName")})

        existing_res = await db.execute(
            select(DriveFile).where(
                DriveFile.connection_id == connection.id, DriveFile.provider_file_id == fid
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.name = name or existing.name
            existing.mime_type = mime or existing.mime_type
            existing.size_bytes = size if size is not None else existing.size_bytes
            existing.parents = parents or existing.parents
            existing.owners = owners or existing.owners
            existing.modified_time = modified_time or existing.modified_time
            existing.web_view_link = web_view or existing.web_view_link
            existing.is_trashed = is_trashed
            await db.flush()
            return existing

        row = DriveFile(
            connection_id=connection.id,
            provider="graph_onedrive",
            provider_file_id=fid,
            name=name,
            mime_type=mime,
            size_bytes=size,
            parents=parents,
            owners=owners,
            web_view_link=web_view,
            modified_time=modified_time,
            is_trashed=is_trashed,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def delete_drive_item(
        db: AsyncSession, connection: ConnectorConnection, provider_file_id: str
    ) -> None:
        r = await db.execute(
            select(DriveFile).where(
                DriveFile.connection_id == connection.id, DriveFile.provider_file_id == provider_file_id
            )
        )
        row = r.scalar_one_or_none()
        if row:
            await db.delete(row)


__all__ = ["GraphMirrorService"]
