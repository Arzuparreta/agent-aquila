from __future__ import annotations

HarnessMode = Literal["native"]  # prompted mode removed
HarnessPreference = Literal["native"]  # auto/prompted removed


def resolve_effective_mode(
    preference: str | None,
    provider_kind: str | None,
    chat_model: str | None,
) -> HarnessMode:
    """Always use native harness (prompted mode removed)."""
    return "native"
