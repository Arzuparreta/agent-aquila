from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.schemas.ai import EmailDraftResponse
from app.schemas.email import (
    EmailCreate,
    EmailRead,
    EmailReadStateUpdate,
    StartChatResponse,
    UnreadCountResponse,
)
from app.services.chat_service import append_message, get_or_create_entity_thread
from app.services.email_service import EmailService
from app.services.inbound_filter_service import (
    CATEGORY_ACTIONABLE,
    CATEGORY_NOISE,
    SOURCE_MANUAL,
    InboundFilterService,
    Verdict,
)

router = APIRouter(prefix="/emails", tags=["emails"], dependencies=[Depends(get_current_user)])


TriageQuery = Literal["actionable", "informational", "noise"]


@router.get("", response_model=list[EmailRead])
async def list_emails(
    triage: TriageQuery | None = Query(default=None),
    read: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[EmailRead]:
    emails = await EmailService.list_emails(db, triage=triage, read=read)
    return [EmailRead.model_validate(email) for email in emails]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(db: AsyncSession = Depends(get_db)) -> UnreadCountResponse:
    return UnreadCountResponse(count=await EmailService.count_unread(db))


@router.post("", response_model=EmailRead, status_code=status.HTTP_201_CREATED)
async def create_email(
    payload: EmailCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EmailRead:
    email = await EmailService.ingest_email(db, payload, current_user.id)
    return EmailRead.model_validate(email)


@router.post("/{email_id}/draft", response_model=EmailDraftResponse)
async def draft_email(
    email_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EmailDraftResponse:
    return await EmailService.draft_reply(db, email_id, current_user)


@router.get("/{email_id}", response_model=EmailRead)
async def get_email(email_id: int, db: AsyncSession = Depends(get_db)) -> EmailRead:
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return EmailRead.model_validate(email)


@router.patch("/{email_id}/read", response_model=EmailRead)
async def set_email_read_state(
    email_id: int,
    payload: EmailReadStateUpdate,
    db: AsyncSession = Depends(get_db),
) -> EmailRead:
    """Toggle the per-email ``is_read`` flag. Used by the Inbox UI when a row is opened
    (mark read) or when the user explicitly marks something unread.
    """
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    email.is_read = bool(payload.is_read)
    await db.commit()
    await db.refresh(email)
    return EmailRead.model_validate(email)


@router.post("/{email_id}/start-chat", response_model=StartChatResponse)
async def start_chat_from_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartChatResponse:
    """Create (or reuse) an entity-bound chat thread for this email and seed it with
    a single ``event`` announcement message describing the email. The agent does NOT
    run automatically — the user types the first prompt themselves.
    """
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

    sender = email.sender_name or email.sender_email or "Remitente desconocido"
    title = f"Correo · {sender}"[:255]
    thread = await get_or_create_entity_thread(
        db, current_user, entity_type="email", entity_id=email.id, title=title
    )

    # Only seed the announcement once (idempotent on repeat clicks).
    from app.models.chat_message import ChatMessage
    res = await db.execute(
        select(ChatMessage.id).where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.role == "event",
        ).limit(1)
    )
    already_seeded = res.scalar_one_or_none() is not None

    if not already_seeded:
        announcement = (
            f"📩 Correo referenciado\n"
            f"De: {email.sender_name or ''} <{email.sender_email or ''}>\n"
            f"Asunto: {email.subject or ''}\n\n"
            f"{(email.snippet or email.body or '')[:600]}"
        )
        await append_message(
            db, thread, role="event", content=announcement,
            attachments=[{"event_kind": "email_referenced", "email_id": email.id}],
        )

    # Unarchive if the user is reopening it.
    if thread.archived:
        thread.archived = False
        thread.updated_at = datetime.now(UTC)

    await db.commit()
    return StartChatResponse(thread_id=thread.id)


@router.post("/{email_id}/promote", response_model=EmailRead)
async def promote_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailRead:
    """Re-classify a silenced inbound email as ``actionable``. Does NOT create a chat
    thread or run the agent — the user can hit "Iniciar chat sobre este correo" if
    they want one.
    """
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    InboundFilterService.apply_verdict_to_email(
        email,
        Verdict(category=CATEGORY_ACTIONABLE, reason="promoted by user", source=SOURCE_MANUAL),
    )
    await db.commit()
    await db.refresh(email)
    return EmailRead.model_validate(email)


@router.post("/{email_id}/suppress", response_model=EmailRead)
async def suppress_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailRead:
    """Mark an email as ``noise``. If a chat thread exists for it (or for its
    contact via this email), archive it so it disappears from Conversaciones."""
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    InboundFilterService.apply_verdict_to_email(
        email,
        Verdict(category=CATEGORY_NOISE, reason="suppressed by user", source=SOURCE_MANUAL),
    )
    archive_targets = [("email", email.id)]
    if email.contact_id:
        archive_targets.append(("contact", email.contact_id))
    for entity_type, entity_id in archive_targets:
        res = await db.execute(
            select(ChatThread).where(
                ChatThread.user_id == current_user.id,
                ChatThread.entity_type == entity_type,
                ChatThread.entity_id == entity_id,
            )
        )
        thread = res.scalar_one_or_none()
        if thread and not thread.archived:
            thread.archived = True
            thread.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(email)
    return EmailRead.model_validate(email)
