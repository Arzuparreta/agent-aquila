"""Telegram bot: authenticated pairing + unauthenticated webhook."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cockpit import TelegramLinkStatusRead, TelegramPairingRead
from app.services.telegram_inbound_service import (
    handle_telegram_text_message,
    issue_pairing_code,
    user_has_telegram_link,
)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/pairing-code", response_model=TelegramPairingRead)
async def create_telegram_pairing_code(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TelegramPairingRead:
    if not (settings.telegram_bot_token or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured (TELEGRAM_BOT_TOKEN).",
        )
    code, exp = await issue_pairing_code(db, current_user)
    return TelegramPairingRead(code=code, expires_at=exp)


@router.get("/link-status", response_model=TelegramLinkStatusRead)
async def telegram_link_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TelegramLinkStatusRead:
    linked = await user_has_telegram_link(db, current_user)
    return TelegramLinkStatusRead(linked=linked)


@router.post("/webhook/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    if not (settings.telegram_bot_token or "").strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="disabled")
    expected = (settings.telegram_webhook_secret or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    body = await request.json()
    msg = body.get("message") or body.get("edited_message")
    if isinstance(msg, dict):
        chat = msg.get("chat") or {}
        cid = str(chat.get("id") or "")
        text = str(msg.get("text") or "")
        if cid:
            await handle_telegram_text_message(db, telegram_chat_id=cid, text=text)
    return {"ok": True}
