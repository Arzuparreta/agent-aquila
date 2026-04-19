from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import PendingProposalRead
from app.services.audit_service import create_audit_log
from app.services.capability_policy import enforce_email_recipients_allowed, risk_tier_for_kind
from app.services.pending_execution_service import PendingExecutionService


def proposal_to_read(p: PendingProposal) -> PendingProposalRead:
    return PendingProposalRead(
        id=p.id,
        kind=p.kind,
        summary=p.summary,
        risk_tier=risk_tier_for_kind(p.kind),
        idempotency_key=p.idempotency_key,
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

        if prop.kind in ("email_send", "email_reply"):
            enforce_email_recipients_allowed(dict(prop.payload))

        try:
            await PendingExecutionService.execute(db, user, prop.kind, dict(prop.payload), commit=False)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors()) from exc

        await create_audit_log(
            db,
            "pending_proposal",
            prop.id,
            "approved",
            {"kind": prop.kind, "payload_keys": sorted(dict(prop.payload).keys())},
            user.id,
        )
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
        await create_audit_log(
            db,
            "pending_proposal",
            prop.id,
            "rejected",
            {"kind": prop.kind},
            user.id,
        )
        await db.commit()
        await db.refresh(prop)
        return prop
