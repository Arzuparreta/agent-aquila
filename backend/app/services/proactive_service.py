"""Proactive notification layer.

Hooked from the mail / calendar mirror services after every new ingest. Today
this layer is **push-only**: we send a Web Push notification so the artist can
see something new arrived, and that's it. The agent does NOT run, and no chat
threads are auto-spawned.

Rationale: previously this layer auto-created an entity-bound chat thread per
sender ("Mozilla", "LinkedIn", "Shipco IT"…) and immediately ran the agent
with a "summarize this for the artist" prompt on every actionable email. That
flooded the chat sidebar with junk threads where the agent talked to itself,
and on weak local models (Gemma 3B/4B class) it hallucinated unrelated email
ids in those auto-replies.

The new contract is the inverse: emails land in the Inbox UI, and the user
decides on demand whether to reference them in a chat or start a new chat
about them (see ``POST /emails/{id}/start-chat``). The agent only runs in
response to a user-typed message.

The whole flow is wrapped in defensive try/except blocks because it runs from
background workers — any exception bubbling up would interrupt the mirror
sync. Failures are logged but never re-raised.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.push_service import send_to_user

logger = logging.getLogger(__name__)


async def notify_email_received(db: AsyncSession, user: User, email: Email) -> None:
    """Push-only: ping the artist that a new actionable email arrived.

    Best-effort: returns silently on any error so the mirror sync never
    crashes. Does NOT touch chat threads and does NOT run the agent.
    """
    from app.services.agent_rate_limit_service import AgentRateLimitService

    if not AgentRateLimitService.try_consume_proactive(user.id):
        logger.warning(
            "proactive burst limit reached for user %s; skipping email %s",
            user.id, email.id,
        )
        return
    try:
        sender = email.sender_name or email.sender_email or "Remitente desconocido"
        subject = email.subject or "(sin asunto)"
        await send_to_user(
            db, user,
            title=f"Nuevo correo: {subject}"[:120],
            body=f"De {sender}",
            url=f"/inbox?email={email.id}",
            data={"email_id": email.id, "trigger": "email_received"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("push notification failed for email %s: %s", email.id, exc)


async def notify_calendar_event(
    db: AsyncSession, user: User, event: Event, *, action: str
) -> None:
    """Push-only: ping the artist that a calendar item was created/updated/deleted.

    ``action`` ∈ {"created", "updated", "deleted"}. Same contract as
    ``notify_email_received``: no thread, no agent run, push only.
    """
    from app.services.agent_rate_limit_service import AgentRateLimitService

    if not AgentRateLimitService.try_consume_proactive(user.id):
        logger.warning(
            "proactive burst limit reached for user %s; skipping event %s",
            user.id, event.id,
        )
        return
    try:
        verb = {"created": "Nuevo", "updated": "Actualizado", "deleted": "Eliminado"}.get(
            action, action
        )
        label = event.summary or event.venue_name or "Calendario"
        await send_to_user(
            db, user,
            title=f"{verb} evento: {label}"[:120],
            body="Calendario actualizado",
            url="/inbox",
            data={"event_id": event.id, "trigger": f"calendar_{action}"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("push notification failed for event %s: %s", event.id, exc)
