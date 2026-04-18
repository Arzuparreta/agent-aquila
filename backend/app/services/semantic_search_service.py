from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.schemas.ai import SemanticSearchHit
from app.services.embedding_client import EmbeddingClient
from app.services.embedding_service import pad_embedding
from app.services.user_ai_settings_service import UserAISettingsService


def _snippet(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1]}…"


class SemanticSearchService:
    @staticmethod
    async def search(db: AsyncSession, user: User, query: str, limit_per_type: int) -> list[SemanticSearchHit]:
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return []
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            return []
        q_raw = (await EmbeddingClient.embed_texts(api_key, settings_row, [query]))[0]
        qvec = pad_embedding(q_raw)

        hits: list[SemanticSearchHit] = []

        contact_stmt = (
            select(Contact.id, Contact.name, Contact.notes, Contact.embedding.cosine_distance(qvec).label("dist"))
            .where(Contact.embedding.is_not(None))
            .order_by(Contact.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(contact_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="contact",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.name,
                    snippet=_snippet(row.notes),
                    citation=f"contact:{row.id}",
                )
            )

        email_stmt = (
            select(Email.id, Email.subject, Email.body, Email.embedding.cosine_distance(qvec).label("dist"))
            .where(Email.embedding.is_not(None))
            .order_by(Email.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(email_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="email",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.subject,
                    snippet=_snippet(row.body),
                    citation=f"email:{row.id}",
                )
            )

        deal_stmt = (
            select(Deal.id, Deal.title, Deal.notes, Deal.embedding.cosine_distance(qvec).label("dist"))
            .where(Deal.embedding.is_not(None))
            .order_by(Deal.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(deal_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="deal",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.title,
                    snippet=_snippet(row.notes),
                    citation=f"deal:{row.id}",
                )
            )

        event_stmt = (
            select(Event.id, Event.venue_name, Event.notes, Event.embedding.cosine_distance(qvec).label("dist"))
            .where(Event.embedding.is_not(None))
            .order_by(Event.embedding.cosine_distance(qvec))
            .limit(limit_per_type)
        )
        result = await db.execute(event_stmt)
        for row in result.all():
            dist = float(row.dist)
            hits.append(
                SemanticSearchHit(
                    entity_type="event",
                    entity_id=int(row.id),
                    score=max(0.0, 1.0 - dist),
                    title=row.venue_name,
                    snippet=_snippet(row.notes),
                    citation=f"event:{row.id}",
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: limit_per_type * 4]
