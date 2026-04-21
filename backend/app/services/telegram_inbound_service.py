"""Telegram bot: pairing codes and inbound agent turns."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import secrets
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.telegram_channel import TelegramAccountLink, TelegramPairingCode
from app.models.user import User
from app.services.agent_attachments import attachments_from_agent_run_read
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.channel_binding import get_or_create_thread_for_channel
from app.services.chat_service import append_message, apply_agent_run_to_placeholder, history_for_agent
from app.services.chat_service import render_user_message
from app.services.job_queue import enqueue
from app.services.telegram_notify import send_telegram_text

logger = logging.getLogger(__name__)

_PLACEHOLDER = "\u2026"


async def issue_pairing_code(db: AsyncSession, user: User) -> tuple[str, datetime]:
    await db.execute(delete(TelegramPairingCode).where(TelegramPairingCode.user_id == user.id))
    await db.flush()
    code = secrets.token_hex(4)
    exp = datetime.now(UTC) + timedelta(minutes=10)
    db.add(TelegramPairingCode(code=code, user_id=user.id, expires_at=exp))
    await db.commit()
    return code, exp


async def user_has_telegram_link(db: AsyncSession, user: User) -> bool:
    r = await db.execute(select(TelegramAccountLink.id).where(TelegramAccountLink.user_id == user.id).limit(1))
    return r.scalar_one_or_none() is not None


async def link_chat_with_code(db: AsyncSession, *, code: str, telegram_chat_id: str) -> bool:
    c = (code or "").strip()
    row = (
        await db.execute(select(TelegramPairingCode).where(TelegramPairingCode.code == c))
    ).scalar_one_or_none()
    if not row:
        return False
    if row.expires_at < datetime.now(UTC):
        await db.execute(delete(TelegramPairingCode).where(TelegramPairingCode.code == c))
        await db.commit()
        return False
    uid = int(row.user_id)
    await db.execute(delete(TelegramPairingCode).where(TelegramPairingCode.code == c))
    await db.execute(
        delete(TelegramAccountLink).where(TelegramAccountLink.telegram_chat_id == telegram_chat_id)
    )
    db.add(TelegramAccountLink(user_id=uid, telegram_chat_id=telegram_chat_id))
    await db.commit()
    return True


async def get_user_for_telegram_chat(db: AsyncSession, telegram_chat_id: str) -> User | None:
    r = await db.execute(
        select(TelegramAccountLink).where(TelegramAccountLink.telegram_chat_id == telegram_chat_id)
    )
    link = r.scalar_one_or_none()
    if not link:
        return None
    return await db.get(User, link.user_id)


async def handle_telegram_text_message(db: AsyncSession, *, telegram_chat_id: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_telegram_text(
                telegram_chat_id,
                "Generate a code in the app dashboard (Telegram section), then send:\n/start YOUR_CODE",
            )
            return
        code = parts[1].strip()
        ok = await link_chat_with_code(db, code=code, telegram_chat_id=telegram_chat_id)
        if ok:
            await send_telegram_text(telegram_chat_id, "Connected! You can chat with your agent here.")
        else:
            await send_telegram_text(
                telegram_chat_id,
                "Invalid or expired code. Generate a fresh code in the dashboard.",
            )
        return

    user = await get_user_for_telegram_chat(db, telegram_chat_id)
    if not user:
        await send_telegram_text(
            telegram_chat_id,
            "Not linked yet. Open the dashboard → Telegram, then send /start YOUR_CODE here.",
        )
        return

    AgentRateLimitService.check(user.id)
    thread = await get_or_create_thread_for_channel(
        db,
        user,
        channel="telegram",
        external_key=telegram_chat_id,
        title="Telegram",
    )
    await append_message(db, thread, role="user", content=text)
    await db.commit()
    await db.refresh(thread)

    prior = await history_for_agent(db, thread)
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == text:
        prior = prior[:-1]
    rendered = render_user_message(text, [])
    hint = f"Telegram (chat {telegram_chat_id})"

    early = await AgentService.run_agent_invalid_preflight(db, user, rendered, thread_id=thread.id)
    if early is not None:
        cards = attachments_from_agent_run_read(early)
        body = early.assistant_reply or early.error or ""
        if not body and not cards:
            body = "Can't run the agent right now."
        await append_message(
            db,
            thread,
            role="assistant" if early.status == "completed" else "system",
            content=body,
            attachments=cards or None,
            agent_run_id=early.id,
        )
        await db.commit()
        await send_telegram_text(telegram_chat_id, body or "Something went wrong.")
        return

    use_async = settings.agent_async_runs and bool(settings.redis_url)
    if use_async:
        run_row = await AgentService.create_pending_agent_run(db, user, rendered, thread_id=thread.id)
        run_id = int(run_row.id)
        await append_message(
            db, thread, role="assistant", content=_PLACEHOLDER, agent_run_id=run_id
        )
        await db.commit()
        try:
            await enqueue(
                "run_chat_agent_turn",
                run_id,
                user.id,
                prior,
                hint,
                _job_id=f"agent_run:{run_id}",
            )
        except Exception:
            logger.exception("telegram ARQ enqueue failed run_id=%s", run_id)
        return

    run = await AgentService.run_agent(
        db,
        user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=hint,
    )
    cards = attachments_from_agent_run_read(run)
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    if run.assistant_reply:
        assistant_text = run.assistant_reply
    elif has_error_card:
        assistant_text = ""
    else:
        assistant_text = run.error or ""
    await append_message(
        db,
        thread,
        role="assistant" if run.status == "completed" else "system",
        content=assistant_text,
        attachments=cards or None,
        agent_run_id=run.id,
    )
    await db.commit()
    await send_telegram_text(telegram_chat_id, assistant_text or run.error or "")
