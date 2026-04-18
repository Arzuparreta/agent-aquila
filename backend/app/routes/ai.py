from __future__ import annotations

from fastapi import APIRouter, Depends
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
from app.schemas.ai import SemanticSearchHit, SemanticSearchRequest, UserAISettingsRead, UserAISettingsUpdate
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
