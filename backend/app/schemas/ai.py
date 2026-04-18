from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.ai_providers import PROVIDER_IDS, resolve_known_provider_id

# Sentinel clients send in place of api_key to mean "reuse the key that is
# already stored on the user's settings row". This lets the UI test/list
# models against the saved key without re-transmitting it.
STORED_API_KEY_SENTINEL = "__stored__"

ProviderId = Literal[
    "openai",
    "anthropic",
    "ollama",
    "openrouter",
    "litellm",
    "azure_openai",
    "openai_compatible",
]


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

    @field_validator("provider_kind")
    @classmethod
    def _normalize_provider_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = resolve_known_provider_id(value)
        if normalized is None or normalized not in PROVIDER_IDS:
            raise ValueError(f"Unknown provider_kind: {value}")
        return normalized


# --- Provider registry DTOs -------------------------------------------------


class ProviderFieldRead(BaseModel):
    key: str
    label: str
    type: Literal["text", "password", "url", "select"]
    required: bool
    placeholder: str = ""
    help: str = ""
    secret: bool = False
    default: str | None = None
    options: list[str] | None = None


class ProviderRead(BaseModel):
    id: str
    label: str
    description: str
    auth_kind: Literal["bearer", "x-api-key", "api-key-header", "none"]
    fields: list[ProviderFieldRead]
    default_base_url: str | None = None
    default_chat_model: str | None = None
    default_embedding_model: str | None = None
    default_classify_model: str | None = None
    docs_url: str | None = None
    model_list_is_deployments: bool = False
    chat_openai_compatible: bool = True
    supports_capability_filter: bool = False


# --- Test / list models request-response ------------------------------------


class ProviderConfigRequest(BaseModel):
    """Transient provider configuration used for test / list-models calls.

    When ``api_key`` equals ``STORED_API_KEY_SENTINEL`` the route swaps in the
    user's saved key. ``base_url`` may be blank if the provider has a default.
    """

    provider_id: ProviderId
    api_key: str | None = None
    base_url: str | None = None
    extras: dict[str, Any] | None = None


class TestConnectionResult(BaseModel):
    ok: bool
    message: str
    code: str | None = None
    detail: str | None = None


class ModelInfoRead(BaseModel):
    id: str
    label: str
    capability: Literal["chat", "embedding", "unknown"] = "unknown"


class ListModelsResponse(BaseModel):
    ok: bool
    models: list[ModelInfoRead]
    error: TestConnectionResult | None = None


# --- Unchanged -------------------------------------------------------------


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
