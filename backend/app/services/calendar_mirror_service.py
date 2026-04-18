"""Ingest Google Calendar events into the CRM mirror (shared `events` table).

For each Google event we either insert a row or update the existing one keyed by
(connection_id, provider_event_id). Deleted events (status=cancelled) are removed.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.event import Event
from app.models.user import User
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def _parse_event_dt(value: dict[str, Any] | None) -> tuple[datetime | None, bool]:
    """Return (utc_datetime, is_all_day). Google uses `dateTime` for timed and `date` for all-day."""
    if not value:
        return None, False
    if "dateTime" in value:
        raw = str(value["dateTime"])
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC), False
        except (TypeError, ValueError):
            return None, False
    if "date" in value:
        raw = str(value["date"])
        try:
            d = datetime.fromisoformat(raw).replace(tzinfo=UTC)
            return d, True
        except (TypeError, ValueError):
            return None, False
    return None, False


def _venue_name_from(summary: str | None, location: str | None, msg_id: str) -> str:
    if summary and summary.strip():
        return summary.strip()[:255]
    if location and location.strip():
        return location.strip()[:255]
    return f"Calendar event {msg_id[:40]}"


def _best_date(start_utc: datetime | None, fallback: datetime | None) -> date:
    for d in (start_utc, fallback):
        if d is not None:
            return d.date() if isinstance(d, datetime) else d
    return datetime.now(UTC).date()


class CalendarMirrorService:
    @staticmethod
    async def upsert_event(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        event_payload: dict[str, Any],
        *,
        calendar_id: str = "primary",
    ) -> Event | None:
        gid = str(event_payload.get("id") or "")
        if not gid:
            return None
        status_val = str(event_payload.get("status") or "confirmed").lower()

        result = await db.execute(
            select(Event).where(
                Event.connection_id == connection.id,
                Event.provider_event_id == gid,
            )
        )
        existing = result.scalar_one_or_none()

        if status_val == "cancelled":
            if existing:
                await create_audit_log(
                    db,
                    "event",
                    existing.id,
                    "deleted_from_calendar",
                    {"google_id": gid},
                    user.id,
                )
                await db.delete(existing)
            return None

        summary = event_payload.get("summary")
        location = event_payload.get("location")
        description = event_payload.get("description")
        html_link = event_payload.get("htmlLink")
        attendees = event_payload.get("attendees") or []
        recurrence = event_payload.get("recurrence") or None
        ical_uid = event_payload.get("iCalUID")

        start_utc, start_all_day = _parse_event_dt(event_payload.get("start"))
        end_utc, _ = _parse_event_dt(event_payload.get("end"))

        venue_name = _venue_name_from(summary if isinstance(summary, str) else None, location if isinstance(location, str) else None, gid)
        event_date = _best_date(start_utc, end_utc)

        attendee_data = [
            {
                "email": a.get("email"),
                "displayName": a.get("displayName"),
                "responseStatus": a.get("responseStatus"),
                "organizer": a.get("organizer"),
            }
            for a in attendees
            if isinstance(a, dict)
        ]

        if existing:
            existing.venue_name = venue_name
            existing.event_date = event_date
            existing.summary = (summary or "")[:500] if summary else existing.summary
            existing.location = (location or "")[:500] if location else existing.location
            existing.description = description if description else existing.description
            existing.html_link = html_link if html_link else existing.html_link
            existing.attendees = attendee_data or None
            existing.recurrence = list(recurrence) if recurrence else None
            existing.start_utc = start_utc
            existing.end_utc = end_utc
            existing.all_day = start_all_day
            existing.ical_uid = ical_uid or existing.ical_uid
            existing.provider_calendar_id = calendar_id
            existing.status = status_val
            await db.flush()
            try:
                await EmbeddingService.sync_event(db, user.id, existing.id)
            except Exception:  # pragma: no cover
                logger.exception("embedding sync failed for event %s", existing.id)
            return existing

        event = Event(
            venue_name=venue_name,
            event_date=event_date,
            city=None,
            status=status_val or "confirmed",
            notes=description if isinstance(description, str) else None,
            connection_id=connection.id,
            provider="google_calendar",
            provider_event_id=gid,
            provider_calendar_id=calendar_id,
            ical_uid=ical_uid,
            summary=(summary or "")[:500] if isinstance(summary, str) else None,
            location=(location or "")[:500] if isinstance(location, str) else None,
            description=description if isinstance(description, str) else None,
            html_link=html_link if isinstance(html_link, str) else None,
            attendees=attendee_data or None,
            recurrence=list(recurrence) if recurrence else None,
            start_utc=start_utc,
            end_utc=end_utc,
            all_day=start_all_day,
        )
        db.add(event)
        await db.flush()
        await create_audit_log(
            db, "event", event.id, "ingested_from_calendar", {"google_id": gid}, user.id
        )
        try:
            await EmbeddingService.sync_event(db, user.id, event.id)
        except Exception:
            logger.exception("embedding sync failed for event %s", event.id)
        try:
            from app.services.inbound_filter_service import (
                CATEGORY_ACTIONABLE,
                InboundFilterService,
            )

            verdict = await InboundFilterService.classify_event(
                db, user, event, payload=event_payload
            )
            InboundFilterService.apply_verdict_to_event(event, verdict)
            await db.flush()
            if verdict.category == CATEGORY_ACTIONABLE:
                from app.services.proactive_service import notify_calendar_event

                await notify_calendar_event(db, user, event, action="created")
            else:
                logger.info(
                    "silenced calendar event %s (%s/%s): %s",
                    event.id,
                    verdict.category,
                    verdict.source,
                    verdict.reason,
                )
        except Exception:
            logger.exception("inbound filter / proactive notification failed for event %s", event.id)
        return event

    @staticmethod
    async def upsert_from_write_result(
        db: AsyncSession,
        user: User,
        connection: ConnectorConnection,
        request_payload: dict[str, Any],
        send_result: dict[str, Any],
    ) -> Event | None:
        """After a successful write-through `create_calendar_event`, persist the returned event."""
        if not send_result.get("ok"):
            return None
        event_obj = send_result.get("event") if isinstance(send_result.get("event"), dict) else None
        if not event_obj:
            return None
        return await CalendarMirrorService.upsert_event(db, user, connection, event_obj)
