from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.rag_chunk import RagChunk
from app.models.user import User
from app.services.chunking import split_into_chunks
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.embedding_client import EmbeddingClient
from app.services.embedding_vector import pad_embedding
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

EMBED_BATCH = 24


def mean_padded_vectors(vectors: list[list[float]], dim: int) -> list[float]:
    if not vectors:
        return [0.0] * dim
    n = len(vectors)
    out = [sum(v[i] for v in vectors) / n for i in range(dim)]
    return out


class RagIndexService:
    @staticmethod
    async def delete_entity_chunks(db: AsyncSession, entity_type: str, entity_id: int) -> None:
        await db.execute(delete(RagChunk).where(RagChunk.entity_type == entity_type, RagChunk.entity_id == entity_id))

    @staticmethod
    async def delete_contact_subtree(db: AsyncSession, contact_id: int) -> None:
        er = await db.execute(select(Email.id).where(Email.contact_id == contact_id))
        for (eid,) in er.all():
            await RagIndexService.delete_entity_chunks(db, "email", int(eid))

        dr = await db.execute(select(Deal.id).where(Deal.contact_id == contact_id))
        deal_ids = [int(did) for (did,) in dr.all()]
        for deal_id in deal_ids:
            evr = await db.execute(select(Event.id).where(Event.deal_id == deal_id))
            for (evid,) in evr.all():
                await RagIndexService.delete_entity_chunks(db, "event", int(evid))
            await RagIndexService.delete_entity_chunks(db, "deal", deal_id)

        await RagIndexService.delete_entity_chunks(db, "contact", contact_id)

    @staticmethod
    async def delete_deal_subtree(db: AsyncSession, deal_id: int) -> None:
        evr = await db.execute(select(Event.id).where(Event.deal_id == deal_id))
        for (evid,) in evr.all():
            await RagIndexService.delete_entity_chunks(db, "event", int(evid))
        await RagIndexService.delete_entity_chunks(db, "deal", deal_id)

    @staticmethod
    def _contact_doc(contact: Contact) -> str:
        lines = [
            "ENTITY: CONTACT",
            f"Name: {contact.name}",
            f"Role: {contact.role}",
        ]
        if contact.email:
            lines.append(f"Email: {contact.email}")
        if contact.phone:
            lines.append(f"Phone: {contact.phone}")
        if contact.notes:
            lines.append(f"Notes:\n{contact.notes}")
        return "\n".join(lines).strip()

    @staticmethod
    def _email_doc(email: Email) -> str:
        lines = [
            "ENTITY: EMAIL",
            f"Subject: {email.subject}",
            f"From: {email.sender_name or ''} <{email.sender_email}>",
            f"Received: {email.received_at.isoformat()}",
        ]
        if email.contact_id:
            lines.append(f"Linked_contact_id: {email.contact_id}")
        lines.append(f"Body:\n{email.body}")
        return "\n".join(lines).strip()

    @staticmethod
    def _deal_doc(deal: Deal, contact_name: str | None) -> str:
        lines = [
            "ENTITY: DEAL",
            f"Title: {deal.title}",
            f"Status: {deal.status}",
            f"Contact: {contact_name or ''} (contact_id={deal.contact_id})",
        ]
        if deal.amount is not None:
            lines.append(f"Amount: {deal.amount} {deal.currency or ''}".strip())
        if deal.notes:
            lines.append(f"Notes:\n{deal.notes}")
        return "\n".join(lines).strip()

    @staticmethod
    def _event_doc(event: Event) -> str:
        lines = [
            "ENTITY: EVENT",
            f"Venue: {event.venue_name}",
            f"Date: {event.event_date.isoformat()}",
            f"City: {event.city or ''}",
            f"Status: {event.status}",
        ]
        if event.deal_id:
            lines.append(f"Linked_deal_id: {event.deal_id}")
        if event.notes:
            lines.append(f"Notes:\n{event.notes}")
        return "\n".join(lines).strip()

    @staticmethod
    async def _replace_chunks(
        db: AsyncSession,
        *,
        entity_type: str,
        entity_id: int,
        document: str,
        api_key: str,
        settings_row: Any,
        metadata_base: dict[str, Any] | None = None,
    ) -> list[float] | None:
        await RagIndexService.delete_entity_chunks(db, entity_type, entity_id)
        chunks = split_into_chunks(document)
        if not chunks:
            return None

        now = datetime.now(UTC)
        all_vectors: list[list[float]] = []
        try:
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[i : i + EMBED_BATCH]
                raw = await EmbeddingClient.embed_texts(api_key, settings_row, batch)
                all_vectors.extend(pad_embedding(v) for v in raw)
        except Exception as exc:
            logger.warning("chunk embed failed %s:%s: %s", entity_type, entity_id, exc)
            return None

        mean_vec = pad_embedding(mean_padded_vectors(all_vectors, len(all_vectors[0])))
        rows: list[RagChunk] = []
        for idx, (content, vec) in enumerate(zip(chunks, all_vectors, strict=True)):
            meta = {**(metadata_base or {}), "chunk_of": len(chunks)}
            rows.append(
                RagChunk(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    chunk_index=idx,
                    content=content,
                    embedding=vec,
                    embedding_model=settings_row.embedding_model,
                    embedding_updated_at=now,
                    metadata_=meta,
                )
            )
        db.add_all(rows)
        return list(mean_vec)

    @staticmethod
    async def reindex_contact(db: AsyncSession, user_id: int | None, contact_id: int) -> list[float] | None:
        user = await db.get(User, user_id) if user_id else None
        if not user:
            return None
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "contact", contact_id)
            return None
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            await RagIndexService.delete_entity_chunks(db, "contact", contact_id)
            return None
        result = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if not contact:
            return None
        doc = RagIndexService._contact_doc(contact)
        return await RagIndexService._replace_chunks(
            db,
            entity_type="contact",
            entity_id=contact_id,
            document=doc,
            api_key=api_key or "",
            settings_row=settings_row,
            metadata_base={"name": contact.name, "role": contact.role},
        )

    @staticmethod
    async def reindex_email(db: AsyncSession, user_id: int | None, email_id: int) -> list[float] | None:
        user = await db.get(User, user_id) if user_id else None
        if not user:
            return None
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "email", email_id)
            return None
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            await RagIndexService.delete_entity_chunks(db, "email", email_id)
            return None
        result = await db.execute(select(Email).where(Email.id == email_id))
        email = result.scalar_one_or_none()
        if not email:
            return None
        doc = RagIndexService._email_doc(email)
        return await RagIndexService._replace_chunks(
            db,
            entity_type="email",
            entity_id=email_id,
            document=doc,
            api_key=api_key or "",
            settings_row=settings_row,
            metadata_base={"subject": email.subject},
        )

    @staticmethod
    async def reindex_deal(db: AsyncSession, user_id: int | None, deal_id: int) -> list[float] | None:
        user = await db.get(User, user_id) if user_id else None
        if not user:
            return None
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "deal", deal_id)
            return None
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            await RagIndexService.delete_entity_chunks(db, "deal", deal_id)
            return None
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return None
        contact_name: str | None = None
        if deal.contact_id:
            c = await db.get(Contact, deal.contact_id)
            contact_name = c.name if c else None
        doc = RagIndexService._deal_doc(deal, contact_name)
        return await RagIndexService._replace_chunks(
            db,
            entity_type="deal",
            entity_id=deal_id,
            document=doc,
            api_key=api_key or "",
            settings_row=settings_row,
            metadata_base={"title": deal.title, "status": deal.status},
        )

    @staticmethod
    async def reindex_event(db: AsyncSession, user_id: int | None, event_id: int) -> list[float] | None:
        user = await db.get(User, user_id) if user_id else None
        if not user:
            return None
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            await RagIndexService.delete_entity_chunks(db, "event", event_id)
            return None
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            await RagIndexService.delete_entity_chunks(db, "event", event_id)
            return None
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            return None
        doc = RagIndexService._event_doc(event)
        return await RagIndexService._replace_chunks(
            db,
            entity_type="event",
            entity_id=event_id,
            document=doc,
            api_key=api_key or "",
            settings_row=settings_row,
            metadata_base={"venue": event.venue_name, "event_date": event.event_date.isoformat()},
        )
