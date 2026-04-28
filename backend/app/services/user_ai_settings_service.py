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

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope_crypto import KeyDecryptError
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.schemas.agent_runtime_config import AgentRuntimeConfigPartial
from app.schemas.ai import UserAISettingsRead, UserAISettingsUpdate
from app.services.agent_runtime_config_service import merge_patch_into_stored, runtime_from_row
from app.services.ai_provider_config_service import (
    AIProviderConfigService,
    ProviderConfigUpsert,
)
from app.services.ai_providers import normalize_provider_id
from app.services.user_time_context import normalize_time_format

HarnessMode = Literal["native"]  # prompted mode removed


async def merge_calendar_timezone_from_user_prefs(
    db: AsyncSession, user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    """When ``timezone`` is absent, use the user's IANA zone from AI settings.

    Google/Graph interpret ``dateTime`` as *wall time in ``timeZone``*. If we
    default to UTC while the model supplies local clock times (e.g. "12:00"
    meaning noon at home), the calendar shows an offset (often +1h or +2h in
    Europe)."""
    out = dict(payload)
    if str(out.get("timezone") or "").strip():
        return out
    prefs = await UserAISettingsService.get_or_create(db, user)
    tz = getattr(prefs, "user_timezone", None)
    if tz and str(tz).strip():
        out["timezone"] = str(tz).strip()
    return out


def coerce_harness_mode(row: UserAISettings) -> HarnessMode:
    hm = getattr(row, "harness_mode", None) or "auto"
    if hm in ("native",):
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
            embedding_provider_kind=getattr(row, "embedding_provider_kind", None),
            ranking_provider_kind=getattr(row, "ranking_provider_kind", None),
            ai_disabled=row.ai_disabled,
            has_api_key=False,  # Filled in by callers that have access to db; safe default.
            extras=row.extras,
            harness_mode=coerce_harness_mode(row),
            user_timezone=getattr(row, "user_timezone", None),
            time_format=normalize_time_format(getattr(row, "time_format", None)),  # type: ignore[arg-type]
            agent_processing_paused=bool(getattr(row, "agent_processing_paused", False)),
            agent_runtime=runtime_from_row(row),
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
            embedding_provider_kind=getattr(row, "embedding_provider_kind", None),
            ranking_provider_kind=getattr(row, "ranking_provider_kind", None),
            ai_disabled=row.ai_disabled,
            has_api_key=bool(active and active.has_api_key),
            extras=row.extras,
            harness_mode=coerce_harness_mode(row),
            user_timezone=getattr(row, "user_timezone", None),
            time_format=normalize_time_format(getattr(row, "time_format", None)),  # type: ignore[arg-type]
            agent_processing_paused=bool(getattr(row, "agent_processing_paused", False)),
            agent_runtime=runtime_from_row(row),
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
            if hm not in ("native",):
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

        if "agent_runtime" in data:
            ar = data["agent_runtime"]
            if ar is None:
                prefs.agent_runtime_config = None
            else:
                patch = AgentRuntimeConfigPartial.model_validate(ar)
                prefs.agent_runtime_config = merge_patch_into_stored(
                    prefs.agent_runtime_config if isinstance(prefs.agent_runtime_config, dict) else None,
                    patch,
                )

        if "embedding_provider_kind" in data:
            embed_raw = data["embedding_provider_kind"]
            if embed_raw is None:
                prefs.embedding_provider_kind = None
            else:
                embed_kind = normalize_provider_id(str(embed_raw))
                embed_row = await AIProviderConfigService.get_config(db, user, embed_kind)
                if embed_row is None:
                    raise ValueError(
                        f"No saved configuration for provider {embed_kind!r}; save that provider first."
                    )
                active_raw = prefs.active_provider_kind or prefs.provider_kind
                active_norm = normalize_provider_id(active_raw) if active_raw else None
                if active_norm and embed_kind == active_norm:
                    prefs.embedding_provider_kind = None
                else:
                    prefs.embedding_provider_kind = embed_kind
            await db.flush()

        if "ranking_provider_kind" in data:
            rank_raw = data["ranking_provider_kind"]
            if rank_raw is None:
                prefs.ranking_provider_kind = None
            else:
                rank_kind = normalize_provider_id(str(rank_raw))
                rank_row = await AIProviderConfigService.get_config(db, user, rank_kind)
                if rank_row is None:
                    raise ValueError(
                        f"No saved configuration for provider {rank_kind!r}; save that provider first."
                    )
                active_raw = prefs.active_provider_kind or prefs.provider_kind
                active_norm = normalize_provider_id(active_raw) if active_raw else None
                if active_norm and rank_kind == active_norm:
                    prefs.ranking_provider_kind = None
                else:
                    prefs.ranking_provider_kind = rank_kind
            await db.flush()

        # Per-provider row updates: skip when the payload only touches user-level
        # fields (e.g. ``embedding_provider_kind``, ``ranking_provider_kind``) so we do not create a stray
        # ``user_ai_provider_configs`` row via upsert.
        provider_patch_keys = (
            "provider_kind",
            "base_url",
            "embedding_model",
            "chat_model",
            "classify_model",
            "extras",
            "api_key",
        )
        if any(k in data for k in provider_patch_keys):
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
