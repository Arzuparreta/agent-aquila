from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.envelope_crypto import KeyDecryptError
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.models.user_ai_provider_config import UserAIProviderConfig
from app.models.user_ai_settings import UserAISettings
from app.schemas.agent import RagBackfillRequest
from app.schemas.ai import (
    STORED_API_KEY_SENTINEL,
    AIHealthResponse,
    ListModelsResponse,
    ModelInfoRead,
    ProviderConfigRead,
    ProviderConfigRequest,
    ProviderConfigsResponse,
    ProviderConfigUpsertRequest,
    ProviderFieldRead,
    ProviderRead,
    ProviderTestStatus,
    SemanticSearchHit,
    SemanticSearchRequest,
    SetActiveProviderRequest,
    TestConnectionResult,
    UserAISettingsRead,
    UserAISettingsUpdate,
)
from app.services.ai_provider_config_service import (
    AIProviderConfigService,
    ProviderConfigUpsert,
)
from app.services.ai_providers import (
    list_providers,
    normalize_provider_id,
    resolve_known_provider_id,
)
from app.services.ai_providers.adapters import (
    ProviderConfig,
    safe_list_models,
    test_connection as adapter_test_connection,
)
from app.services.embedding_service import EmbeddingService
from app.services.semantic_search_service import SemanticSearchService
from app.services.user_ai_settings_service import UserAISettingsService

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Legacy single-config shim ("active provider" lens over the new tables)
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=UserAISettingsRead)
async def get_ai_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserAISettingsRead:
    """Return the active provider's config in the legacy shape.

    Kept for clients that haven't moved to ``/ai/providers/configs`` yet.
    Slated for removal once the frontend is fully migrated.
    """
    row = await UserAISettingsService.get_or_create(db, current_user)
    await db.commit()
    await db.refresh(row)
    return await UserAISettingsService.to_read_async(db, current_user, row)


@router.patch("/settings", response_model=UserAISettingsRead)
async def patch_ai_settings(
    payload: UserAISettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserAISettingsRead:
    """Compatibility writer; routes the update into the new multi-config tables."""
    return await UserAISettingsService.update_settings(db, current_user, payload)


# ---------------------------------------------------------------------------
# Static provider registry
# ---------------------------------------------------------------------------


@router.get("/providers", response_model=list[ProviderRead])
async def get_providers() -> list[ProviderRead]:
    """Read-only registry of supported AI providers.

    Requires auth (inherited from the router) but returns the same static
    data for every user. The frontend uses this to render the provider
    picker and field layout dynamically instead of duplicating provider
    metadata in TypeScript.
    """
    out: list[ProviderRead] = []
    for definition in list_providers():
        fields = [
            ProviderFieldRead(
                key=f.key,
                label=f.label,
                type=f.type,
                required=f.required,
                placeholder=f.placeholder,
                help=f.help,
                secret=f.secret,
                default=f.default,
                options=list(f.options) if f.options else None,
            )
            for f in definition.fields
        ]
        out.append(
            ProviderRead(
                id=definition.id,
                label=definition.label,
                description=definition.description,
                auth_kind=definition.auth_kind,
                fields=fields,
                default_base_url=definition.default_base_url,
                default_chat_model=definition.default_chat_model,
                default_embedding_model=definition.default_embedding_model,
                default_classify_model=definition.default_classify_model,
                docs_url=definition.docs_url,
                model_list_is_deployments=definition.model_list_is_deployments,
                chat_openai_compatible=definition.chat_openai_compatible,
                supports_capability_filter=definition.supports_capability_filter,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Multi-provider configs (the real new surface)
# ---------------------------------------------------------------------------


def _row_to_read(row: UserAIProviderConfig, *, active_kind: str | None) -> ProviderConfigRead:
    return ProviderConfigRead(
        provider_kind=row.provider_kind,
        base_url=row.base_url,
        chat_model=row.chat_model or "",
        embedding_model=row.embedding_model or "",
        classify_model=row.classify_model,
        extras=dict(row.extras) if row.extras else None,
        has_api_key=row.has_api_key,
        is_active=(row.provider_kind == active_kind),
        last_test=ProviderTestStatus(
            ok=row.last_test_ok,
            at=row.last_test_at,
            message=row.last_test_message,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _prefs(db: AsyncSession, user: User) -> UserAISettings:
    return await UserAISettingsService.get_or_create(db, user)


@router.get("/providers/configs", response_model=ProviderConfigsResponse)
async def list_provider_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProviderConfigsResponse:
    rows = await AIProviderConfigService.list_configs(db, current_user)
    prefs = await _prefs(db, current_user)
    active = prefs.active_provider_kind or (prefs.provider_kind or None)
    return ProviderConfigsResponse(
        active_provider_kind=active,
        ai_disabled=prefs.ai_disabled,
        configs=[_row_to_read(r, active_kind=active) for r in rows],
    )


@router.put("/providers/configs/{kind}", response_model=ProviderConfigRead)
async def upsert_provider_config(
    kind: str,
    payload: ProviderConfigUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProviderConfigRead:
    """Idempotent upsert of one provider's config row.

    Saving never touches *other* providers — the artist can move freely
    between providers without losing keys. Pass ``api_key=""`` to clear a
    saved key, or omit it to keep the existing one.
    """
    canonical = resolve_known_provider_id(kind)
    if canonical is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider {kind!r}")
    row = await AIProviderConfigService.upsert_config(
        db,
        current_user,
        canonical,
        ProviderConfigUpsert(
            base_url=payload.base_url,
            chat_model=payload.chat_model,
            embedding_model=payload.embedding_model,
            classify_model=payload.classify_model,
            extras=payload.extras,
            api_key=payload.api_key,
        ),
    )
    await db.commit()
    await db.refresh(row)
    prefs = await _prefs(db, current_user)
    return _row_to_read(row, active_kind=prefs.active_provider_kind)


@router.delete("/providers/configs/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(
    kind: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    canonical = resolve_known_provider_id(kind)
    if canonical is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider {kind!r}")
    deleted = await AIProviderConfigService.delete_config(db, current_user, canonical)
    if not deleted:
        raise HTTPException(status_code=404, detail="No config to delete")
    await db.commit()
    return None


@router.post("/providers/active", response_model=ProviderConfigRead)
async def set_active_provider(
    payload: SetActiveProviderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProviderConfigRead:
    """Flip the active pointer to a saved config (no key re-entry needed)."""
    try:
        row = await AIProviderConfigService.set_active(
            db, current_user, payload.provider_kind
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    prefs = await _prefs(db, current_user)
    return _row_to_read(row, active_kind=prefs.active_provider_kind)


@router.post("/providers/configs/{kind}/test", response_model=TestConnectionResult)
async def test_saved_config(
    kind: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestConnectionResult:
    """Test a *saved* config (no need to re-send the key in the payload).

    Persists the outcome into ``last_test_*`` so the UI can render the
    green/red status pill without an extra round-trip.
    """
    canonical = resolve_known_provider_id(kind)
    if canonical is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider {kind!r}")
    row = await AIProviderConfigService.get_config(db, current_user, canonical)
    if row is None:
        raise HTTPException(status_code=404, detail="No saved config for this provider")
    try:
        api_key = AIProviderConfigService.decrypt_api_key(row)
    except KeyDecryptError as exc:
        # Re-raised so the global handler returns the structured 409.
        raise exc
    cfg = ProviderConfig(
        provider_id=row.provider_kind,
        api_key=api_key,
        base_url=row.base_url,
        extras=dict(row.extras or {}),
    )
    result = await adapter_test_connection(cfg)
    await AIProviderConfigService.record_test_result(
        db, row, ok=result.ok, message=result.message
    )
    await db.commit()
    return TestConnectionResult(
        ok=result.ok, message=result.message, code=result.code, detail=result.detail
    )


# ---------------------------------------------------------------------------
# Health endpoint for the chat top-bar pill
# ---------------------------------------------------------------------------


@router.get("/health", response_model=AIHealthResponse)
async def ai_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AIHealthResponse:
    prefs = await _prefs(db, current_user)
    if prefs.ai_disabled:
        return AIHealthResponse(
            ai_disabled=True,
            active_provider_kind=prefs.active_provider_kind,
            chat_model=prefs.chat_model or None,
            needs_setup=False,
            message="AI is disabled in Settings.",
        )
    active = await AIProviderConfigService.get_active(db, current_user)
    if active is None:
        return AIHealthResponse(
            active_provider_kind=None,
            needs_setup=True,
            message="No active AI provider — open Settings → AI to choose one.",
        )
    return AIHealthResponse(
        ai_disabled=False,
        active_provider_kind=active.provider_kind,
        has_api_key=active.has_api_key,
        chat_model=active.chat_model or None,
        last_test=ProviderTestStatus(
            ok=active.last_test_ok,
            at=active.last_test_at,
            message=active.last_test_message,
        ),
        needs_setup=False,
    )


# ---------------------------------------------------------------------------
# Transient test / list-models (still used by the form UI)
# ---------------------------------------------------------------------------


async def _resolve_config(
    payload: ProviderConfigRequest,
    db: AsyncSession,
    current_user: User,
) -> ProviderConfig:
    """Turn a request DTO into an in-memory ProviderConfig.

    If ``api_key`` equals the stored-sentinel, swap in the decrypted key
    from the saved config for that provider. A ``None`` / empty api_key
    stays as ``None``.
    """
    raw_key = payload.api_key
    resolved_key: str | None
    if raw_key == STORED_API_KEY_SENTINEL:
        canonical = normalize_provider_id(payload.provider_id)
        saved = await AIProviderConfigService.get_config(db, current_user, canonical)
        try:
            resolved_key = (
                AIProviderConfigService.decrypt_api_key(saved) if saved else None
            )
        except KeyDecryptError:
            # Surface as "no key" so the test flow returns the standard
            # missing_field code instead of a 500.
            resolved_key = None
    else:
        resolved_key = raw_key

    return ProviderConfig(
        provider_id=payload.provider_id,
        api_key=resolved_key,
        base_url=(payload.base_url or None),
        extras=dict(payload.extras or {}),
    )


@router.post("/providers/test", response_model=TestConnectionResult)
async def test_provider(
    payload: ProviderConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestConnectionResult:
    cfg = await _resolve_config(payload, db, current_user)
    result = await adapter_test_connection(cfg)
    return TestConnectionResult(
        ok=result.ok, message=result.message, code=result.code, detail=result.detail
    )


@router.post("/providers/models", response_model=ListModelsResponse)
async def list_provider_models(
    payload: ProviderConfigRequest,
    capability: str | None = Query(default=None, pattern="^(chat|embedding)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ListModelsResponse:
    cfg = await _resolve_config(payload, db, current_user)
    models, error = await safe_list_models(cfg)
    if error is not None:
        return ListModelsResponse(
            ok=False,
            models=[],
            error=TestConnectionResult(
                ok=False, message=error.message, code=error.code, detail=error.detail
            ),
        )
    filtered = models
    if capability in ("chat", "embedding"):
        # If no models advertise their capability (common on Ollama, custom
        # servers), keep the full list so the user can still pick something.
        typed = [m for m in models if m.capability == capability]
        filtered = typed or models
    return ListModelsResponse(
        ok=True,
        models=[
            ModelInfoRead(id=m.id, label=m.label, capability=m.capability)
            for m in filtered
        ],
    )


# ---------------------------------------------------------------------------
# Misc unrelated endpoints kept verbatim
# ---------------------------------------------------------------------------


@router.post("/search", response_model=list[SemanticSearchHit])
async def semantic_search(
    payload: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SemanticSearchHit]:
    return await SemanticSearchService.search(
        db, current_user, payload.query, payload.limit_per_type
    )


@router.post("/rag/backfill")
async def rag_backfill(
    payload: RagBackfillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Re-embed up to N rows per table (chunked RAG index). Run after upgrades or API key changes."""
    lim = payload.limit_per_table
    counts: dict[str, int] = {}
    for model, key, sync in (
        (Contact, "contacts", EmbeddingService.sync_contact),
        (Email, "emails", EmbeddingService.sync_email),
        (Deal, "deals", EmbeddingService.sync_deal),
        (Event, "events", EmbeddingService.sync_event),
    ):
        ids = (await db.execute(select(model.id).order_by(model.id).limit(lim))).scalars().all()
        for eid in ids:
            await sync(db, current_user.id, int(eid))
        counts[key] = len(ids)
    await db.commit()
    return counts
