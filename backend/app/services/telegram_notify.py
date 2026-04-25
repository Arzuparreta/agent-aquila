"""Outbound Telegram messages (completion notifications)."""

from __future__ import annotations

import logging
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.channel_thread_binding import ChannelThreadBinding
from app.models.user import User
from app.services.llm_client import shared_http_client
from app.services.telegram_integration_service import get_effective_bot_token_for_user

logger = logging.getLogger(__name__)


async def send_telegram_text(chat_id: str, text: str, *, bot_token: str | None = None) -> None:
    token = ((bot_token or "").strip() or (settings.telegram_bot_token or "").strip())
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = await shared_http_client().post(
            url,
            json={"chat_id": chat_id, "text": (text or "")[:4090]},
            timeout=httpx.Timeout(60.0, connect=15.0),
        )
        r.raise_for_status()
    except Exception:
        logger.exception("telegram sendMessage failed chat_id=%s", chat_id[:8])


async def notify_telegram_for_completed_run(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    assistant_reply: str | None,
    error: str | None,
) -> None:
    """If this thread is bound to Telegram, push the final text to the chat."""
    r = await db.execute(
        select(ChannelThreadBinding).where(
            ChannelThreadBinding.user_id == user_id,
            ChannelThreadBinding.chat_thread_id == thread_id,
            ChannelThreadBinding.channel == "telegram",
        )
    )
    row = r.scalar_one_or_none()
    if not row:
        return
    chat_id = (row.external_key or "").strip()
    if not chat_id:
        return
    body = (assistant_reply or error or "(no output)")[:4090]
    user = await db.get(User, user_id)
    if not user:
        return
    tok = await get_effective_bot_token_for_user(db, user)
    await send_telegram_text(chat_id, body, bot_token=tok)


async def notify_user_telegram(
    db: AsyncSession,
    *,
    user_id: int,
    message: str,
) -> bool:
    """Send a Telegram message to the user's primary Telegram chat.

    Returns True if sent, False if user has no Telegram connected.
    """
    r = await db.execute(
        select(ChannelThreadBinding.external_key).where(
            ChannelThreadBinding.user_id == user_id,
            ChannelThreadBinding.channel == "telegram",
        )
    )
    chat_id = r.scalar_one_or_none()
    if not chat_id:
        return False
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return False
    user = await db.get(User, user_id)
    if not user:
        return False
    tok = await get_effective_bot_token_for_user(db, user)
    await send_telegram_text(chat_id, message[:4090], bot_token=tok)
    return True
