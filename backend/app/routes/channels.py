"""Gateway / multi-channel stub — disabled unless ``AGENT_CHANNEL_GATEWAY_ENABLED``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.channel import ChannelDeliverResult, ChannelInboundMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.channel_binding import get_or_create_thread_for_channel

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[Depends(get_current_user)])


@router.post("/gateway/deliver", response_model=ChannelDeliverResult)
async def gateway_deliver(
    payload: ChannelInboundMessage,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelDeliverResult:
    """Run the agent for one inbound message (stub gateway uses ``gateway_stub`` channel).

    Requires ``AGENT_CHANNEL_GATEWAY_ENABLED=true`` so production instances do not
    expose this path accidentally.
    """
    if not settings.agent_channel_gateway_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel gateway is disabled")

    AgentRateLimitService.check(current_user.id)
    thread = await get_or_create_thread_for_channel(
        db,
        current_user,
        channel=payload.channel.value,
        external_key=payload.external_key,
    )
    run = await AgentService.run_agent(
        db,
        current_user,
        payload.text,
        thread_id=thread.id,
        thread_context_hint=f"Channel {payload.channel.value} (external: {payload.external_key[:80]})",
    )
    return ChannelDeliverResult(
        run_id=run.id,
        chat_thread_id=thread.id,
        root_trace_id=run.root_trace_id,
        status=run.status,
    )
