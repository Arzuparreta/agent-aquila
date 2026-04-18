from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services.contact_service import ContactService

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ContactRead])
async def list_contacts(db: AsyncSession = Depends(get_db)) -> list[ContactRead]:
    contacts = await ContactService.list_contacts(db)
    return [ContactRead.model_validate(contact) for contact in contacts]


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ContactRead:
    contact = await ContactService.create_contact(db, payload, current_user.id)
    return ContactRead.model_validate(contact)


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> ContactRead:
    contact = await ContactService.get_contact(db, contact_id)
    return ContactRead.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactRead:
    contact = await ContactService.update_contact(db, contact_id, payload, current_user.id)
    return ContactRead.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_contact(
    contact_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    await ContactService.delete_contact(db, contact_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
