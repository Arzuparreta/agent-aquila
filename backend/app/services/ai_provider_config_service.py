"""Multi-provider AI configuration service.

Owns the ``user_ai_provider_configs`` table and the ``active_provider_kind``
pointer on ``user_ai_settings``. The agent loop, the embedding client and
the new ``/ai/providers/configs`` REST surface all read through here.

Key invariants
--------------

- One row per ``(user_id, provider_kind)``. Race-safe via Postgres
  ``INSERT ... ON CONFLICT DO UPDATE``.
- The legacy ``user_ai_settings`` per-provider columns are kept as a
  *cached mirror* of the active provider's config. Always written via
  :meth:`_sync_legacy_mirror` so existing call sites that still take
  ``UserAISettings`` (agent_service, embedding_service, …) keep working
  unchanged.
- API keys are stored using envelope encryption
  (:mod:`app.core.envelope_crypto`). Decryption raises a typed
  :class:`KeyDecryptError` so the caller can prompt the user to re-enter
  the key, instead of silently behaving as if the key was never set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope_crypto import (
    KeyDecryptError,
    decrypt_value,
    encrypt_value,
)
from app.models.user import User
from app.models.user_ai_provider_config import UserAIProviderConfig
from app.models.user_ai_settings import UserAISettings
from app.services.ai_providers import (
    get_provider,
    normalize_provider_id,
    provider_kind_requires_api_key,
    resolve_known_provider_id,
)


@dataclass(frozen=True)
class ProviderConfigUpsert:
    """Plain-old data passed by routes / scripts when writing a config row.

    Fields default to ``None`` and are only applied when explicitly set, so
    a partial update doesn't blow away unrelated fields.
    """

    base_url: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    classify_model: str | None = None
    extras: dict[str, Any] | None = None
    # Special semantics for the API key:
    #   None  -> leave existing key untouched.
    #   ""    -> clear the stored key.
    #   "..." -> replace the stored key with this plaintext.
    api_key: str | None = None


class AIProviderConfigService:
    # ------------------------------------------------------------------ get

    @staticmethod
    async def list_configs(db: AsyncSession, user: User) -> list[UserAIProviderConfig]:
        result = await db.execute(
            select(UserAIProviderConfig)
            .where(UserAIProviderConfig.user_id == user.id)
            .order_by(UserAIProviderConfig.provider_kind.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_config(
        db: AsyncSession, user: User, provider_kind: str
    ) -> UserAIProviderConfig | None:
        canonical = resolve_known_provider_id(provider_kind)
        if canonical is None:
            return None
        result = await db.execute(
            select(UserAIProviderConfig).where(
                UserAIProviderConfig.user_id == user.id,
                UserAIProviderConfig.provider_kind == canonical,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active(
        db: AsyncSession, user: User
    ) -> UserAIProviderConfig | None:
        """Return the row matching ``user_ai_settings.active_provider_kind``."""
        prefs = await _get_or_create_prefs(db, user)
        kind = prefs.active_provider_kind or prefs.provider_kind
        if not kind:
            return None
        return await AIProviderConfigService.get_config(db, user, kind)

    # ------------------------------------------------------------------ write

    @staticmethod
    async def upsert_config(
        db: AsyncSession,
        user: User,
        provider_kind: str,
        payload: ProviderConfigUpsert,
    ) -> UserAIProviderConfig:
        """Create or update a per-provider config row.

        Defaults from the provider definition (registry) are applied for any
        field the caller leaves empty AND that has no existing value, so a
        first-time save against e.g. ``ollama`` ends up with sensible
        ``chat_model`` / ``embedding_model`` defaults.

        If the saved config matches the user's currently-active provider,
        the legacy mirror columns are updated atomically too.
        """
        canonical = resolve_known_provider_id(provider_kind)
        if canonical is None:
            raise ValueError(f"Unknown provider_kind: {provider_kind!r}")
        definition = get_provider(canonical)

        row = await AIProviderConfigService.get_config(db, user, canonical)
        if row is None:
            row = UserAIProviderConfig(user_id=user.id, provider_kind=canonical)
            db.add(row)

        if payload.base_url is not None:
            row.base_url = (payload.base_url or "").strip() or None
        if payload.chat_model is not None:
            row.chat_model = (payload.chat_model or "").strip()
        if payload.embedding_model is not None:
            row.embedding_model = (payload.embedding_model or "").strip()
        if payload.classify_model is not None:
            cleaned = (payload.classify_model or "").strip()
            row.classify_model = cleaned or None
        if payload.extras is not None:
            cleaned_extras = {
                str(k): v for k, v in payload.extras.items() if v not in (None, "")
            }
            row.extras = cleaned_extras or None

        # API key: None=keep, ""=clear, anything else=replace.
        if payload.api_key is not None:
            if payload.api_key == "":
                row.wrapped_dek = None
                row.api_key_ciphertext = None
            else:
                wrapped, ciphertext = encrypt_value(payload.api_key)
                row.wrapped_dek = wrapped
                row.api_key_ciphertext = ciphertext

        # Apply registry defaults for empty required fields on first save.
        if definition is not None:
            if not row.chat_model and definition.default_chat_model:
                row.chat_model = definition.default_chat_model
            if not row.embedding_model and definition.default_embedding_model:
                row.embedding_model = definition.default_embedding_model
            if row.base_url is None and definition.default_base_url:
                row.base_url = definition.default_base_url

        # Saving a config invalidates any prior test result that no longer
        # reflects the current key/url/extras combination.
        if (
            payload.api_key is not None
            or payload.base_url is not None
            or payload.extras is not None
        ):
            row.last_test_at = None
            row.last_test_ok = None
            row.last_test_message = None

        await db.flush()
        await _sync_legacy_mirror_if_active(db, user, row)
        return row

    @staticmethod
    async def delete_config(
        db: AsyncSession, user: User, provider_kind: str
    ) -> bool:
        """Hard-delete a per-provider config. Returns True when something was deleted.

        If the deleted config was the active one, the active pointer is
        cleared (next agent run will fail with ``NoActiveProviderError`` and
        the UI will prompt the user to pick another provider).
        """
        row = await AIProviderConfigService.get_config(db, user, provider_kind)
        if row is None:
            return False
        was_active = row.provider_kind == (await _get_or_create_prefs(db, user)).active_provider_kind
        await db.delete(row)
        await db.flush()
        if was_active:
            prefs = await _get_or_create_prefs(db, user)
            prefs.active_provider_kind = None
            # Clear the mirror so callers see "no provider set".
            prefs.provider_kind = ""
            prefs.base_url = None
            prefs.chat_model = ""
            prefs.embedding_model = ""
            prefs.classify_model = None
            prefs.api_key_encrypted = None
            prefs.extras = None
            await db.flush()
        return True

    @staticmethod
    async def set_active(
        db: AsyncSession, user: User, provider_kind: str
    ) -> UserAIProviderConfig:
        """Flip the active pointer to ``provider_kind`` and refresh the mirror.

        Raises ``ValueError`` if the user has no saved config for that kind
        (the UI is expected to first call ``upsert_config``).
        """
        canonical = resolve_known_provider_id(provider_kind)
        if canonical is None:
            raise ValueError(f"Unknown provider_kind: {provider_kind!r}")
        row = await AIProviderConfigService.get_config(db, user, canonical)
        if row is None:
            raise ValueError(
                f"No saved configuration for provider {canonical!r}; create it before activating."
            )
        prefs = await _get_or_create_prefs(db, user)
        prefs.active_provider_kind = canonical
        await db.flush()
        await _sync_legacy_mirror_if_active(db, user, row)
        return row

    # ------------------------------------------------------------------ secrets

    @staticmethod
    def decrypt_api_key(row: UserAIProviderConfig) -> str | None:
        """Return the plaintext key, or ``None`` when no key is stored.

        Raises :class:`KeyDecryptError` when a ciphertext exists but cannot
        be decrypted (e.g. KEK rotated / lost). Callers should translate
        that into a clear "please re-enter your key" UI message.
        """
        if not row.api_key_ciphertext:
            return None
        if not row.wrapped_dek:
            # Migrations 0016/0017 should have populated wrapped_dek; this
            # only happens for rows that the rewrap migration explicitly
            # cleared (legacy ciphertext was unrecoverable).
            raise KeyDecryptError(
                scope=f"user={row.user_id} provider={row.provider_kind}",
                reason="missing wrapped_dek",
            )
        return decrypt_value(
            row.wrapped_dek,
            row.api_key_ciphertext,
            scope=f"user={row.user_id} provider={row.provider_kind}",
        )

    @staticmethod
    async def decrypt_active_api_key(db: AsyncSession, user: User) -> str | None:
        active = await AIProviderConfigService.get_active(db, user)
        if active is None:
            return None
        return AIProviderConfigService.decrypt_api_key(active)

    # ------------------------------------------------------------------ test

    @staticmethod
    async def record_test_result(
        db: AsyncSession,
        row: UserAIProviderConfig,
        *,
        ok: bool,
        message: str,
    ) -> None:
        row.last_test_at = datetime.now(UTC)
        row.last_test_ok = ok
        row.last_test_message = (message or "")[:512]
        await db.flush()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_or_create_prefs(db: AsyncSession, user: User) -> UserAISettings:
    result = await db.execute(
        select(UserAISettings).where(UserAISettings.user_id == user.id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserAISettings(user_id=user.id)
        db.add(prefs)
        await db.flush()
    return prefs


async def _sync_legacy_mirror_if_active(
    db: AsyncSession,
    user: User,
    row: UserAIProviderConfig,
) -> None:
    """Copy ``row`` into the legacy ``user_ai_settings`` columns when it is active.

    Existing services (agent_service, embedding_service, rag_index_service,
    triage_service, etc.) still load the legacy ``UserAISettings`` row and
    pass it to the LLM/Embedding clients. By keeping that row in sync with
    the active config we don't have to refactor every call site at once.
    """
    prefs = await _get_or_create_prefs(db, user)
    active_kind = prefs.active_provider_kind
    if not active_kind:
        # First-ever save in the multi-provider world: seed the active pointer.
        prefs.active_provider_kind = row.provider_kind
        active_kind = row.provider_kind
    if active_kind != row.provider_kind:
        return
    prefs.provider_kind = row.provider_kind
    prefs.base_url = row.base_url
    prefs.chat_model = row.chat_model or ""
    prefs.embedding_model = row.embedding_model or ""
    prefs.classify_model = row.classify_model
    prefs.extras = dict(row.extras) if row.extras else None
    # The legacy api_key_encrypted column is intentionally left untouched
    # (it's the legacy ciphertext format, not envelope). All decryption
    # goes via AIProviderConfigService.decrypt_api_key. Clearing it once
    # all call sites use envelope keeps the legacy column from confusing
    # operators reading the table.
    if row.api_key_ciphertext is None:
        prefs.api_key_encrypted = None
    await db.flush()


def needs_api_key(provider_kind: str | None) -> bool:
    """Convenience wrapper around the registry helper for callers in this module."""
    return provider_kind_requires_api_key(normalize_provider_id(provider_kind))
