"""One-tap maintenance endpoints invoked from the Settings page.

Today we expose a single operation: hard-delete the legacy auto-spawned chat
threads (kind ``entity``, bound to email/contact/event) where the user never
typed anything. Those threads were created by the old proactive layer that
auto-ran the agent on every inbound email; the new layer is push-only, but
historical pollution still lives in the DB and clogs up the sidebar.

Scoped to the calling user only. The CLI equivalent is
``backend/app/scripts/cleanup_proactive_noise.py --purge``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.user import User

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class PurgeResponse(BaseModel):
    deleted: int


@router.post("/purge-proactive-threads", response_model=PurgeResponse)
async def purge_proactive_threads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurgeResponse:
    """Hard-delete entity-bound chat threads for the calling user that the user
    never replied in. Cascades to chat_messages first, then deletes threads.
    """
    user_msg_exists = (
        select(ChatMessage.id)
        .where(
            ChatMessage.thread_id == ChatThread.id,
            ChatMessage.role == "user",
        )
        .exists()
    )
    candidate_stmt = select(ChatThread.id).where(
        ChatThread.user_id == current_user.id,
        ChatThread.kind == "entity",
        ChatThread.entity_type.in_(("email", "contact", "event")),
        ~user_msg_exists,
    )
    res = await db.execute(candidate_stmt)
    ids = [row[0] for row in res.all()]
    if not ids:
        return PurgeResponse(deleted=0)

    await db.execute(delete(ChatMessage).where(ChatMessage.thread_id.in_(ids)))
    await db.execute(delete(ChatThread).where(ChatThread.id.in_(ids)))
    await db.commit()
    return PurgeResponse(deleted=len(ids))


# Quietens linters about the unused helper symbol when the module is imported
# elsewhere for side effects only.
_ = exists
