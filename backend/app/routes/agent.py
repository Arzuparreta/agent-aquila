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
    AgentRunSummaryRead,
    AgentTraceEventRead,
    PendingOperationPreviewRead,
    PendingOperationRead,
    PendingProposalRead,
)
from app.models.agent_run import AgentRun
from app.models.chat_thread import ChatThread
from app.services.agent_event_bus import publish_run_status_event
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.chat_service import apply_agent_run_to_placeholder
from app.services.capability_policy import risk_tier_for_kind
from app.services.capability_registry import describe_capabilities
from app.services.pending_execution_service import preview_for_proposal_kind
from app.services.proposal_service import ProposalService, proposal_to_read

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(get_current_user)])


@router.get("/runs", response_model=list[AgentRunSummaryRead])
async def list_agent_runs(
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentRunSummaryRead]:
    return await AgentService.list_recent_runs(db, current_user, limit=limit)


@router.post("/runs", response_model=AgentRunRead)
async def create_agent_run(
    payload: AgentRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunRead:
    AgentRateLimitService.check(current_user.id)
    return await AgentService.run_agent(db, current_user, payload.message, agent_ctx={"source_channel": "api"})


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


@router.post("/runs/{run_id}/stop", response_model=AgentRunRead)
async def stop_agent_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentRunRead:
    run_row = await db.get(AgentRun, run_id)
    if not run_row or run_row.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run_row.status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active.",
        )
    if run_row.status == "pending":
        run_row.status = "cancelled"
        run_row.assistant_reply = (run_row.assistant_reply or "").strip() or "Stopped."
        run_row.cancel_requested = False
        await db.commit()
        read = await AgentService.get_run(db, current_user, run_id)
        tid = run_row.chat_thread_id
        if read and tid is not None:
            thread = await db.get(ChatThread, tid)
            if thread and thread.user_id == current_user.id:
                await apply_agent_run_to_placeholder(
                    db, thread, agent_run_id=run_id, run_read=read
                )
                await db.commit()
        await publish_run_status_event(
            user_id=current_user.id,
            run_id=run_id,
            status="cancelled",
            error=None,
            step_count=0,
            chat_thread_id=tid,
            terminal=True,
        )
        if not read:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return read

    run_row.cancel_requested = True
    await db.commit()
    read = await AgentService.get_run(db, current_user, run_id)
    if not read:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return read


@router.get("/runs/{run_id}/trace-events", response_model=list[AgentTraceEventRead])
async def list_agent_run_trace_events(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentTraceEventRead]:
    events = await AgentService.list_trace_events(db, current_user, run_id)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return events


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
