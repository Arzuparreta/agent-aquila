from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramIntegrationRead(BaseModel):
    """User-visible Telegram bot configuration (no raw token)."""

    configured: bool
    polling_enabled: bool
    poll_timeout: int = Field(ge=0, le=50)
    webhook_secret_configured: bool
    # Returned only immediately after PATCH generates a new secret (copy to configure Telegram webhook).
    webhook_secret: str | None = None


class TelegramIntegrationUpdate(BaseModel):
    bot_token: str | None = Field(
        default=None,
        description="When set, replaces stored token. Empty string clears stored token.",
        max_length=256,
    )
    polling_enabled: bool | None = None
    poll_timeout: int | None = Field(default=None, ge=0, le=50)
    regenerate_webhook_secret: bool | None = Field(
        default=None,
        description="When true, generate a new webhook path secret.",
    )
