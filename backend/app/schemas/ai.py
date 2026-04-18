from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UserAISettingsRead(BaseModel):
    provider_kind: str
    base_url: str | None = None
    embedding_model: str
    chat_model: str
    classify_model: str | None = None
    ai_disabled: bool
    has_api_key: bool
    extras: dict[str, Any] | None = None


class UserAISettingsUpdate(BaseModel):
    provider_kind: str | None = None
    base_url: str | None = None
    embedding_model: str | None = None
    chat_model: str | None = None
    classify_model: str | None = None
    ai_disabled: bool | None = None
    api_key: str | None = Field(
        default=None,
        description="When set, replaces the stored key. Send empty string to clear.",
    )
    extras: dict[str, Any] | None = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit_per_type: int = Field(default=5, ge=1, le=20)


class SemanticSearchHit(BaseModel):
    entity_type: str
    entity_id: int
    score: float
    title: str
    snippet: str
    citation: str
    chunk_id: int | None = None
    match_sources: list[str] | None = None
    rrf_score: float | None = None


class EmailDraftResponse(BaseModel):
    draft: str
    model: str
