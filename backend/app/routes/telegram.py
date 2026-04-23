"""Telegram bot: settings UI, authenticated pairing + unauthenticated webhook."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cockpit import TelegramLinkStatusRead, TelegramPairingRead
from app.schemas.telegram_integration import TelegramIntegrationRead, TelegramIntegrationUpdate
from app.services.telegram_inbound_service import (
    dispatch_telegram_bot_update,
    issue_pairing_code,
    user_has_telegram_link,
)
from app.services.telegram_integration_service import (
    get_effective_bot_token_for_user,
    read_integration,
    resolve_webhook_secret_for_request,
    update_integration,
)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/integration", response_model=TelegramIntegrationRead)
async def get_telegram_integration(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TelegramIntegrationRead:
    return await read_integration(db, current_user)


@router.patch("/integration", response_model=TelegramIntegrationRead)
async def patch_telegram_integration(
    payload: TelegramIntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TelegramIntegrationRead:
    try:
        return await update_integration(db, current_user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/pairing-code", response_model=TelegramPairingRead)
async def create_telegram_pairing_code(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TelegramPairingRead:
    if not await get_effective_bot_token_for_user(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure a Telegram bot token in Settings → Telegram (or TELEGRAM_BOT_TOKEN).",
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
    tok, _user = await resolve_webhook_secret_for_request(db, secret)
    if not tok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    body = await request.json()
    await dispatch_telegram_bot_update(db, body, bot_token=tok)
    return {"ok": True}
