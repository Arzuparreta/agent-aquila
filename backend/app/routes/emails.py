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
from app.schemas.email import EmailCreate, EmailRead
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
    db: AsyncSession = Depends(get_db),
) -> list[EmailRead]:
    emails = await EmailService.list_emails(db, triage=triage)
    return [EmailRead.model_validate(email) for email in emails]


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


@router.post("/{email_id}/promote", response_model=EmailRead)
async def promote_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailRead:
    """Re-classify a silenced inbound email as ``actionable`` and run the
    proactive layer (thread + agent + push). Used from the FE when the artist
    wants to bring a previously-filtered message into a chat retroactively.
    """
    email = await EmailService.get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    InboundFilterService.apply_verdict_to_email(
        email,
        Verdict(category=CATEGORY_ACTIONABLE, reason="promoted by user", source=SOURCE_MANUAL),
    )
    await db.flush()
    # Defer import to avoid pulling agent_service into route module load.
    from app.services.proactive_service import notify_email_received

    try:
        await notify_email_received(db, current_user, email)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proactive run failed: {exc}",
        ) from exc
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
    # Archive the entity-bound thread, if any. Both the per-email and the
    # per-contact thread shapes that ``proactive_service`` may have created.
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
