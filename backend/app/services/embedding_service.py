from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.rag_index_service import RagIndexService
from app.services.user_ai_settings_service import UserAISettingsService


class EmbeddingService:
    @staticmethod
    async def _user(db: AsyncSession, user_id: int | None) -> User | None:
        if not user_id:
            return None
        return await db.get(User, user_id)

    @staticmethod
    async def sync_contact(db: AsyncSession, user_id: int | None, contact_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "contact", contact_id)
            result = await db.execute(select(Contact).where(Contact.id == contact_id))
            contact = result.scalar_one_or_none()
            if contact:
                contact.embedding = None
                contact.embedding_model = None
                contact.embedding_updated_at = None
            return
        result = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if not contact:
            return
        mean_vec = await RagIndexService.reindex_contact(db, user_id, contact_id)
        if mean_vec:
            contact.embedding = mean_vec
            contact.embedding_model = settings_row.embedding_model
            contact.embedding_updated_at = datetime.now(UTC)
        else:
            contact.embedding = None
            contact.embedding_model = None
            contact.embedding_updated_at = None

    @staticmethod
    async def sync_email(db: AsyncSession, user_id: int | None, email_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "email", email_id)
            result = await db.execute(select(Email).where(Email.id == email_id))
            email = result.scalar_one_or_none()
            if email:
                email.embedding = None
                email.embedding_model = None
                email.embedding_updated_at = None
            return
        result = await db.execute(select(Email).where(Email.id == email_id))
        email = result.scalar_one_or_none()
        if not email:
            return
        mean_vec = await RagIndexService.reindex_email(db, user_id, email_id)
        if mean_vec:
            email.embedding = mean_vec
            email.embedding_model = settings_row.embedding_model
            email.embedding_updated_at = datetime.now(UTC)
        else:
            email.embedding = None
            email.embedding_model = None
            email.embedding_updated_at = None

    @staticmethod
    async def sync_deal(db: AsyncSession, user_id: int | None, deal_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "deal", deal_id)
            result = await db.execute(select(Deal).where(Deal.id == deal_id))
            deal = result.scalar_one_or_none()
            if deal:
                deal.embedding = None
                deal.embedding_model = None
                deal.embedding_updated_at = None
            return
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        mean_vec = await RagIndexService.reindex_deal(db, user_id, deal_id)
        if mean_vec:
            deal.embedding = mean_vec
            deal.embedding_model = settings_row.embedding_model
            deal.embedding_updated_at = datetime.now(UTC)
        else:
            deal.embedding = None
            deal.embedding_model = None
            deal.embedding_updated_at = None

    @staticmethod
    async def sync_event(db: AsyncSession, user_id: int | None, event_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "event", event_id)
            result = await db.execute(select(Event).where(Event.id == event_id))
            event = result.scalar_one_or_none()
            if event:
                event.embedding = None
                event.embedding_model = None
                event.embedding_updated_at = None
            return
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            return
        mean_vec = await RagIndexService.reindex_event(db, user_id, event_id)
        if mean_vec:
            event.embedding = mean_vec
            event.embedding_model = settings_row.embedding_model
            event.embedding_updated_at = datetime.now(UTC)
        else:
            event.embedding = None
            event.embedding_model = None
            event.embedding_updated_at = None
