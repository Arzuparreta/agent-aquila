from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService
from app.services.rag_index_service import RagIndexService


class EventService:
    @staticmethod
    async def list_events(db: AsyncSession) -> list[Event]:
        result = await db.execute(select(Event).order_by(Event.event_date.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_event(db: AsyncSession, event_id: int) -> Event:
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
        return event

    @staticmethod
    async def create_event(db: AsyncSession, payload: EventCreate, user_id: int | None = None) -> Event:
        event = Event(**payload.model_dump())
        db.add(event)
        await db.flush()
        await create_audit_log(db, "event", event.id, "created", payload.model_dump(mode="json"), user_id)
        await EmbeddingService.sync_event(db, user_id, event.id)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def update_event(db: AsyncSession, event_id: int, payload: EventUpdate, user_id: int | None = None) -> Event:
        event = await EventService.get_event(db, event_id)
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(event, key, value)
        await create_audit_log(db, "event", event.id, "updated", payload.model_dump(mode="json", exclude_unset=True), user_id)
        await EmbeddingService.sync_event(db, user_id, event.id)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def delete_event(db: AsyncSession, event_id: int, user_id: int | None = None) -> None:
        event = await EventService.get_event(db, event_id)
        await create_audit_log(db, "event", event.id, "deleted", None, user_id)
        await RagIndexService.delete_entity_chunks(db, "event", event_id)
        await db.delete(event)
        await db.commit()
