from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.user import User
from app.schemas.ai import EmailDraftResponse
from app.schemas.email import EmailCreate
from app.core.config import settings
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService
from app.services.llm_client import LLMClient
from app.services.triage_service import TriageService
from app.services.user_ai_settings_service import UserAISettingsService


class EmailService:
    @staticmethod
    async def list_emails(
        db: AsyncSession, *, triage: str | None = None, read: bool | None = None
    ) -> list[Email]:
        stmt = select(Email)
        if triage:
            stmt = stmt.where(Email.triage_category == triage)
        if read is not None:
            stmt = stmt.where(Email.is_read.is_(read))
        stmt = stmt.order_by(Email.received_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_unread(db: AsyncSession) -> int:
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(Email.id)).where(Email.is_read.is_(False))
        )
        return int(result.scalar() or 0)

    @staticmethod
    async def get_email(db: AsyncSession, email_id: int) -> Email | None:
        result = await db.execute(select(Email).where(Email.id == email_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def ingest_email(db: AsyncSession, payload: EmailCreate, user_id: int | None = None) -> Email:
        contact = await EmailService._resolve_contact(db, payload)

        email = Email(
            contact_id=contact.id if contact else payload.contact_id,
            sender_email=str(payload.sender_email),
            sender_name=payload.sender_name,
            subject=payload.subject,
            body=payload.body,
            received_at=payload.received_at,
            raw_headers=payload.raw_headers,
        )
        db.add(email)
        await db.flush()
        await create_audit_log(db, "email", email.id, "created", payload.model_dump(mode="json"), user_id)

        if contact:
            triage = await TriageService.evaluate(db, user_id, email.subject, email.body)
            await create_audit_log(db, "email", email.id, "ai_triage", triage, user_id)
            await EmailService._apply_ingestion_rules(db, email, contact.id, user_id, triage)
            await EmbeddingService.sync_contact(db, user_id, contact.id)

        await EmbeddingService.sync_email(db, user_id, email.id)
        await db.commit()
        await db.refresh(email)
        return email

    @staticmethod
    async def _resolve_contact(db: AsyncSession, payload: EmailCreate) -> Contact | None:
        if payload.contact_id:
            result = await db.execute(select(Contact).where(Contact.id == payload.contact_id))
            return result.scalar_one_or_none()

        result = await db.execute(select(Contact).where(Contact.email == str(payload.sender_email)))
        contact = result.scalar_one_or_none()
        if contact:
            return contact

        if not payload.sender_email:
            return None

        contact = Contact(
            name=payload.sender_name or str(payload.sender_email),
            email=str(payload.sender_email),
            role="other",
        )
        db.add(contact)
        await db.flush()
        await create_audit_log(
            db,
            "contact",
            contact.id,
            "created_from_email",
            {"sender_email": str(payload.sender_email), "sender_name": payload.sender_name},
            None,
        )
        return contact

    @staticmethod
    async def _apply_ingestion_rules(
        db: AsyncSession, email: Email, contact_id: int, user_id: int | None, triage: dict
    ) -> None:
        if not settings.email_ingest_auto_create_deals:
            return
        if not triage.get("create_deal"):
            return

        status = str(triage.get("suggested_status") or "new")
        if status not in ("new", "contacted", "negotiating", "won", "lost"):
            status = "new"

        title = email.subject[:255] if len(email.subject) > 255 else email.subject
        deal = Deal(contact_id=contact_id, title=title, status=status)
        db.add(deal)
        await db.flush()
        await create_audit_log(
            db,
            "deal",
            deal.id,
            "created_from_email_rule",
            {"subject": email.subject, "contact_id": contact_id, "triage": triage},
            user_id,
        )
        await EmbeddingService.sync_deal(db, user_id, deal.id)

    @staticmethod
    async def draft_reply(db: AsyncSession, email_id: int, user: User) -> EmailDraftResponse:
        email = await EmailService.get_email(db, email_id)
        if not email:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AI is disabled for this user")
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key not configured")

        history_lines: list[str] = []
        if email.contact_id:
            result = await db.execute(
                select(Email)
                .where(Email.contact_id == email.contact_id)
                .order_by(Email.received_at.desc())
                .limit(12)
            )
            for row in result.scalars().all():
                history_lines.append(f"- {row.received_at.isoformat()} | {row.subject} | {row.body[:400]}")
        history = "\n".join(history_lines) if history_lines else "(no thread context)"

        system = (
            "You help an artist manager reply professionally and briefly. "
            "Output only the email body text, no subject line."
        )
        user_msg = (
            f"Draft a reply to this message.\n\n"
            f"Subject: {email.subject}\nFrom: {email.sender_name or ''} <{email.sender_email}>\n\n"
            f"{email.body}\n\nRecent thread (newest first):\n{history}"
        )
        draft = await LLMClient.chat_completion(
            api_key or "",
            settings_row,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.4,
        )
        await create_audit_log(
            db,
            "email",
            email.id,
            "ai_draft_generated",
            {"model": settings_row.chat_model},
            user.id,
        )
        await db.commit()
        return EmailDraftResponse(draft=draft.strip(), model=settings_row.chat_model)
