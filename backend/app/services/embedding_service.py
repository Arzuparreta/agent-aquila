from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.embedding_client import EmbeddingClient
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)


def pad_embedding(vec: list[float]) -> list[float]:
    dim = settings.embedding_dimensions
    if len(vec) >= dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


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
            return
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            return
        result = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if not contact:
            return
        text = f"{contact.name}\n{contact.role}\n{contact.email or ''}\n{contact.notes or ''}".strip()
        try:
            vectors = await EmbeddingClient.embed_texts(api_key, settings_row, [text])
        except Exception as exc:
            logger.warning("contact embedding failed id=%s: %s", contact_id, exc)
            return
        contact.embedding = pad_embedding(vectors[0])
        contact.embedding_model = settings_row.embedding_model
        contact.embedding_updated_at = datetime.now(UTC)

    @staticmethod
    async def sync_email(db: AsyncSession, user_id: int | None, email_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            return
        result = await db.execute(select(Email).where(Email.id == email_id))
        email = result.scalar_one_or_none()
        if not email:
            return
        text = f"{email.subject}\n{email.body}".strip()
        try:
            vectors = await EmbeddingClient.embed_texts(api_key, settings_row, [text[:8000]])
        except Exception as exc:
            logger.warning("email embedding failed id=%s: %s", email_id, exc)
            return
        email.embedding = pad_embedding(vectors[0])
        email.embedding_model = settings_row.embedding_model
        email.embedding_updated_at = datetime.now(UTC)

    @staticmethod
    async def sync_deal(db: AsyncSession, user_id: int | None, deal_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            return
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        text = f"{deal.title}\n{deal.status}\n{deal.notes or ''}".strip()
        try:
            vectors = await EmbeddingClient.embed_texts(api_key, settings_row, [text])
        except Exception as exc:
            logger.warning("deal embedding failed id=%s: %s", deal_id, exc)
            return
        deal.embedding = pad_embedding(vectors[0])
        deal.embedding_model = settings_row.embedding_model
        deal.embedding_updated_at = datetime.now(UTC)

    @staticmethod
    async def sync_event(db: AsyncSession, user_id: int | None, event_id: int) -> None:
        user = await EmbeddingService._user(db, user_id)
        if not user:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            return
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            return
        text = f"{event.venue_name}\n{event.event_date.isoformat()}\n{event.city or ''}\n{event.status}\n{event.notes or ''}".strip()
        try:
            vectors = await EmbeddingClient.embed_texts(api_key, settings_row, [text])
        except Exception as exc:
            logger.warning("event embedding failed id=%s: %s", event_id, exc)
            return
        event.embedding = pad_embedding(vectors[0])
        event.embedding_model = settings_row.embedding_model
        event.embedding_updated_at = datetime.now(UTC)
