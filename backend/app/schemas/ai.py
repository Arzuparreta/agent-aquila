from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.ai_providers import PROVIDER_IDS, resolve_known_provider_id

# Sentinel clients send in place of api_key to mean "reuse the key that is
# already stored on the user's settings row". This lets the UI test/list
# models against the saved key without re-transmitting it.
STORED_API_KEY_SENTINEL = "__stored__"

# NOTE: do NOT hardcode the provider list here. The registry
# (``app.services.ai_providers.registry``) is the single source of truth
# and is exposed as ``PROVIDER_IDS``. Schemas that accept a provider id
# validate against ``PROVIDER_IDS`` via the validator below, so adding a
# new provider to the registry auto-flows everywhere without schema edits.


class UserAISettingsRead(BaseModel):
    provider_kind: str
    base_url: str | None = None
    embedding_model: str
    chat_model: str
    classify_model: str | None = None
    embedding_provider_kind: str | None = Field(
        default=None,
        description=(
            "When set, agent memory embeddings use this provider's saved row instead of the active provider."
        ),
    )
    ai_disabled: bool
    has_api_key: bool
    extras: dict[str, Any] | None = None
    harness_mode: Literal["auto", "native", "prompted"] = "auto"
    user_timezone: str | None = None
    time_format: Literal["auto", "12", "24"] = "auto"
    agent_processing_paused: bool = False


class UserAISettingsUpdate(BaseModel):
    provider_kind: str | None = None
    base_url: str | None = None
    embedding_model: str | None = None
    chat_model: str | None = None
    classify_model: str | None = None
    embedding_provider_kind: str | None = None
    ai_disabled: bool | None = None
    harness_mode: Literal["auto", "native", "prompted"] | None = None
    user_timezone: str | None = None
    time_format: Literal["auto", "12", "24"] | None = None
    agent_processing_paused: bool | None = None
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

    @field_validator("embedding_provider_kind")
    @classmethod
    def _normalize_embedding_provider_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            return None
        normalized = resolve_known_provider_id(stripped)
        if normalized is None or normalized not in PROVIDER_IDS:
            raise ValueError(f"Unknown embedding_provider_kind: {value}")
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
    suggested_chat_models: list[str] | None = None


# --- Test / list models request-response ------------------------------------


class ProviderConfigRequest(BaseModel):
    """Transient provider configuration used for test / list-models calls.

    When ``api_key`` equals ``STORED_API_KEY_SENTINEL`` the route swaps in the
    user's saved key. ``base_url`` may be blank if the provider has a default.
    """

    provider_id: str
    api_key: str | None = None
    base_url: str | None = None
    extras: dict[str, Any] | None = None

    @field_validator("provider_id")
    @classmethod
    def _normalize_provider_id(cls, value: str) -> str:
        normalized = resolve_known_provider_id(value)
        if normalized is None or normalized not in PROVIDER_IDS:
            raise ValueError(
                f"Unknown provider_id: {value!r}. Known: {', '.join(PROVIDER_IDS)}."
            )
        return normalized


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


# --- Multi-provider configs (new in 0016) ----------------------------------


class ProviderTestStatus(BaseModel):
    """Outcome of the most recent connection test for a saved config."""

    ok: bool | None = None
    at: datetime | None = None
    message: str | None = None


class ProviderConfigRead(BaseModel):
    """One persisted ``user_ai_provider_configs`` row, as seen by the UI."""

    provider_kind: str
    base_url: str | None = None
    chat_model: str = ""
    embedding_model: str = ""
    classify_model: str | None = None
    extras: dict[str, Any] | None = None
    has_api_key: bool = False
    is_active: bool = False
    last_test: ProviderTestStatus = Field(default_factory=ProviderTestStatus)
    created_at: datetime
    updated_at: datetime


class ProviderConfigsResponse(BaseModel):
    """Top-level shape returned by ``GET /ai/providers/configs``."""

    active_provider_kind: str | None = None
    embedding_provider_kind: str | None = None
    ai_disabled: bool = False
    harness_mode: Literal["auto", "native", "prompted"] = "auto"
    user_timezone: str | None = None
    time_format: Literal["auto", "12", "24"] = "auto"
    configs: list[ProviderConfigRead] = Field(default_factory=list)


class ProviderConfigUpsertRequest(BaseModel):
    """Payload for ``PUT /ai/providers/configs/{kind}``.

    Field semantics mirror :class:`UserAISettingsUpdate`:

    - Unset fields are ignored (partial update).
    - ``api_key`` of ``""`` clears the stored key; any other non-null value
      replaces it; ``None`` (the default) leaves it untouched.
    - ``classify_model`` of ``""`` clears the value.
    """

    base_url: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    classify_model: str | None = None
    extras: dict[str, Any] | None = None
    api_key: str | None = Field(
        default=None,
        description=(
            "Send a non-empty string to replace the stored key; an empty "
            "string clears it; omit/null to keep the existing key."
        ),
    )


class SetActiveProviderRequest(BaseModel):
    provider_kind: str

    @field_validator("provider_kind")
    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = resolve_known_provider_id(value)
        if normalized is None or normalized not in PROVIDER_IDS:
            raise ValueError(f"Unknown provider_kind: {value!r}")
        return normalized


class AIHealthResponse(BaseModel):
    """Light-weight status payload for the chat top-bar indicator."""

    ai_disabled: bool = False
    active_provider_kind: str | None = None
    has_api_key: bool = False
    chat_model: str | None = None
    last_test: ProviderTestStatus = Field(default_factory=ProviderTestStatus)
    needs_setup: bool = True
    message: str | None = None
