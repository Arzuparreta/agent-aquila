"""Proactive agent layer.

Hooked from the mail / calendar / drive mirror services after every new ingest. For each
inbound entity the service:

1. Resolves (or creates) the relevant entity-bound chat thread so the artist sees a
   continuous conversation per topic ("Maria López", "Madrid Festival 2026", …).
2. Posts a system ``event`` message that announces the new arrival ("📩 Nuevo correo
   entrante de X — Asunto: Y").
3. Runs the agent in that thread context with a short briefing prompt; the agent
   decides whether to reply, propose, or just acknowledge.
4. Persists the assistant reply + any inline cards into the thread.
5. Fires a Web Push notification so the artist can see it on their phone immediately.

The whole flow is wrapped in defensive try/except blocks because it runs from background
workers — any exception bubbling up would interrupt the mirror sync. Failures are logged
but never re-raised.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.agent_service import AgentService
from app.services.chat_service import (
    append_message,
    get_or_create_entity_thread,
    history_for_agent,
)
from app.services.push_service import send_to_user

logger = logging.getLogger(__name__)


def _email_thread_title(email: Email) -> str:
    sender = email.sender_name or email.sender_email or "Remitente desconocido"
    return f"Correo · {sender}"[:255]


def _event_thread_title(event: Event) -> str:
    label = event.summary or event.venue_name or "Evento"
    return f"Evento · {label}"[:255]


def _agent_run_to_attachments(run) -> list[dict[str, Any]]:
    """Mirror of the helper in routes/threads — kept inline to avoid a circular import."""
    out: list[dict[str, Any]] = []
    for action in getattr(run, "executed_actions", None) or []:
        out.append(
            {
                "card_kind": "undo",
                "action_id": action.id,
                "kind": action.kind,
                "summary": action.summary,
                "status": action.status,
                "reversible_until": action.reversible_until.isoformat()
                if action.reversible_until
                else None,
                "result": action.result,
            }
        )
    for prop in getattr(run, "pending_proposals", None) or []:
        out.append(
            {
                "card_kind": "approval",
                "proposal_id": prop.id,
                "kind": prop.kind,
                "summary": prop.summary,
                "risk_tier": prop.risk_tier,
            }
        )
    return out


async def notify_email_received(db: AsyncSession, user: User, email: Email) -> None:
    """Spawn / reuse an entity thread for the email's contact (or sender) and run the agent.

    Best-effort: returns silently on any error so the mirror sync never crashes.
    """
    from app.services.agent_rate_limit_service import AgentRateLimitService

    if not AgentRateLimitService.try_consume_proactive(user.id):
        logger.warning(
            "proactive burst limit reached for user %s; skipping email %s",
            user.id, email.id,
        )
        return
    try:
        # Bind the thread to the linked Contact when we have one (so all messages from
        # this person live in one thread). Fall back to the email row itself otherwise.
        if email.contact_id:
            entity_type = "contact"
            entity_id = email.contact_id
            title = email.sender_name or email.sender_email or "Contacto"
        else:
            entity_type = "email"
            entity_id = email.id
            title = _email_thread_title(email)

        thread = await get_or_create_entity_thread(
            db, user, entity_type=entity_type, entity_id=entity_id, title=title
        )

        announcement = (
            f"📩 Nuevo correo entrante\n"
            f"De: {email.sender_name or ''} <{email.sender_email or ''}>\n"
            f"Asunto: {email.subject or ''}\n\n"
            f"{(email.snippet or email.body or '')[:600]}"
        )
        await append_message(
            db, thread, role="event", content=announcement,
            attachments=[{"event_kind": "email_received", "email_id": email.id}],
        )
        await db.commit()
        await db.refresh(thread)

        prior = await history_for_agent(db, thread)
        prompt = (
            "Acaba de llegar un correo nuevo en este hilo (ver mensaje anterior). "
            "Decide qué hacer: responder en chat al artista con un resumen breve y, si "
            "procede, proponer una respuesta al remitente vía propose_connector_email_reply, "
            "o crear/actualizar un trato/contacto/evento. Si la situación coincide con una "
            "regla aprendida, aplícala. Sé conciso."
        )
        run = await AgentService.run_agent(
            db, user, prompt,
            prior_messages=prior,
            thread_id=thread.id,
            thread_context_hint=(
                f"Conversación dedicada a {entity_type} #{entity_id} ({title}). "
                f"Trigger: nuevo email."
            ),
        )

        text = run.assistant_reply or (run.error or "")
        cards = _agent_run_to_attachments(run)
        asst_msg = await append_message(
            db, thread,
            role="assistant" if run.status == "completed" else "system",
            content=text,
            attachments=cards or None,
            agent_run_id=run.id,
        )
        await db.commit()
        await db.refresh(asst_msg)

        # Push: short headline + tap target = the thread.
        try:
            headline = email.subject or "Nuevo correo"
            preview = (text[:160] if text else "Toca para ver detalles.")
            await send_to_user(
                db, user,
                title=f"📩 {headline}",
                body=preview,
                url=f"/?thread={thread.id}",
                data={"thread_id": thread.id, "trigger": "email_received"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("push notification failed for thread %s: %s", thread.id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("proactive email handling failed: %s", exc)


async def notify_calendar_event(db: AsyncSession, user: User, event: Event, *, action: str) -> None:
    """Lightweight proactive ping for calendar events. ``action`` ∈ {"created","updated","deleted"}."""
    from app.services.agent_rate_limit_service import AgentRateLimitService

    if not AgentRateLimitService.try_consume_proactive(user.id):
        logger.warning(
            "proactive burst limit reached for user %s; skipping event %s",
            user.id, event.id,
        )
        return
    try:
        thread = await get_or_create_entity_thread(
            db, user, entity_type="event", entity_id=event.id, title=_event_thread_title(event)
        )
        when = event.start_utc.isoformat() if event.start_utc else (
            event.event_date.isoformat() if event.event_date else "fecha por confirmar"
        )
        verb = {"created": "Nuevo", "updated": "Actualizado", "deleted": "Eliminado"}.get(action, action)
        announcement = f"📅 {verb} evento de calendario: {event.summary or event.venue_name} ({when})."
        await append_message(
            db, thread, role="event", content=announcement,
            attachments=[{"event_kind": f"calendar_{action}", "event_id": event.id}],
        )
        await db.commit()
        try:
            await send_to_user(
                db, user,
                title=f"📅 {verb} evento",
                body=event.summary or event.venue_name or "Calendario actualizado",
                url=f"/?thread={thread.id}",
                data={"thread_id": thread.id, "trigger": f"calendar_{action}"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("push notification failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("proactive calendar handling failed: %s", exc)
