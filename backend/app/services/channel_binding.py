"""Map (user, channel, external_key) to a :class:`ChatThread` for multi-channel chat."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_thread_binding import ChannelThreadBinding
from app.models.chat_thread import ChatThread
from app.models.user import User


async def get_or_create_thread_for_channel(
    db: AsyncSession,
    user: User,
    *,
    channel: str,
    external_key: str,
    title: str | None = None,
) -> ChatThread:
    """Return the bound thread or create a general thread + binding row."""
    key = (external_key or "").strip()[:512]
    ch = (channel or "").strip()[:32]
    if not key or not ch:
        raise ValueError("channel and external_key are required")

    stmt = select(ChannelThreadBinding).where(
        ChannelThreadBinding.user_id == user.id,
        ChannelThreadBinding.channel == ch,
        ChannelThreadBinding.external_key == key,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        row = await db.get(ChatThread, existing.chat_thread_id)
        if row:
            return row

    thread = ChatThread(
        user_id=user.id,
        kind="general",
        entity_type=None,
        entity_id=None,
        title=(title or f"Gateway {ch}")[:255],
        is_default=False,
    )
    db.add(thread)
    await db.flush()
    db.add(
        ChannelThreadBinding(
            user_id=user.id,
            channel=ch,
            external_key=key,
            chat_thread_id=thread.id,
        )
    )
    await db.flush()
    return thread
