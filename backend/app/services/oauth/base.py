"""Provider-agnostic OAuth 2.0 helper interface.

`google_oauth` and `microsoft_oauth` both conform to the same functional shape so callers
(routes, TokenManager) can treat them interchangeably. Kept intentionally as module-level
functions + a registry dict — no abstract class ceremony required.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable


@dataclass
class OAuthProvider:
    name: str  # "google" | "microsoft"
    build_authorize_url: Callable[[str, list[str]], str]
    exchange_code: Callable[[str], Awaitable[dict[str, Any]]]
    refresh_access_token: Callable[..., Awaitable[dict[str, Any]]]
    fetch_userinfo: Callable[[str], Awaitable[dict[str, Any]]]
    scopes_for_intent: Callable[[str], list[str]]
    provider_ids_for_scopes: Callable[[list[str]], list[str]]
    redirect_uri: Callable[[], str]
    is_configured: Callable[[], bool]
    compute_expires_at: Callable[[dict[str, Any]], datetime | None]


_registry: dict[str, OAuthProvider] = {}


def register_provider(provider: OAuthProvider) -> None:
    _registry[provider.name] = provider


def get_provider(name: str) -> OAuthProvider | None:
    return _registry.get(name)


def all_providers() -> dict[str, OAuthProvider]:
    return dict(_registry)
