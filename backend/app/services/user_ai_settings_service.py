"""Compatibility shim around the legacy ``user_ai_settings`` row.

Since the introduction of multi-provider configs (migration 0016 +
:class:`app.services.ai_provider_config_service.AIProviderConfigService`),
the per-provider columns on ``user_ai_settings`` are a *cached mirror* of
the active provider config. This service exposes the legacy interface
(``get_or_create``, ``get_api_key``, ``update_settings``, ``to_read``)
unchanged so the dozens of existing call sites — agent loop, embedding
service, RAG indexer, triage, drafts — keep working without any change.

All writes go through :class:`AIProviderConfigService` so the canonical
``user_ai_provider_configs`` table stays in sync.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope_crypto import KeyDecryptError
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.schemas.ai import UserAISettingsRead, UserAISettingsUpdate
from app.services.ai_provider_config_service import (
    AIProviderConfigService,
    ProviderConfigUpsert,
)
from app.services.ai_providers import normalize_provider_id
from app.services.user_time_context import normalize_time_format

HarnessMode = Literal["auto", "native", "prompted"]


def coerce_harness_mode(row: UserAISettings) -> HarnessMode:
    hm = getattr(row, "harness_mode", None) or "auto"
    if hm in ("auto", "native", "prompted"):
        return hm
    return "auto"


class UserAISettingsService:
    @staticmethod
    async def get_or_create(db: AsyncSession, user: User) -> UserAISettings:
        result = await db.execute(
            select(UserAISettings).where(UserAISettings.user_id == user.id)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        row = UserAISettings(user_id=user.id)
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    def to_read(row: UserAISettings) -> UserAISettingsRead:
        return UserAISettingsRead(
            provider_kind=row.provider_kind,
            base_url=row.base_url,
            embedding_model=row.embedding_model,
            chat_model=row.chat_model,
            classify_model=row.classify_model,
            ai_disabled=row.ai_disabled,
            has_api_key=False,  # Filled in by callers that have access to db; safe default.
            extras=row.extras,
            harness_mode=coerce_harness_mode(row),
            user_timezone=getattr(row, "user_timezone", None),
            time_format=normalize_time_format(getattr(row, "time_format", None)),  # type: ignore[arg-type]
            agent_processing_paused=bool(getattr(row, "agent_processing_paused", False)),
        )

    @staticmethod
    async def to_read_async(db: AsyncSession, user: User, row: UserAISettings) -> UserAISettingsRead:
        """Like :meth:`to_read` but resolves ``has_api_key`` from the active config."""
        active = await AIProviderConfigService.get_active(db, user)
        return UserAISettingsRead(
            provider_kind=row.provider_kind,
            base_url=row.base_url,
            embedding_model=row.embedding_model,
            chat_model=row.chat_model,
            classify_model=row.classify_model,
            ai_disabled=row.ai_disabled,
            has_api_key=bool(active and active.has_api_key),
            extras=row.extras,
            harness_mode=coerce_harness_mode(row),
            user_timezone=getattr(row, "user_timezone", None),
            time_format=normalize_time_format(getattr(row, "time_format", None)),  # type: ignore[arg-type]
            agent_processing_paused=bool(getattr(row, "agent_processing_paused", False)),
        )

    @staticmethod
    async def update_settings(
        db: AsyncSession, user: User, payload: UserAISettingsUpdate
    ) -> UserAISettingsRead:
        """Compatibility writer for the old ``PATCH /ai/settings`` endpoint.

        Translates the single-row update into:

        - An ``upsert_config`` against the chosen provider (or the
          currently active one when ``provider_kind`` isn't provided).
        - A ``set_active`` flip when ``provider_kind`` changed.
        - A direct write to the user-level ``ai_disabled`` toggle.

        Net effect: clients still talking to the old endpoint never lose
        keys when they switch providers, because each provider keeps its
        own row.
        """
        prefs = await UserAISettingsService.get_or_create(db, user)
        data = payload.model_dump(exclude_unset=True)

        if "ai_disabled" in data:
            prefs.ai_disabled = bool(data["ai_disabled"])

        if "harness_mode" in data and data["harness_mode"] is not None:
            hm = str(data["harness_mode"]).strip().lower()
            if hm not in ("auto", "native", "prompted"):
                raise ValueError(f"Invalid harness_mode: {data['harness_mode']!r}")
            prefs.harness_mode = hm

        if "user_timezone" in data:
            tz = data["user_timezone"]
            if tz is None or (isinstance(tz, str) and not tz.strip()):
                prefs.user_timezone = None
            else:
                prefs.user_timezone = str(tz).strip()[:128]

        if "time_format" in data and data["time_format"] is not None:
            prefs.time_format = normalize_time_format(str(data["time_format"]))

        if "agent_processing_paused" in data and data["agent_processing_paused"] is not None:
            prefs.agent_processing_paused = bool(data["agent_processing_paused"])

        # Pick the target provider for this update. When the client doesn't
        # name one, we keep operating on the currently-active one (or fall
        # back to the legacy mirror's column for the very first save on a
        # fresh install).
        target_kind_raw = data.get("provider_kind") or prefs.active_provider_kind or prefs.provider_kind
        target_kind = normalize_provider_id(target_kind_raw)

        upsert = ProviderConfigUpsert(
            base_url=data.get("base_url"),
            chat_model=data.get("chat_model"),
            embedding_model=data.get("embedding_model"),
            classify_model=data.get("classify_model") if "classify_model" in data else None,
            extras=data.get("extras") if "extras" in data else None,
            api_key=data.get("api_key") if "api_key" in data else None,
        )
        # Treat empty-string classify_model as "clear" to mirror the prior behaviour.
        if "classify_model" in data and data["classify_model"] == "":
            upsert = ProviderConfigUpsert(
                base_url=upsert.base_url,
                chat_model=upsert.chat_model,
                embedding_model=upsert.embedding_model,
                classify_model="",
                extras=upsert.extras,
                api_key=upsert.api_key,
            )

        # Save the per-provider config (creates the row on first touch).
        await AIProviderConfigService.upsert_config(db, user, target_kind, upsert)

        # If the client switched provider, flip the active pointer (this also
        # refreshes the legacy mirror).
        active = prefs.active_provider_kind or prefs.provider_kind
        if normalize_provider_id(active) != target_kind:
            await AIProviderConfigService.set_active(db, user, target_kind)

        await db.commit()
        await db.refresh(prefs)
        return await UserAISettingsService.to_read_async(db, user, prefs)

    @staticmethod
    async def get_api_key(db: AsyncSession, user: User) -> str | None:
        """Decrypted API key of the active provider config, or ``None``.

        Returns ``None`` (instead of raising) on decryption failure so the
        existing call sites — which already treat ``None`` as "no key" —
        continue to behave deterministically. The structured failure is
        still surfaced in the new ``/ai/providers/configs`` endpoints and
        in the agent loop's :class:`LLMProviderError` translation.
        """
        try:
            return await AIProviderConfigService.decrypt_active_api_key(db, user)
        except KeyDecryptError:
            return None
