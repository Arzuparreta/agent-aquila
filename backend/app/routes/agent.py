from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.agent import AgentRunCreate, AgentRunRead, PendingProposalRead
from app.services.agent_service import AgentService
from app.services.proposal_service import ProposalService, proposal_to_read

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(get_current_user)])


@router.post("/runs", response_model=AgentRunRead)
async def create_agent_run(
    payload: AgentRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunRead:
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
