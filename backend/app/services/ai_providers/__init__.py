"""AI provider registry and adapters.

Single source of truth for which providers the app supports, what fields each
one requires, and how to test/list-models against each one. The frontend
fetches this registry via ``GET /ai/providers`` so the UI stays in sync
without duplicating provider metadata.
"""

from __future__ import annotations

from app.services.ai_providers.registry import (
    PROVIDER_IDS,
    PROVIDERS,
    ProviderDefinition,
    ProviderField,
    get_provider,
    list_providers,
    normalize_provider_id,
    provider_kind_requires_api_key,
    resolve_known_provider_id,
)

__all__ = [
    "PROVIDER_IDS",
    "PROVIDERS",
    "ProviderDefinition",
    "ProviderField",
    "get_provider",
    "list_providers",
    "normalize_provider_id",
    "provider_kind_requires_api_key",
    "resolve_known_provider_id",
]
