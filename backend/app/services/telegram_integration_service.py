"""Telegram bot token + polling prefs stored per user (Settings UI); env remains fallback."""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import defaultdict
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.schemas.telegram_integration import TelegramIntegrationRead, TelegramIntegrationUpdate
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)


async def _prefs(db: AsyncSession, user: User) -> UserAISettings:
    return await UserAISettingsService.get_or_create(db, user)


async def _token_from_telegram_connector(db: AsyncSession, user: User) -> str | None:
    r = await db.execute(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider == "telegram_bot",
        )
    )
    row = r.scalars().first()
    if not row:
        return None
    from app.services.connector_service import ConnectorService

    try:
        creds = ConnectorService.decrypt_credentials(row)
    except Exception:
        logger.exception("telegram connector decrypt failed user_id=%s", user.id)
        return None
    tok = str(creds.get("bot_token") or "").strip()
    return tok or None


async def get_decrypted_bot_token(db: AsyncSession, user: User) -> str | None:
    prefs = await _prefs(db, user)
    blob = getattr(prefs, "telegram_bot_token_encrypted", None)
    if blob:
        tok = decrypt_secret(blob)
        if tok:
            return tok.strip() or None
    return await _token_from_telegram_connector(db, user)


async def get_effective_bot_token_for_user(db: AsyncSession, user: User) -> str | None:
    tok = await get_decrypted_bot_token(db, user)
    if tok:
        return tok
    env = (settings.telegram_bot_token or "").strip()
    return env or None


async def read_integration(db: AsyncSession, user: User) -> TelegramIntegrationRead:
    prefs = await _prefs(db, user)
    has_settings = bool((getattr(prefs, "telegram_bot_token_encrypted", None) or "").strip())
    has_connector = (await _token_from_telegram_connector(db, user)) is not None
    env = bool((settings.telegram_bot_token or "").strip())
    return TelegramIntegrationRead(
        configured=bool(has_settings or has_connector or env),
        polling_enabled=bool(getattr(prefs, "telegram_polling_enabled", True)),
        poll_timeout=int(getattr(prefs, "telegram_poll_timeout", 45) or 45),
        webhook_secret_configured=bool((getattr(prefs, "telegram_webhook_secret", None) or "").strip())
        or bool((settings.telegram_webhook_secret or "").strip()),
        webhook_secret=None,
    )


async def update_integration(
    db: AsyncSession, user: User, payload: TelegramIntegrationUpdate
) -> TelegramIntegrationRead:
    prefs = await _prefs(db, user)
    data = payload.model_dump(exclude_unset=True)
    reveal_webhook_secret: str | None = None

    if "bot_token" in data:
        raw = data["bot_token"]
        if raw is None:
            pass
        elif str(raw).strip() == "":
            prefs.telegram_bot_token_encrypted = None
        else:
            prefs.telegram_bot_token_encrypted = encrypt_secret(str(raw).strip())
            if not (getattr(prefs, "telegram_webhook_secret", None) or "").strip():
                prefs.telegram_webhook_secret = secrets.token_urlsafe(32)
                reveal_webhook_secret = prefs.telegram_webhook_secret

    if "polling_enabled" in data and data["polling_enabled"] is not None:
        prefs.telegram_polling_enabled = bool(data["polling_enabled"])

    if "poll_timeout" in data and data["poll_timeout"] is not None:
        prefs.telegram_poll_timeout = max(0, min(int(data["poll_timeout"]), 50))

    if data.get("regenerate_webhook_secret"):
        prefs.telegram_webhook_secret = secrets.token_urlsafe(32)
        reveal_webhook_secret = prefs.telegram_webhook_secret

    await db.commit()
    base = await read_integration(db, user)
    if reveal_webhook_secret:
        return base.model_copy(update={"webhook_secret": reveal_webhook_secret})
    return base


@dataclass(frozen=True)
class TelegramPollTarget:
    bot_token: str
    poll_timeout: int


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


async def list_telegram_poll_targets(db: AsyncSession) -> list[TelegramPollTarget]:
    """Distinct bot tokens to long-poll (worker). Merges env token + all users with a token."""
    by_token: dict[str, list[tuple[int, int, bool]]] = defaultdict(list)
    # (user_id, poll_timeout, polling_enabled)

    env_tok = (settings.telegram_bot_token or "").strip()
    if env_tok and settings.telegram_polling_enabled:
        by_token[env_tok].append(
            (0, max(0, min(int(getattr(settings, "telegram_poll_timeout", 45) or 45), 50)), True)
        )

    r = await db.execute(select(UserAISettings))
    for prefs in r.scalars().all():
        u = await db.get(User, int(prefs.user_id))
        if not u:
            continue
        tok = await get_decrypted_bot_token(db, u)
        if not tok:
            continue
        if not bool(getattr(prefs, "telegram_polling_enabled", True)):
            continue
        to = int(getattr(prefs, "telegram_poll_timeout", 45) or 45)
        by_token[tok].append((int(prefs.user_id), max(0, min(to, 50)), True))

    out: list[TelegramPollTarget] = []
    for tok, entries in by_token.items():
        if not any(e[2] for e in entries):
            continue
        poll_timeout = max(e[1] for e in entries)
        if poll_timeout <= 0:
            poll_timeout = 45
        out.append(TelegramPollTarget(bot_token=tok, poll_timeout=poll_timeout))
    return out


def offset_file_path_for_token(bot_token: str) -> str:
    """Filename fragment for persisting getUpdates offset (under user data dir)."""
    return f"telegram_poll_offset_{_token_key(bot_token)}.json"


async def resolve_webhook_secret_for_request(
    db: AsyncSession, path_secret: str
) -> tuple[str | None, User | None]:
    """Match webhook secret to user row (or env). Returns (bot_token, user) for dispatch context."""
    path_secret = (path_secret or "").strip()
    if not path_secret:
        return None, None
    env_secret = (settings.telegram_webhook_secret or "").strip()
    env_tok = (settings.telegram_bot_token or "").strip()
    if env_secret and path_secret == env_secret and env_tok:
        return env_tok, None

    r = await db.execute(select(UserAISettings))
    for prefs in r.scalars().all():
        ws = (getattr(prefs, "telegram_webhook_secret", None) or "").strip()
        if not ws or ws != path_secret:
            continue
        user = await db.get(User, int(prefs.user_id))
        if not user:
            continue
        tok = await get_decrypted_bot_token(db, user)
        if tok:
            return tok, user
    return None, None


async def user_telegram_configured(db: AsyncSession, user: User) -> bool:
    return (await get_effective_bot_token_for_user(db, user)) is not None
