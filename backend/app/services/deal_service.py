from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal import Deal
from app.schemas.deal import DealCreate, DealUpdate
from app.services.audit_service import create_audit_log
from app.services.embedding_service import EmbeddingService
from app.services.rag_index_service import RagIndexService


class DealService:
    @staticmethod
    async def list_deals(db: AsyncSession) -> list[Deal]:
        result = await db.execute(select(Deal).order_by(Deal.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def list_active_deals(db: AsyncSession) -> list[Deal]:
        result = await db.execute(
            select(Deal).where(Deal.status.in_(["new", "contacted", "negotiating"])).order_by(Deal.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_deal(db: AsyncSession, deal_id: int) -> Deal:
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        return deal

    @staticmethod
    async def create_deal(
        db: AsyncSession, payload: DealCreate, user_id: int | None = None, *, commit: bool = True
    ) -> Deal:
        deal = Deal(**payload.model_dump())
        db.add(deal)
        await db.flush()
        await create_audit_log(db, "deal", deal.id, "created", payload.model_dump(mode="json"), user_id)
        await EmbeddingService.sync_deal(db, user_id, deal.id)
        if commit:
            await db.commit()
            await db.refresh(deal)
        else:
            await db.flush()
            await db.refresh(deal)
        return deal

    @staticmethod
    async def update_deal(
        db: AsyncSession,
        deal_id: int,
        payload: DealUpdate,
        user_id: int | None = None,
        *,
        commit: bool = True,
    ) -> Deal:
        deal = await DealService.get_deal(db, deal_id)
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(deal, key, value)
        await create_audit_log(db, "deal", deal.id, "updated", payload.model_dump(mode="json", exclude_unset=True), user_id)
        await EmbeddingService.sync_deal(db, user_id, deal.id)
        if commit:
            await db.commit()
            await db.refresh(deal)
        else:
            await db.flush()
            await db.refresh(deal)
        return deal

    @staticmethod
    async def delete_deal(db: AsyncSession, deal_id: int, user_id: int | None = None) -> None:
        deal = await DealService.get_deal(db, deal_id)
        await create_audit_log(db, "deal", deal.id, "deleted", None, user_id)
        await RagIndexService.delete_deal_subtree(db, deal_id)
        await db.delete(deal)
        await db.commit()
