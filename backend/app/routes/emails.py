from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.ai import EmailDraftResponse
from app.schemas.email import EmailCreate, EmailRead
from app.services.email_service import EmailService

router = APIRouter(prefix="/emails", tags=["emails"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[EmailRead])
async def list_emails(db: AsyncSession = Depends(get_db)) -> list[EmailRead]:
    emails = await EmailService.list_emails(db)
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
