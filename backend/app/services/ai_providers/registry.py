"""Typed registry of supported AI providers.

Each entry declares how the UI should render its fields and how the backend
should authenticate, test, and list models for that provider. The registry is
intentionally static data: the adapter layer (``adapters.py``) reads these
definitions at runtime to issue HTTP requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["text", "password", "url", "select"]
AuthKind = Literal["bearer", "x-api-key", "api-key-header", "none"]
TestStrategy = Literal["list_models", "ollama_tags", "azure_deployments", "anthropic_models"]


@dataclass(frozen=True)
class ProviderField:
    """A single input the user has to fill for a provider."""

    key: str
    label: str
    type: FieldType = "text"
    required: bool = False
    placeholder: str = ""
    help: str = ""
    secret: bool = False
    default: str | None = None
    options: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    label: str
    description: str
    auth_kind: AuthKind
    fields: tuple[ProviderField, ...]
    default_base_url: str | None
    default_chat_model: str | None
    default_embedding_model: str | None
    default_classify_model: str | None
    test_strategy: TestStrategy
    docs_url: str | None = None
    # Model capability hints the adapter can return: "chat", "embedding", "unknown".
    supports_capability_filter: bool = False
    # If True, the model list for this provider reflects deployment names
    # rather than canonical model IDs (Azure).
    model_list_is_deployments: bool = False
    # If True, chat execution against this provider requires a custom client
    # because the HTTP shape is not OpenAI-compatible.
    chat_openai_compatible: bool = True


_API_KEY_FIELD = ProviderField(
    key="api_key",
    label="API key",
    type="password",
    required=True,
    secret=True,
    placeholder="sk-...",
    help="Stored encrypted at rest. Leave blank on save to keep the existing key.",
)

_OPTIONAL_API_KEY_FIELD = ProviderField(
    key="api_key",
    label="API key (optional)",
    type="password",
    required=False,
    secret=True,
    help="Only needed if your proxy requires one. Stored encrypted.",
)


PROVIDERS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        id="openai",
        label="OpenAI",
        description="Official OpenAI API. Uses gpt-4o and text-embedding-3 models.",
        auth_kind="bearer",
        fields=(_API_KEY_FIELD,),
        default_base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
        default_embedding_model="text-embedding-3-small",
        default_classify_model=None,
        test_strategy="list_models",
        docs_url="https://platform.openai.com/api-keys",
        supports_capability_filter=True,
    ),
    ProviderDefinition(
        id="anthropic",
        label="Anthropic",
        description="Claude models. Uses the native Anthropic Messages API.",
        auth_kind="x-api-key",
        fields=(_API_KEY_FIELD,),
        default_base_url="https://api.anthropic.com/v1",
        default_chat_model="claude-3-5-sonnet-latest",
        default_embedding_model=None,
        default_classify_model=None,
        test_strategy="anthropic_models",
        docs_url="https://console.anthropic.com/settings/keys",
        chat_openai_compatible=False,
    ),
    ProviderDefinition(
        id="ollama",
        label="Ollama",
        description="Local models via Ollama. No API key required.",
        auth_kind="none",
        fields=(
            ProviderField(
                key="base_url",
                label="Server URL",
                type="url",
                required=True,
                placeholder="http://localhost:11434",
                help="URL where your Ollama server is reachable.",
                default="http://localhost:11434",
            ),
        ),
        default_base_url="http://localhost:11434",
        default_chat_model=None,
        default_embedding_model=None,
        default_classify_model=None,
        test_strategy="ollama_tags",
        docs_url="https://ollama.com/download",
    ),
    ProviderDefinition(
        id="openrouter",
        label="OpenRouter",
        description="Unified access to 100+ models from a single API key.",
        auth_kind="bearer",
        fields=(
            _API_KEY_FIELD,
            ProviderField(
                key="openrouter_referer",
                label="HTTP Referer (optional)",
                type="url",
                placeholder="https://your-app.example.com",
                help="OpenRouter uses this to attribute usage to your app.",
            ),
            ProviderField(
                key="openrouter_title",
                label="App title (optional)",
                type="text",
                placeholder="Artist CRM",
                help="Shown on OpenRouter's rankings page.",
            ),
        ),
        default_base_url="https://openrouter.ai/api/v1",
        default_chat_model="openai/gpt-4o-mini",
        default_embedding_model="openai/text-embedding-3-small",
        default_classify_model=None,
        test_strategy="list_models",
        docs_url="https://openrouter.ai/keys",
    ),
    ProviderDefinition(
        id="litellm",
        label="LiteLLM Proxy",
        description="Self-hosted LiteLLM proxy exposing any provider via the OpenAI API shape.",
        auth_kind="bearer",
        fields=(
            ProviderField(
                key="base_url",
                label="Proxy URL",
                type="url",
                required=True,
                placeholder="http://localhost:4000",
                help="Root URL of your LiteLLM proxy (no trailing slash).",
            ),
            _OPTIONAL_API_KEY_FIELD,
        ),
        default_base_url=None,
        default_chat_model="gpt-4o-mini",
        default_embedding_model="text-embedding-3-small",
        default_classify_model=None,
        test_strategy="list_models",
        docs_url="https://docs.litellm.ai/docs/proxy/quick_start",
    ),
    ProviderDefinition(
        id="azure_openai",
        label="Azure OpenAI",
        description="Azure-hosted OpenAI deployments. Uses deployment names instead of model IDs.",
        auth_kind="api-key-header",
        fields=(
            _API_KEY_FIELD,
            ProviderField(
                key="base_url",
                label="Resource endpoint",
                type="url",
                required=True,
                placeholder="https://my-resource.openai.azure.com",
                help="Your Azure OpenAI resource URL (without a trailing slash).",
            ),
            ProviderField(
                key="api_version",
                label="API version",
                type="text",
                required=True,
                placeholder="2024-06-01",
                help="Azure OpenAI API version to target.",
                default="2024-06-01",
            ),
        ),
        default_base_url=None,
        default_chat_model=None,
        default_embedding_model=None,
        default_classify_model=None,
        test_strategy="azure_deployments",
        docs_url="https://learn.microsoft.com/azure/ai-services/openai/reference",
        model_list_is_deployments=True,
    ),
    ProviderDefinition(
        id="openai_compatible",
        label="Custom (OpenAI-compatible)",
        description="Any server that speaks the OpenAI REST API (vLLM, LM Studio, TGI, etc.).",
        auth_kind="bearer",
        fields=(
            ProviderField(
                key="base_url",
                label="Base URL",
                type="url",
                required=True,
                placeholder="https://api.example.com/v1",
                help="Root URL including the /v1 suffix if your server uses one.",
            ),
            _OPTIONAL_API_KEY_FIELD,
        ),
        default_base_url=None,
        default_chat_model=None,
        default_embedding_model=None,
        default_classify_model=None,
        test_strategy="list_models",
    ),
)


PROVIDER_IDS: tuple[str, ...] = tuple(p.id for p in PROVIDERS)

_BY_ID: dict[str, ProviderDefinition] = {p.id: p for p in PROVIDERS}

# Legacy provider_kind values stored in the DB that should be mapped to a
# current registry id on read. Blank / unknown values fall through to
# ``openai`` (safe default for a fresh install).
_LEGACY_ALIASES: dict[str, str] = {
    "": "openai",
    "openai_compat": "openai_compatible",
}


def list_providers() -> list[ProviderDefinition]:
    return list(PROVIDERS)


def get_provider(provider_id: str) -> ProviderDefinition | None:
    normalized = normalize_provider_id(provider_id)
    return _BY_ID.get(normalized)


def provider_kind_requires_api_key(provider_kind: str | None) -> bool:
    """True when the provider expects a stored API key (or equivalent secret).

    Local providers such as Ollama use ``auth_kind="none"`` and must not be
    blocked when ``api_key_encrypted`` is empty.
    """

    definition = get_provider(normalize_provider_id(provider_kind))
    if definition is None:
        return True
    return definition.auth_kind != "none"


def normalize_provider_id(provider_id: str | None) -> str:
    """Return a known provider id, falling back to ``openai_compatible``.

    This keeps read paths tolerant of historical rows (``openai_compatible``
    remains valid; blank values map to ``openai``). Use ``resolve_known_provider_id``
    in write paths when an unknown value should be rejected.
    """

    resolved = resolve_known_provider_id(provider_id)
    if resolved is not None:
        return resolved
    return "openai_compatible"


def resolve_known_provider_id(provider_id: str | None) -> str | None:
    """Return the canonical id for a known provider, else ``None``.

    Handles legacy aliases (blank -> ``openai``, ``openai_compat`` ->
    ``openai_compatible``). Unknown values return ``None`` so callers can
    surface a validation error.
    """

    if provider_id is None:
        return None
    key = provider_id.strip()
    if key == "":
        return _LEGACY_ALIASES[""]
    alias = _LEGACY_ALIASES.get(key)
    if alias is not None:
        return alias
    if key in _BY_ID:
        return key
    return None
