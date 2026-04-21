from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
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
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
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


@router.get("/runs/{run_id}/stream")
async def stream_agent_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Server-Sent Events for agent run status until ``completed`` or ``failed`` (or stream cap).

    Polls the database on a short interval; the ARQ worker updates ``agent_runs`` in
    the background. Same auth as ``GET /agent/runs/{id}`` — 404 if the run is missing
    or not owned by the current user.
    """
    probe = await AgentService.get_run(db, current_user, run_id)
    if not probe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    _terminal = frozenset({"completed", "failed"})
    _max_stream_seconds = 3600.0
    _sleep_s = 1.0

    async def sse_gen():
        seq = 0
        t0 = time.monotonic()
        while True:
            run = await AgentService.get_run(db, current_user, run_id)
            if not run:
                yield f"data: {json.dumps({'seq': seq, 'error': 'not_found'})}\n\n"
                return
            seq += 1
            payload: dict = {
                "seq": seq,
                "id": run.id,
                "status": run.status,
                "error": run.error,
                "step_count": len(run.steps),
            }
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            if run.status in _terminal:
                return
            if time.monotonic() - t0 > _max_stream_seconds:
                yield f"data: {json.dumps({'seq': seq, 'error': 'sse_timeout'})}\n\n"
                return
            await asyncio.sleep(_sleep_s)

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
