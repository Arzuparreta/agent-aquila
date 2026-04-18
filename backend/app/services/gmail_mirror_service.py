"""Ingest Gmail messages into the Postgres CRM mirror.

Every ingested message re-uses the existing contact upsert + triage + embedding pipeline, so the
agent can query Gmail data via the same RAG + `emails` table it already knows about.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.connector_connection import ConnectorConnection
from app.models.contact import Contact
from app.models.email import Email, EmailAttachment
from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

_ADDR_RE = re.compile(r"(?:\"?([^\"<]+)\"?\s*)?<([^>]+)>|([^\s<>]+@[^\s<>]+)")


def _parse_address(raw: str) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    m = _ADDR_RE.search(raw)
    if not m:
        return None, None
    if m.group(2):
        name = (m.group(1) or "").strip() or None
        email_addr = m.group(2).strip().lower()
        return name, email_addr
    if m.group(3):
        return None, m.group(3).strip().lower()
    return None, None


def _headers_to_dict(headers: Iterable[dict[str, str]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not headers:
        return out
    for h in headers:
        name = str(h.get("name") or "").strip()
        if name:
            out[name.lower()] = str(h.get("value") or "")
    return out


def _decode_b64url(data: str | None) -> bytes:
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _extract_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (plain_text, html) by walking the multipart tree."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def _walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime == "text/plain":
            try:
                plain_parts.append(_decode_b64url(data).decode("utf-8", "replace"))
            except Exception:
                pass
        elif data and mime == "text/html":
            try:
                html_parts.append(_decode_b64url(data).decode("utf-8", "replace"))
            except Exception:
                pass
        for child in part.get("parts") or []:
            _walk(child)

    _walk(payload or {})
    return "\n\n".join(plain_parts).strip(), "\n\n".join(html_parts).strip()


def _collect_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def _walk(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        filename = str(part.get("filename") or "").strip()
        if filename and body.get("attachmentId"):
            out.append(
                {
                    "provider_attachment_id": str(body.get("attachmentId")),
                    "filename": filename[:500],
                    "mime_type": str(part.get("mimeType") or "") or None,
                    "size_bytes": int(body.get("size") or 0) or None,
                }
            )
        for child in part.get("parts") or []:
            _walk(child)

    _walk(payload or {})
    return out


def _html_to_text(html: str) -> str:
    # Extremely simple fallback for mirror snippets (we keep the raw HTML in body_html too).
    clean = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<style[^>]*>.*?</style>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


class GmailMirrorService:
    @staticmethod
    async def _upsert_contact_from_address(
        db: AsyncSession, name: str | None, email_addr: str | None
    ) -> Contact | None:
        if not email_addr:
            return None
        r = await db.execute(select(Contact).where(Contact.email == email_addr))
        contact = r.scalar_one_or_none()
        if contact:
            return contact
        contact = Contact(name=name or email_addr, email=email_addr, role="other")
        db.add(contact)
        await db.flush()
        await create_audit_log(
            db,
            "contact",
            contact.id,
            "created_from_gmail",
            {"email": email_addr, "name": name},
            None,
        )
        return contact

    @staticmethod
    async def upsert_message(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        message: dict[str, Any],
        *,
        run_triage: bool = True,
    ) -> Email:
        """Insert-or-update one Gmail `messages.get(format=full)` response into the mirror.

        Returns the persisted Email row. Idempotent on (connection_id, provider_message_id).
        """
        from app.services.email_service import EmailService
        from app.services.triage_service import TriageService

        msg_id = str(message.get("id") or "")
        thread_id = str(message.get("threadId") or "") or None
        label_ids = list(message.get("labelIds") or [])
        snippet = str(message.get("snippet") or "")[:4000]
        internal_ts = message.get("internalDate")
        internal_date: datetime | None
        if internal_ts:
            try:
                internal_date = datetime.fromtimestamp(int(internal_ts) / 1000, tz=UTC)
            except (TypeError, ValueError):
                internal_date = None
        else:
            internal_date = None

        payload = message.get("payload") or {}
        headers = _headers_to_dict(payload.get("headers"))
        subject = headers.get("subject") or "(no subject)"
        from_raw = headers.get("from") or ""
        sender_name, sender_email = _parse_address(from_raw)
        if not sender_email:
            sender_email = (headers.get("return-path") or "").strip("<>").lower() or "unknown@unknown"
        received_hdr = headers.get("date")
        received_at: datetime
        if received_hdr:
            try:
                parsed_dt = parsedate_to_datetime(received_hdr)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=UTC)
                received_at = parsed_dt.astimezone(UTC)
            except (TypeError, ValueError):
                received_at = internal_date or datetime.now(UTC)
        else:
            received_at = internal_date or datetime.now(UTC)

        body_text, body_html = _extract_bodies(payload)
        if not body_text and body_html:
            body_text = _html_to_text(body_html)
        body_text = body_text[:200_000]
        body_html = body_html[:500_000] if body_html else None

        direction = "outbound" if "SENT" in label_ids else "inbound"
        is_read = "UNREAD" not in label_ids

        result = await db.execute(
            select(Email).where(
                Email.connection_id == connection.id,
                Email.provider_message_id == msg_id,
            )
        )
        existing = result.scalar_one_or_none()

        # Try to link the CRM contact from the "other" side (sender for inbound, first recipient for outbound).
        link_name = sender_name
        link_addr = sender_email
        if direction == "outbound":
            to_hdr = headers.get("to") or ""
            ln, la = _parse_address(to_hdr)
            if la:
                link_name, link_addr = ln, la
        contact = await GmailMirrorService._upsert_contact_from_address(db, link_name, link_addr)

        if existing:
            existing.labels = label_ids
            existing.is_read = is_read
            existing.snippet = snippet or existing.snippet
            if body_text and not existing.body:
                existing.body = body_text
            if body_html is not None:
                existing.body_html = body_html
            existing.provider_thread_id = thread_id or existing.provider_thread_id
            existing.internal_date = internal_date or existing.internal_date
            existing.direction = direction
            if contact and not existing.contact_id:
                existing.contact_id = contact.id
            await db.flush()
            return existing

        email = Email(
            contact_id=contact.id if contact else None,
            connection_id=connection.id,
            provider="google_gmail",
            provider_message_id=msg_id,
            provider_thread_id=thread_id,
            direction=direction,
            labels=label_ids,
            in_reply_to=(headers.get("in-reply-to") or None),
            snippet=snippet or None,
            body_html=body_html,
            internal_date=internal_date,
            is_read=is_read,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject[:500],
            body=body_text or snippet or "",
            received_at=received_at,
            raw_headers={"gmail_headers": headers, "label_ids": label_ids},
        )
        db.add(email)
        await db.flush()

        for att in _collect_attachments(payload):
            db.add(
                EmailAttachment(
                    email_id=email.id,
                    provider_attachment_id=att["provider_attachment_id"],
                    filename=att["filename"],
                    mime_type=att["mime_type"],
                    size_bytes=att["size_bytes"],
                )
            )

        await create_audit_log(
            db,
            "email",
            email.id,
            "ingested_from_gmail",
            {"message_id": msg_id, "thread_id": thread_id, "direction": direction},
            user.id,
        )

        # Re-use the existing triage + ingestion rules (LLM classify + auto-deal if enabled).
        # Only on inbound — we don't need to triage our own sent mail.
        if direction == "inbound" and contact and run_triage:
            try:
                triage = await TriageService.evaluate(db, user.id, email.subject, email.body)
                await create_audit_log(db, "email", email.id, "ai_triage", triage, user.id)
                await EmailService._apply_ingestion_rules(db, email, contact.id, user.id, triage)
            except Exception:
                logger.exception("triage failed for email %s", email.id)

        # Embeddings for RAG.
        try:
            await EmbeddingService.sync_email(db, user.id, email.id)
            if contact:
                await EmbeddingService.sync_contact(db, user.id, contact.id)
        except Exception:
            logger.exception("embedding sync failed for email %s", email.id)

        # Automation dispatch — fire-and-forget enqueue for every matching rule.
        if direction == "inbound" and run_triage:
            try:
                from app.services.automation_service import dispatch_email_received

                await dispatch_email_received(db, user, email)
            except Exception:
                logger.exception("automation dispatch failed for email %s", email.id)

            try:
                from app.services.proactive_service import notify_email_received

                await notify_email_received(db, user, email)
            except Exception:
                logger.exception("proactive notification failed for email %s", email.id)

        return email

    @staticmethod
    async def delete_message(db: AsyncSession, connection: ConnectorConnection, provider_message_id: str) -> None:
        result = await db.execute(
            select(Email).where(
                Email.connection_id == connection.id,
                Email.provider_message_id == provider_message_id,
            )
        )
        email = result.scalar_one_or_none()
        if email:
            await db.delete(email)

    @staticmethod
    async def record_outbound(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        *,
        to_list: list[str],
        subject: str,
        body: str,
        content_type: str,
        send_result: dict[str, Any],
        thread_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> Email | None:
        """Persist a just-sent message into the mirror. If Gmail returned an `id`, we store it so the
        next delta sync dedupes on the same row; otherwise a synthetic id avoids dupes.
        """
        msg_id = str(send_result.get("id") or "") or f"local-{datetime.now(UTC).isoformat()}"
        existing = None
        result = await db.execute(
            select(Email).where(
                Email.connection_id == connection.id,
                Email.provider_message_id == msg_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        recipient_name, recipient_addr = _parse_address(to_list[0]) if to_list else (None, None)
        contact = await GmailMirrorService._upsert_contact_from_address(db, recipient_name, recipient_addr)

        email = Email(
            contact_id=contact.id if contact else None,
            connection_id=connection.id,
            provider=connection.provider,
            provider_message_id=msg_id,
            provider_thread_id=str(send_result.get("thread_id") or thread_id or "") or None,
            direction="outbound",
            labels=list(send_result.get("label_ids") or []) or ["SENT"],
            in_reply_to=in_reply_to,
            snippet=(body[:4000] if content_type != "html" else _html_to_text(body)[:4000]),
            body_html=body if content_type == "html" else None,
            internal_date=datetime.now(UTC),
            is_read=True,
            sender_email=str(user.email),
            sender_name=None,
            subject=subject[:500],
            body=body if content_type != "html" else _html_to_text(body),
            received_at=datetime.now(UTC),
            raw_headers={"source": "outbound_send_back"},
        )
        db.add(email)
        await db.flush()
        try:
            await EmbeddingService.sync_email(db, user.id, email.id)
        except Exception:
            logger.exception("embedding sync failed for outbound email %s", email.id)
        return email


__all__ = ["GmailMirrorService"]
