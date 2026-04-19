from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.chat import StartChatResponse
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services.chat_service import start_entity_chat
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


@router.post("/{contact_id}/start-chat", response_model=StartChatResponse)
async def start_chat_from_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartChatResponse:
    """Create (or reuse) an entity-bound chat thread for this contact and seed it with
    a single ``event`` announcement describing the contact. Mirrors
    ``POST /emails/{id}/start-chat`` — the agent does NOT run automatically.
    """
    contact = await ContactService.get_contact(db, contact_id)

    title = f"Contacto · {contact.name}"[:255]
    detail_bits = [
        f"Email: {contact.email}" if contact.email else None,
        f"Teléfono: {contact.phone}" if contact.phone else None,
        f"Rol: {contact.role}" if contact.role and contact.role != "other" else None,
    ]
    details = " · ".join(b for b in detail_bits if b)
    announcement = (
        f"👤 Contacto referenciado\n"
        f"Nombre: {contact.name}\n"
        f"{details}\n\n"
        f"{(contact.notes or '')[:600]}"
    )
    thread = await start_entity_chat(
        db,
        current_user,
        entity_type="contact",
        entity_id=contact.id,
        title=title,
        announcement=announcement,
        event_attachments=[{"event_kind": "contact_referenced", "contact_id": contact.id}],
    )
    await db.commit()
    return StartChatResponse(thread_id=thread.id)
