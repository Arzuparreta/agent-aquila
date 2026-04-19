"""Chat threads + messages — the artist-first home of the new app.

Endpoints:
- ``GET    /threads`` — list threads (excludes archived by default).
- ``POST   /threads`` — create a manual thread (or upsert an entity-bound one).
- ``GET    /threads/{id}`` — read a single thread.
- ``PATCH  /threads/{id}`` — pin/archive/title.
- ``DELETE /threads/{id}`` — hard-delete the thread (cascades to chat_messages;
  ``executed_actions.thread_id`` and ``attachments.thread_id`` are SET NULL by
  the migration so audit history survives).
- ``GET    /threads/{id}/messages`` — paginated message history.
- ``POST   /threads/{id}/messages`` — append a user message and run the agent in this
  thread context. Persists both messages, returns the assistant reply with any inline
  cards (approval / undo / setup) attached as ``attachments``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.chat import (
    MessageCreate,
    MessageRead,
    MessageSendResult,
    ThreadCreate,
    ThreadPatch,
    ThreadRead,
)
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.capability_policy import risk_tier_for_kind
from app.services.chat_service import (
    append_message,
    get_or_create_entity_thread,
    get_or_create_general_thread,
    get_thread,
    history_for_agent,
    list_messages,
    list_threads,
    message_to_read,
    render_user_message,
    thread_to_read,
)
from app.services.pending_execution_service import preview_for_proposal_kind

router = APIRouter(prefix="/threads", tags=["threads"], dependencies=[Depends(get_current_user)])


async def _build_thread_context_hint(db: AsyncSession, thread) -> str | None:
    """Build the system-prompt suffix for entity-bound threads.

    Returns a short, single-line sentence describing the bound entity so the agent
    knows what the thread is about without needing a tool call. Falls back to a
    minimal "conversación dedicada al {type} #{id}" when the entity can't be
    fetched (deleted, permission issue, etc.). Non-entity threads get ``None``.
    """
    if thread.kind != "entity" or not thread.entity_type:
        return None

    fallback = (
        f"Conversación dedicada al {thread.entity_type} #{thread.entity_id} ({thread.title})."
    )

    try:
        if thread.entity_type == "email":
            from app.services.email_service import EmailService

            email = await EmailService.get_email(db, thread.entity_id)
            if not email:
                return fallback
            bits = [
                f"de {email.sender_name or email.sender_email}" if (email.sender_name or email.sender_email) else None,
                f"asunto \"{email.subject}\"" if email.subject else None,
            ]
            tail = " · ".join(b for b in bits if b)
            snippet = (email.snippet or email.body or "").strip().replace("\n", " ")[:200]
            return (
                f"Conversación dedicada al correo #{email.id}"
                f"{' ' + tail if tail else ''}."
                f"{' Extracto: ' + snippet if snippet else ''}"
            )

        if thread.entity_type == "contact":
            from app.services.contact_service import ContactService

            contact = await ContactService.get_contact(db, thread.entity_id)
            bits = [
                f"Email: {contact.email}" if contact.email else None,
                f"Teléfono: {contact.phone}" if contact.phone else None,
                f"Rol: {contact.role}" if contact.role and contact.role != "other" else None,
            ]
            tail = " · ".join(b for b in bits if b)
            return (
                f"Conversación dedicada al contacto #{contact.id} ({contact.name})."
                f"{' ' + tail + '.' if tail else ''}"
            )

        if thread.entity_type == "deal":
            from app.services.deal_service import DealService

            deal = await DealService.get_deal(db, thread.entity_id)
            amount = None
            if deal.amount is not None:
                amount = f"Monto: {deal.amount}{' ' + deal.currency if deal.currency else ''}"
            bits = [
                f"Estado: {deal.status}" if deal.status else None,
                amount,
            ]
            tail = " · ".join(b for b in bits if b)
            return (
                f"Conversación dedicada al trato #{deal.id} ({deal.title})."
                f"{' ' + tail + '.' if tail else ''}"
            )

        if thread.entity_type == "event":
            from app.services.event_service import EventService

            event = await EventService.get_event(db, thread.entity_id)
            when = event.event_date.isoformat() if event.event_date else None
            bits = [
                f"Fecha: {when}" if when else None,
                f"Ciudad: {event.city}" if event.city else None,
                f"Recinto: {event.venue_name}" if event.venue_name else None,
            ]
            tail = " · ".join(b for b in bits if b)
            return (
                f"Conversación dedicada al evento #{event.id} ({event.venue_name})."
                f"{' ' + tail + '.' if tail else ''}"
            )

        if thread.entity_type == "attachment":
            from app.models.attachment import Attachment

            row = await db.get(Attachment, thread.entity_id)
            if not row:
                return fallback
            size_kb = (row.size_bytes or 0) / 1024
            return (
                f"Conversación dedicada al archivo #{row.id} ({row.filename})."
                f" Tipo: {row.mime_type} · Tamaño: {size_kb:.1f} KB."
            )
    except Exception:  # noqa: BLE001 — hint enrichment must never break the send turn
        return fallback

    return fallback


def _agent_run_to_attachments(run) -> list[dict[str, Any]]:
    """Translate executed actions and pending proposals into inline chat cards.

    Each card shape (frontend-aware):
      - {"card_kind": "undo", "action_id": int, "kind": str, "summary": str,
         "reversible_until": iso, "result": {...}}
      - {"card_kind": "approval", "proposal_id": int, "kind": str, "summary": str,
         "risk_tier": str, "preview": {...}}
    Connector setup / oauth_authorize cards are emitted directly by the agent tools as
    tool results; we surface those to the FE by inspecting agent steps. (The chat view
    can also poll thread refs if the agent did not embed a card.)
    """
    out: list[dict[str, Any]] = []
    for action in run.executed_actions or []:
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
    for prop in run.pending_proposals or []:
        out.append(
            {
                "card_kind": "approval",
                "proposal_id": prop.id,
                "kind": prop.kind,
                "summary": prop.summary,
                "risk_tier": prop.risk_tier or risk_tier_for_kind(prop.kind),
                "preview": preview_for_proposal_kind(prop.kind, dict(prop.payload)),
            }
        )
    # Surface any tool results that look like setup cards (connector_setup / oauth_authorize).
    for step in run.steps or []:
        if not step.payload:
            continue
        # Provider-error / key-decrypt steps emitted by the agent loop become
        # inline chat cards so the UI can render the "Probar conexión" /
        # "Abrir ajustes" affordances instead of dumping raw httpx text.
        if step.kind == "provider_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "provider_error")
            out.append(payload)
            continue
        if step.kind == "key_decrypt_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "key_decrypt_error")
            out.append(payload)
            continue
        if step.kind != "tool":
            continue
        result = step.payload.get("result") if isinstance(step.payload, dict) else None
        if isinstance(result, dict) and result.get("card_kind") in {
            "connector_setup",
            "oauth_authorize",
        }:
            out.append(result)
    return out


@router.get("", response_model=list[ThreadRead])
async def get_threads(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadRead]:
    # Ensure the artist always has a "General" thread to land on.
    await get_or_create_general_thread(db, current_user)
    await db.commit()
    rows = await list_threads(db, current_user, include_archived=include_archived)
    return [thread_to_read(r) for r in rows]


@router.post("", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    if payload.entity_type and payload.entity_id:
        row = await get_or_create_entity_thread(
            db,
            current_user,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            title=payload.title,
        )
    else:
        # Free-form manual thread (kind=general) with custom title.
        from app.models.chat_thread import ChatThread

        row = ChatThread(
            user_id=current_user.id,
            kind="general",
            title=(payload.title or "Nueva conversación")[:255],
        )
        db.add(row)
        await db.flush()
    await db.commit()
    await db.refresh(row)
    return thread_to_read(row)


@router.get("/{thread_id}", response_model=ThreadRead)
async def read_thread(
    thread_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return thread_to_read(row)


@router.patch("/{thread_id}", response_model=ThreadRead)
async def patch_thread(
    thread_id: int,
    patch: ThreadPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    if patch.title is not None:
        row.title = patch.title.strip()[:255] or row.title
    if patch.pinned is not None:
        row.pinned = bool(patch.pinned)
    if patch.archived is not None:
        row.archived = bool(patch.archived)
    await db.commit()
    await db.refresh(row)
    return thread_to_read(row)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Hard-delete a chat thread owned by the calling user.

    DB-level ``ON DELETE CASCADE`` on ``chat_messages.thread_id`` removes the
    message history automatically. ``executed_actions.thread_id`` and
    ``attachments.thread_id`` are ``SET NULL`` (see migration
    ``0012_chat_artist_rework``), so audit history and uploaded files survive
    the deletion.
    """
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{thread_id}/messages", response_model=list[MessageRead])
async def read_messages(
    thread_id: int,
    limit: int = Query(default=200, ge=1, le=500),
    before_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageRead]:
    thread = await get_thread(db, current_user, thread_id)
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    rows = await list_messages(db, thread, limit=limit, before_id=before_id)
    return [message_to_read(m) for m in rows]


@router.post("/{thread_id}/messages", response_model=MessageSendResult)
async def send_message(
    thread_id: int,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageSendResult:
    thread = await get_thread(db, current_user, thread_id)
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    AgentRateLimitService.check(current_user.id)

    user_attachments = (
        [r.model_dump() for r in payload.references] if payload.references else None
    )
    user_msg = await append_message(
        db,
        thread,
        role="user",
        content=payload.content,
        attachments=user_attachments,
    )
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(thread)

    prior = await history_for_agent(db, thread)
    # Drop the most recent user message we just persisted (it's already last in `prior`),
    # since the agent expects it as the live `message` arg.
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == payload.content:
        prior = prior[:-1]

    rendered = render_user_message(payload.content, payload.references)

    run = await AgentService.run_agent(
        db,
        current_user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=await _build_thread_context_hint(db, thread),
    )

    cards = _agent_run_to_attachments(run)
    # When the agent loop already produced a structured error card
    # (provider_error / key_decrypt_error), don't *also* dump `run.error` text
    # into the message bubble or the top-of-thread banner — the card already
    # shows message + actionable hint + a CTA, and duplicating it just clutters
    # the conversation. Any partial assistant_reply produced before the failure
    # is still rendered (preserving useful context).
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    if run.assistant_reply:
        assistant_text = run.assistant_reply
    elif has_error_card:
        assistant_text = ""
    else:
        assistant_text = run.error or ""

    asst_msg = await append_message(
        db,
        thread,
        role="assistant" if run.status == "completed" else "system",
        content=assistant_text,
        attachments=cards or None,
        agent_run_id=run.id,
    )
    await db.commit()
    await db.refresh(asst_msg)
    await db.refresh(thread)

    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(asst_msg),
        error=run.error if (run.status != "completed" and not has_error_card) else None,
    )
