"""Outbound Telegram messages (completion notifications)."""

from __future__ import annotations

import logging
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.channel_thread_binding import ChannelThreadBinding
from app.services.llm_client import shared_http_client

logger = logging.getLogger(__name__)


async def send_telegram_text(chat_id: str, text: str) -> None:
    token = (settings.telegram_bot_token or "").strip()
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
    await send_telegram_text(chat_id, body)
