"""User-level AI preferences + a *mirror* of the active provider's config.

Since the introduction of :class:`app.models.user_ai_provider_config.UserAIProviderConfig`
(migration ``0016_ai_provider_configs``) the per-provider config columns on
this table (``provider_kind``, ``base_url``, ``chat_model``, ``embedding_model``,
``classify_model``, ``extras``, ``api_key_encrypted``) are kept as a *cached
mirror* of the active provider config — the canonical source of truth lives
in ``user_ai_provider_configs``. The mirror exists so existing call sites
that still take a :class:`UserAISettings` keep working unchanged through
the transition.

The new fields are:

- ``active_provider_kind`` — the pointer the agent loop reads. ``NULL``
  means "no provider selected" and the chat composer is disabled.
- ``embedding_provider_kind`` — optional pointer for embedding calls (agent
  memory). ``NULL`` means use the same row as ``active_provider_kind``.
- ``ranking_provider_kind`` — optional pointer for auxiliary LLM calls that
  use the row's ``classify_model`` (ranking / structured JSON). ``NULL`` means
  the same row as the active provider.
- ``ai_disabled`` — kill-switch unchanged.

The mirror columns are kept in sync by
:class:`app.services.ai_provider_config_service.AIProviderConfigService`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserAISettings(Base, TimestampMixin):
    __tablename__ = "user_ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    # User-level prefs.
    active_provider_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Agent tool-calling: auto (model heuristic), native (API tools), prompted (<tool_call> tags).
    harness_mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    # User-local wall clock for the agent (IANA name, e.g. Europe/Madrid). None → UTC in prompts.
    user_timezone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Clock display in prompts / get_session_time: auto | 12 | 24
    time_format: Mapped[str] = mapped_column(String(8), default="auto", nullable=False)
    # When true, new agent turns fail fast with a friendly message (dashboard "pause").
    agent_processing_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When set, agent memory embeddings use this user_ai_provider_configs row
    # instead of the active one. NULL = same as active_provider_kind.
    embedding_provider_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ranking_provider_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Partial overrides for ``config.settings`` agent_* keys (merged server-side).
    agent_runtime_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Short async-maintained summary for “user TL;DR” injection (context-first harness).
    agent_context_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_context_overview_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Telegram bot (inbound DMs + replies): token encrypted like legacy secrets; optional webhook secret.
    telegram_bot_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_polling_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_poll_timeout: Mapped[int] = mapped_column(default=45, nullable=False)
    telegram_webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Mirror of the active provider config — DO NOT WRITE DIRECTLY. Use
    # AIProviderConfigService.set_active() / upsert_config() so the mirror
    # stays in sync with user_ai_provider_configs (the canonical source).
    provider_kind: Mapped[str] = mapped_column(String(32), default="openai_compatible", nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(128), default="text-embedding-3-small", nullable=False)
    chat_model: Mapped[str] = mapped_column(String(128), default="gpt-4o-mini", nullable=False)
    classify_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    user = relationship("User", back_populates="ai_settings")
