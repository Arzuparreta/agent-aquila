"""Unit tests for the ``/ai/providers`` route plumbing.

Full FastAPI integration tests would require booting the app with a test DB
and auth fixtures - infrastructure that doesn't exist in this repo yet. These
tests instead exercise the logic that is unique to the routes (the stored-key
sentinel translation and the provider registry serialization).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.routes import ai as ai_routes
from app.schemas.ai import STORED_API_KEY_SENTINEL, ProviderConfigRequest
from app.services.ai_providers import PROVIDER_IDS


def test_get_providers_enumerates_registry() -> None:
    import asyncio

    providers = asyncio.run(ai_routes.get_providers())
    returned_ids = [p.id for p in providers]
    assert set(returned_ids) == set(PROVIDER_IDS)
    # Every provider must ship with at least one input field so the UI has
    # something to render.
    for p in providers:
        assert p.fields, f"Provider {p.id} must declare at least one field"
        for f in p.fields:
            assert f.key
            assert f.label


@dataclass
class _FakeUser:
    id: int = 1


class _FakeSettingsService:
    """Replaces ``UserAISettingsService.get_api_key`` without touching the DB."""

    def __init__(self, stored_key: str | None) -> None:
        self.stored_key = stored_key
        self.calls = 0

    async def get_api_key(self, _db: Any, _user: Any) -> str | None:
        self.calls += 1
        return self.stored_key


@pytest.mark.asyncio
async def test_resolve_config_uses_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSettingsService(stored_key="stored-secret")
    monkeypatch.setattr(ai_routes.UserAISettingsService, "get_api_key", fake.get_api_key)

    payload = ProviderConfigRequest(provider_id="openai", api_key=STORED_API_KEY_SENTINEL)
    cfg = await ai_routes._resolve_config(payload, db=None, current_user=_FakeUser())  # type: ignore[arg-type]
    assert cfg.api_key == "stored-secret"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_resolve_config_passes_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSettingsService(stored_key="stored-secret")
    monkeypatch.setattr(ai_routes.UserAISettingsService, "get_api_key", fake.get_api_key)

    payload = ProviderConfigRequest(provider_id="openai", api_key="new-key")
    cfg = await ai_routes._resolve_config(payload, db=None, current_user=_FakeUser())  # type: ignore[arg-type]
    assert cfg.api_key == "new-key"
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_resolve_config_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSettingsService(stored_key="stored-secret")
    monkeypatch.setattr(ai_routes.UserAISettingsService, "get_api_key", fake.get_api_key)

    payload = ProviderConfigRequest(provider_id="ollama", api_key=None, base_url="http://x")
    cfg = await ai_routes._resolve_config(payload, db=None, current_user=_FakeUser())  # type: ignore[arg-type]
    assert cfg.api_key is None
    assert fake.calls == 0


def test_user_ai_settings_update_normalizes_provider() -> None:
    from app.schemas.ai import UserAISettingsUpdate

    payload = UserAISettingsUpdate(provider_kind="")  # legacy blank
    assert payload.provider_kind == "openai"

    payload = UserAISettingsUpdate(provider_kind="openai_compat")  # legacy alias
    assert payload.provider_kind == "openai_compatible"

    with pytest.raises(Exception):
        UserAISettingsUpdate(provider_kind="nonsense")
