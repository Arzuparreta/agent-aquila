from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import (
    AgentRunCreate,
    AgentRunRead,
    ExecutedActionRead,
    PendingOperationPreviewRead,
    PendingOperationRead,
    PendingProposalRead,
)
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.auto_apply_service import undo_action
from app.services.capability_policy import risk_tier_for_kind
from app.services.capability_registry import describe_capabilities
from app.services.pending_execution_service import preview_for_proposal_kind
from app.services.proposal_service import ProposalService, proposal_to_read

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(get_current_user)])


@router.post("/runs", response_model=AgentRunRead)
async def create_agent_run(
    payload: AgentRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunRead:
    AgentRateLimitService.check(current_user.id)
    return await AgentService.run_agent(db, current_user, payload.message)


@router.get("/runs/{run_id}", response_model=AgentRunRead)
async def get_agent_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunRead:
    run = await AgentService.get_run(db, current_user, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/capabilities")
async def agent_capabilities() -> dict:
    return describe_capabilities()


@router.get("/pending-operations", response_model=list[PendingOperationRead])
async def list_pending_operations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PendingOperationRead]:
    rows = await ProposalService.list_pending(db, current_user)
    return [proposal_to_read(p) for p in rows]


@router.get("/pending-operations/{operation_id}", response_model=PendingOperationRead)
async def get_pending_operation(
    operation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingOperationRead:
    prop = await db.get(PendingProposal, operation_id)
    if not prop or prop.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending operation not found")
    return proposal_to_read(prop)


@router.get("/pending-operations/{operation_id}/preview", response_model=PendingOperationPreviewRead)
async def get_pending_operation_preview(
    operation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingOperationPreviewRead:
    prop = await db.get(PendingProposal, operation_id)
    if not prop or prop.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending operation not found")
    preview = preview_for_proposal_kind(prop.kind, dict(prop.payload))
    return PendingOperationPreviewRead(
        kind=prop.kind,
        risk_tier=risk_tier_for_kind(prop.kind),
        summary=prop.summary,
        preview=preview,
    )


@router.get("/proposals", response_model=list[PendingProposalRead])
async def list_pending_proposals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PendingProposalRead]:
    rows = await ProposalService.list_pending(db, current_user)
    return [proposal_to_read(p) for p in rows]


@router.post("/proposals/{proposal_id}/approve", response_model=PendingProposalRead)
async def approve_proposal(
    proposal_id: int,
    note: str | None = Query(default=None, max_length=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingProposalRead:
    prop = await ProposalService.approve(db, current_user, proposal_id, note)
    return proposal_to_read(prop)


@router.post("/proposals/{proposal_id}/reject", response_model=PendingProposalRead)
async def reject_proposal(
    proposal_id: int,
    note: str | None = Query(default=None, max_length=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingProposalRead:
    prop = await ProposalService.reject(db, current_user, proposal_id, note)
    return proposal_to_read(prop)


@router.post("/actions/{action_id}/undo", response_model=ExecutedActionRead)
async def undo_executed_action(
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExecutedActionRead:
    """Reverse an auto-applied agent action within its undo window.

    The chat UI fires this when the artist taps the UNDO button on an action card.
    Returns the updated row (``reversed_at`` set) or HTTP 410 if the window has passed.
    """
    row = await undo_action(db, current_user, action_id)
    await db.commit()
    await db.refresh(row)
    return ExecutedActionRead(
        id=row.id,
        kind=row.kind,
        summary=row.summary,
        status=row.status,
        payload=dict(row.payload),
        result=dict(row.result) if row.result else None,
        reversible_until=row.reversible_until,
        reversed_at=row.reversed_at,
        created_at=row.created_at,
    )
