from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.schemas.chat import StartChatResponse
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.services.chat_service import start_entity_chat
from app.services.event_service import EventService
from app.services.inbound_filter_service import (
    CATEGORY_ACTIONABLE,
    CATEGORY_NOISE,
    SOURCE_MANUAL,
    InboundFilterService,
    Verdict,
)

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])


TriageQuery = Literal["actionable", "informational", "noise"]


@router.get("", response_model=list[EventRead])
async def list_events(
    triage: TriageQuery | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[EventRead]:
    events = await EventService.list_events(db, triage=triage)
    return [EventRead.model_validate(event) for event in events]


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EventRead:
    event = await EventService.create_event(db, payload, current_user.id)
    return EventRead.model_validate(event)


@router.get("/{event_id}", response_model=EventRead)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)) -> EventRead:
    event = await EventService.get_event(db, event_id)
    return EventRead.model_validate(event)


@router.patch("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: int,
    payload: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventRead:
    event = await EventService.update_event(db, event_id, payload, current_user.id)
    return EventRead.model_validate(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_event(
    event_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    await EventService.delete_event(db, event_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{event_id}/promote", response_model=EventRead)
async def promote_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventRead:
    """Re-classify an event as ``actionable``. Does NOT create a chat thread or run
    the agent — the proactive layer is push-only now (see ``proactive_service``).
    """
    del current_user  # accepted via dependency for auth, no per-user side effects
    event = await EventService.get_event(db, event_id)
    InboundFilterService.apply_verdict_to_event(
        event,
        Verdict(category=CATEGORY_ACTIONABLE, reason="promoted by user", source=SOURCE_MANUAL),
    )
    await db.commit()
    await db.refresh(event)
    return EventRead.model_validate(event)


@router.post("/{event_id}/start-chat", response_model=StartChatResponse)
async def start_chat_from_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartChatResponse:
    """Create (or reuse) an entity-bound chat thread for this event and seed it with
    a single ``event`` announcement. Mirrors ``POST /emails/{id}/start-chat``.
    """
    event = await EventService.get_event(db, event_id)

    title = f"Evento · {event.venue_name}"[:255]
    when = event.event_date.isoformat() if event.event_date else None
    detail_bits = [
        f"Fecha: {when}" if when else None,
        f"Ciudad: {event.city}" if event.city else None,
        f"Recinto: {event.venue_name}" if event.venue_name else None,
        f"Estado: {event.status}" if event.status else None,
    ]
    details = " · ".join(b for b in detail_bits if b)
    body = event.notes or event.description or event.summary or ""
    announcement = (
        f"🎤 Evento referenciado\n"
        f"{event.venue_name}\n"
        f"{details}\n\n"
        f"{body[:600]}"
    )
    thread = await start_entity_chat(
        db,
        current_user,
        entity_type="event",
        entity_id=event.id,
        title=title,
        announcement=announcement,
        event_attachments=[{"event_kind": "event_referenced", "event_id": event.id}],
    )
    await db.commit()
    return StartChatResponse(thread_id=thread.id)


@router.post("/{event_id}/suppress", response_model=EventRead)
async def suppress_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventRead:
    event = await EventService.get_event(db, event_id)
    InboundFilterService.apply_verdict_to_event(
        event,
        Verdict(category=CATEGORY_NOISE, reason="suppressed by user", source=SOURCE_MANUAL),
    )
    res = await db.execute(
        select(ChatThread).where(
            ChatThread.user_id == current_user.id,
            ChatThread.entity_type == "event",
            ChatThread.entity_id == event.id,
        )
    )
    thread = res.scalar_one_or_none()
    if thread and not thread.archived:
        thread.archived = True
        thread.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(event)
    return EventRead.model_validate(event)
