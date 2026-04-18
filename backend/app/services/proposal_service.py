from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import PendingProposalRead
from app.schemas.deal import DealCreate
from app.services.deal_service import DealService


def proposal_to_read(p: PendingProposal) -> PendingProposalRead:
    return PendingProposalRead(
        id=p.id,
        kind=p.kind,
        status=p.status,
        payload=dict(p.payload),
        created_at=p.created_at,
        resolved_at=p.resolved_at,
        resolution_note=p.resolution_note,
    )


class ProposalService:
    @staticmethod
    async def list_pending(db: AsyncSession, user: User) -> list[PendingProposal]:
        result = await db.execute(
            select(PendingProposal)
            .where(PendingProposal.user_id == user.id, PendingProposal.status == "pending")
            .order_by(PendingProposal.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def approve(db: AsyncSession, user: User, proposal_id: int, note: str | None = None) -> PendingProposal:
        prop = await db.get(PendingProposal, proposal_id)
        if not prop or prop.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        if prop.status != "pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal is not pending")

        if prop.kind == "create_deal":
            payload = dict(prop.payload)
            deal_in = DealCreate(**payload)
            await DealService.create_deal(db, deal_in, user.id, commit=False)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown proposal kind: {prop.kind}")

        prop.status = "approved"
        prop.resolution_note = note
        prop.resolved_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(prop)
        return prop

    @staticmethod
    async def reject(db: AsyncSession, user: User, proposal_id: int, note: str | None = None) -> PendingProposal:
        prop = await db.get(PendingProposal, proposal_id)
        if not prop or prop.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
        if prop.status != "pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposal is not pending")

        prop.status = "rejected"
        prop.resolution_note = note
        prop.resolved_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(prop)
        return prop
