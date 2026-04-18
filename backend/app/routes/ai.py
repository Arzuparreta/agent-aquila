from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.schemas.agent import RagBackfillRequest
from app.schemas.ai import (
    STORED_API_KEY_SENTINEL,
    ListModelsResponse,
    ModelInfoRead,
    ProviderConfigRequest,
    ProviderFieldRead,
    ProviderRead,
    SemanticSearchHit,
    SemanticSearchRequest,
    TestConnectionResult,
    UserAISettingsRead,
    UserAISettingsUpdate,
)
from app.services.ai_providers import list_providers
from app.services.ai_providers.adapters import (
    ProviderConfig,
    safe_list_models,
    test_connection as adapter_test_connection,
)
from app.services.embedding_service import EmbeddingService
from app.services.semantic_search_service import SemanticSearchService
from app.services.user_ai_settings_service import UserAISettingsService

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(get_current_user)])


@router.get("/settings", response_model=UserAISettingsRead)
async def get_ai_settings(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> UserAISettingsRead:
    row = await UserAISettingsService.get_or_create(db, current_user)
    await db.commit()
    await db.refresh(row)
    return UserAISettingsService.to_read(row)


@router.patch("/settings", response_model=UserAISettingsRead)
async def patch_ai_settings(
    payload: UserAISettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserAISettingsRead:
    return await UserAISettingsService.update_settings(db, current_user, payload)


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


async def _resolve_config(
    payload: ProviderConfigRequest,
    db: AsyncSession,
    current_user: User,
) -> ProviderConfig:
    """Turn a request DTO into an in-memory ProviderConfig.

    If ``api_key`` equals the stored-sentinel, swap in the decrypted key from
    the user's saved settings. A ``None`` / empty api_key stays as ``None``.
    """
    raw_key = payload.api_key
    resolved_key: str | None
    if raw_key == STORED_API_KEY_SENTINEL:
        resolved_key = await UserAISettingsService.get_api_key(db, current_user)
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
    return TestConnectionResult(ok=result.ok, message=result.message, code=result.code, detail=result.detail)


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
            error=TestConnectionResult(ok=False, message=error.message, code=error.code, detail=error.detail),
        )
    filtered = models
    if capability in ("chat", "embedding"):
        # If no models advertise their capability (common on Ollama, custom
        # servers), keep the full list so the user can still pick something.
        typed = [m for m in models if m.capability == capability]
        filtered = typed or models
    return ListModelsResponse(
        ok=True,
        models=[ModelInfoRead(id=m.id, label=m.label, capability=m.capability) for m in filtered],
    )


@router.post("/search", response_model=list[SemanticSearchHit])
async def semantic_search(
    payload: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SemanticSearchHit]:
    return await SemanticSearchService.search(db, current_user, payload.query, payload.limit_per_type)


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
