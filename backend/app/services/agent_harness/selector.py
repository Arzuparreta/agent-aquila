from __future__ import annotations

from typing import Literal

from app.services.ai_providers import normalize_provider_id

HarnessMode = Literal["native", "prompted"]
HarnessPreference = Literal["auto", "native", "prompted"]


def default_harness_for_model(provider_kind: str | None, chat_model: str | None) -> HarnessMode:
    """Heuristic for Ollama models with broken ``tools=`` / ``tool_choice`` (see ollama#8421, #14601)."""
    pk = normalize_provider_id(provider_kind or "")
    m = (chat_model or "").lower()
    if pk != "ollama":
        return "native"
    if "qwen3-coder" in m or "qwen3_coder" in m:
        return "native"
    if "qwen3" in m:
        return "prompted"
    if "hermes" in m:
        return "prompted"
    return "native"


def resolve_effective_mode(
    preference: str | None,
    provider_kind: str | None,
    chat_model: str | None,
) -> HarnessMode:
    pref = (preference or "auto").strip().lower()
    if pref == "native":
        return "native"
    if pref == "prompted":
        return "prompted"
    return default_harness_for_model(provider_kind, chat_model)
