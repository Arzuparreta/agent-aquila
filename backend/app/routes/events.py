from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[EventRead])
async def list_events(db: AsyncSession = Depends(get_db)) -> list[EventRead]:
    events = await EventService.list_events(db)
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
