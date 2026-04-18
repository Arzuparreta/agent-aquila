from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.ai import SemanticSearchHit, SemanticSearchRequest, UserAISettingsRead, UserAISettingsUpdate
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
