from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService


class ContactService:
    @staticmethod
    async def list_contacts(db: AsyncSession) -> list[Contact]:
        result = await db.execute(select(Contact).order_by(Contact.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_contact(db: AsyncSession, contact_id: int) -> Contact:
        result = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if not contact:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
        return contact

    @staticmethod
    async def create_contact(db: AsyncSession, payload: ContactCreate, user_id: int | None = None) -> Contact:
        contact = Contact(**payload.model_dump())
        db.add(contact)
        await db.flush()
        await create_audit_log(db, "contact", contact.id, "created", payload.model_dump(), user_id)
        await EmbeddingService.sync_contact(db, user_id, contact.id)
        await db.commit()
        await db.refresh(contact)
        return contact

    @staticmethod
    async def update_contact(
        db: AsyncSession, contact_id: int, payload: ContactUpdate, user_id: int | None = None
    ) -> Contact:
        contact = await ContactService.get_contact(db, contact_id)
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(contact, key, value)
        await create_audit_log(db, "contact", contact.id, "updated", updates, user_id)
        await EmbeddingService.sync_contact(db, user_id, contact.id)
        await db.commit()
        await db.refresh(contact)
        return contact

    @staticmethod
    async def delete_contact(db: AsyncSession, contact_id: int, user_id: int | None = None) -> None:
        contact = await ContactService.get_contact(db, contact_id)
        await create_audit_log(db, "contact", contact.id, "deleted", None, user_id)
        await db.delete(contact)
        await db.commit()
