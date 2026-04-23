from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.models.user_ai_settings import UserAISettings
from app.services.ai_providers import normalize_provider_id
from app.services.embedding_client import _api_root, _auth_headers, _extra_headers


@dataclass(frozen=True)
class ModelLimits:
    context_window: int
    max_output_tokens_default: int
    source: str = "defaults"


@dataclass
class _CacheEntry:
    expires_at: float
    limits: ModelLimits


_CACHE_TTL_SECONDS = 900.0
_DEFAULT_CONTEXT = 32_768
_MIN_OUTPUT = 256
_SAFETY_MARGIN = 512
_limits_cache: dict[tuple[str, str], _CacheEntry] = {}


def _keyword_context_overrides(model: str) -> int:
    lowered = model.lower()
    if "200k" in lowered:
        return 200_000
    if "128k" in lowered:
        return 128_000
    if "64k" in lowered:
        return 64_000
    if "32k" in lowered:
        return 32_768
    if "16k" in lowered:
        return 16_384
    if any(k in lowered for k in ("gpt-4.1", "o1", "o3", "gpt-4o", "claude-3.7", "claude-4")):
        return 128_000
    if "gemini" in lowered:
        return 1_048_576
    return _DEFAULT_CONTEXT


def _default_output_for_context(context_window: int) -> int:
    if context_window >= 500_000:
        return 8_192
    if context_window >= 120_000:
        return 6_144
    if context_window >= 64_000:
        return 4_096
    if context_window >= 32_000:
        return 2_048
    return 1_024


def _fallback_limits(model: str) -> ModelLimits:
    context = _keyword_context_overrides(model)
    return ModelLimits(
        context_window=context,
        max_output_tokens_default=_default_output_for_context(context),
        source="fallback",
    )


def _pick_output_from_model_item(raw: dict[str, Any], context_window: int) -> int:
    top = raw.get("top_provider")
    if isinstance(top, dict):
        val = top.get("max_completion_tokens")
        if isinstance(val, int) and val > 0:
            return val
    out = _default_output_for_context(context_window)
    return max(_MIN_OUTPUT, min(out, context_window - _SAFETY_MARGIN))


async def _fetch_openrouter_limits(
    *,
    api_key: str,
    settings_row: UserAISettings,
    model: str,
) -> ModelLimits | None:
    if not settings.dynamic_model_limits:
        return None
    provider = normalize_provider_id(getattr(settings_row, "provider_kind", ""))
    if provider != "openrouter":
        return None
    now = time.monotonic()
    cache_key = (provider, model)
    cached = _limits_cache.get(cache_key)
    if cached is not None and cached.expires_at > now:
        return cached.limits
    try:
        headers = {
            **_auth_headers(api_key, settings_row),
            **_extra_headers(settings_row),
        }
        base = _api_root(settings_row)
        url = f"{base}/models"
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception:  # noqa: BLE001 - best effort enrichment only
        return None
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("id") or "").strip() != model:
            continue
        context_window = raw.get("context_length")
        if not isinstance(context_window, int) or context_window <= 0:
            continue
        limits = ModelLimits(
            context_window=context_window,
            max_output_tokens_default=_pick_output_from_model_item(raw, context_window),
            source="openrouter_models",
        )
        _limits_cache[cache_key] = _CacheEntry(expires_at=now + _CACHE_TTL_SECONDS, limits=limits)
        return limits
    return None


async def resolve_model_limits(
    *,
    api_key: str,
    settings_row: UserAISettings,
    model: str,
) -> ModelLimits:
    dynamic = await _fetch_openrouter_limits(api_key=api_key, settings_row=settings_row, model=model)
    if dynamic is not None:
        return dynamic
    return _fallback_limits(model)
