"""Typed errors raised by the LLM/embedding clients and the agent loop.

These exist so the API layer can return structured 502/424 responses with
actionable hints (the chat UI renders them as a card with "Probar
conexión" / "Abrir ajustes" buttons), instead of leaking raw httpx error
strings into the assistant turn.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.ai_providers import get_provider, normalize_provider_id


class NoActiveProviderError(RuntimeError):
    """No provider config is selected as active.

    The chat UI translates this into the "Configura un proveedor de IA"
    banner with a deep-link to the settings page.
    """


class LLMProviderError(RuntimeError):
    """A call to an upstream LLM provider failed.

    Wraps non-2xx HTTP responses, transport timeouts, JSON parse errors,
    etc. into a single typed exception with structured fields the
    exception handler can serialize.

    Attributes
    ----------
    provider:
        Canonical provider id (``ollama``, ``openai``, …).
    status_code:
        HTTP status when the failure was an HTTP one. ``None`` for
        transport / parse errors.
    message:
        Short human-readable summary, safe to show to the user.
    hint:
        Actionable next step, e.g. ``"Run `ollama pull llama3.2` ..."``.
    detail:
        Truncated raw response body / exception message, useful in logs and
        as expandable detail in the chat card.
    body_excerpt:
        Up to 400 chars of the upstream response body (or transport error
        ``str()``). Same content as ``detail`` but kept as a separate
        field for clients that want to render it in a code block.
    settings_url:
        Hash-link the UI uses to open the affected provider's settings.
    """

    def __init__(
        self,
        *,
        provider: str,
        message: str,
        hint: str | None = None,
        status_code: int | None = None,
        detail: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.message = message
        self.hint = hint or ""
        self.detail = detail
        self.body_excerpt = (detail or "")[:400]
        self.model = model
        self.settings_url = f"/settings#ai-{provider}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "provider_error",
            "provider": self.provider,
            "status_code": self.status_code,
            "message": self.message,
            "hint": self.hint,
            "detail": self.body_excerpt or None,
            "model": self.model,
            "settings_url": self.settings_url,
        }


def hint_for_http_error(
    *, provider: str, status_code: int, model: str | None, body: str
) -> str:
    """Heuristic actionable hint for a given (provider, status, body) tuple.

    Kept short and pragmatic — most users only need one sentence telling
    them what to fix and where.
    """
    canonical = normalize_provider_id(provider)
    definition = get_provider(canonical)
    label = definition.label if definition else canonical
    lowered_body = (body or "").lower()

    if status_code == 401:
        return (
            f"{label} rejected the API key. Open Settings → AI and re-enter or "
            "regenerate the key."
        )
    if status_code == 403:
        return (
            f"{label} rejected the request (forbidden). Confirm the key has the "
            "required scope/permissions."
        )
    if status_code == 404:
        if canonical == "ollama":
            return (
                f"Ollama returned 404 for model {model!r}. Most likely the model "
                f"isn't pulled. Run `ollama pull {model}` on the host (or pick "
                "another model in Settings → AI)."
            )
        if "model" in lowered_body or "not_found" in lowered_body:
            return (
                f"{label} returned 404 — the model {model!r} does not exist on "
                "this account. Pick another in Settings → AI."
            )
        return (
            f"{label} returned 404 for the chat endpoint. Double-check the base "
            "URL in Settings → AI."
        )
    if status_code == 429:
        return f"{label} is rate-limiting you. Wait a moment and try again."
    if 500 <= status_code < 600:
        return f"{label} is having trouble (HTTP {status_code}). Try again in a minute."
    return (
        f"{label} responded with HTTP {status_code}. See the detail below for "
        "the upstream message."
    )


def from_http_status_error(
    exc: httpx.HTTPStatusError,
    *,
    provider: str,
    model: str | None,
) -> LLMProviderError:
    body = (exc.response.text or "").strip()
    status = exc.response.status_code
    return LLMProviderError(
        provider=provider,
        status_code=status,
        message=f"{provider} responded HTTP {status}.",
        hint=hint_for_http_error(provider=provider, status_code=status, model=model, body=body),
        detail=body or None,
        model=model,
    )


def from_transport_error(
    exc: Exception,
    *,
    provider: str,
    model: str | None,
) -> LLMProviderError:
    canonical = normalize_provider_id(provider)
    definition = get_provider(canonical)
    label = definition.label if definition else canonical
    if isinstance(exc, httpx.TimeoutException):
        message = f"{label} did not respond in time."
        hint = (
            "The provider's network is slow or unreachable. Check the base URL "
            "in Settings → AI; if you're using Ollama make sure `ollama serve` "
            "is running."
        )
    else:
        message = f"Could not reach {label}."
        hint = (
            "Verify the base URL in Settings → AI and that the server is "
            "running and reachable from the backend container."
        )
    return LLMProviderError(
        provider=canonical,
        status_code=None,
        message=message,
        hint=hint,
        detail=str(exc),
        model=model,
    )
