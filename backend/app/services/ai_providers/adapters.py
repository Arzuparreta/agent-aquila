"""Per-provider HTTP adapters for test-connection and list-models.

Each adapter speaks the provider's native REST shape (OpenAI-style
``/models``, Ollama's ``/api/tags``, Anthropic's ``/v1/models``, Azure's
``/openai/deployments``) and normalizes errors into a small set of codes the
frontend can translate to user-facing copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.services.ai_providers.registry import ProviderDefinition, get_provider

ErrorCode = Literal[
    "invalid_api_key",
    "unauthorized",
    "not_found",
    "network",
    "timeout",
    "bad_response",
    "missing_field",
    "unknown",
]

Capability = Literal["chat", "embedding", "unknown"]

# Conservative timeouts: test/list should feel snappy but survive a slow LAN.
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0


@dataclass
class ProviderConfig:
    """Runtime configuration used to call a provider.

    ``extras`` carries provider-specific knobs (OpenRouter referer/title,
    Azure api_version, etc.). ``api_key`` is the decrypted key or ``None``
    when the provider does not need one.
    """

    provider_id: str
    api_key: str | None = None
    base_url: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    ok: bool
    message: str
    code: ErrorCode | None = None
    detail: str | None = None


@dataclass
class ModelInfo:
    id: str
    label: str
    capability: Capability = "unknown"


def _clean_base_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/")


def _resolve_base_url(definition: ProviderDefinition, cfg: ProviderConfig) -> str | None:
    return _clean_base_url(cfg.base_url) or _clean_base_url(definition.default_base_url)


def _openrouter_extra_headers(cfg: ProviderConfig) -> dict[str, str]:
    headers: dict[str, str] = {}
    referer = cfg.extras.get("openrouter_referer") or cfg.extras.get("http_referer") or cfg.extras.get("referer")
    if referer:
        headers["Referer"] = str(referer)
    title = cfg.extras.get("openrouter_title")
    if title:
        headers["X-Title"] = str(title)
    return headers


def _auth_headers(definition: ProviderDefinition, cfg: ProviderConfig) -> dict[str, str]:
    headers: dict[str, str] = {}
    key = (cfg.api_key or "").strip()
    if definition.auth_kind == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif definition.auth_kind == "x-api-key" and key:
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    elif definition.auth_kind == "api-key-header" and key:
        headers["api-key"] = key
    if definition.id == "openrouter":
        headers.update(_openrouter_extra_headers(cfg))
    return headers


def _classify_capability(provider_id: str, model_id: str) -> Capability:
    lowered = model_id.lower()
    embedding_hints = ("embed", "embedding")
    if any(hint in lowered for hint in embedding_hints):
        return "embedding"
    # OpenAI-family text completion / chat models: everything else defaults
    # to chat. Anthropic, OpenRouter, LiteLLM mostly list chat models.
    if provider_id in {"openai", "openai_compatible", "openrouter", "litellm", "anthropic", "google"}:
        return "chat"
    return "unknown"


def _map_http_error(exc: httpx.HTTPStatusError) -> TestResult:
    status = exc.response.status_code
    body = (exc.response.text or "").strip()[:400]
    if status in (401, 403):
        return TestResult(
            ok=False,
            code="invalid_api_key" if status == 401 else "unauthorized",
            message="The server rejected the credentials." if status == 401 else "Access denied by the server.",
            detail=body or None,
        )
    if status == 404:
        return TestResult(
            ok=False,
            code="not_found",
            message="The endpoint returned 404. Double-check the base URL.",
            detail=body or None,
        )
    return TestResult(
        ok=False,
        code="bad_response",
        message=f"Server returned HTTP {status}.",
        detail=body or None,
    )


def _map_transport_error(exc: Exception) -> TestResult:
    if isinstance(exc, httpx.TimeoutException):
        return TestResult(ok=False, code="timeout", message="The server did not respond in time.", detail=str(exc))
    return TestResult(ok=False, code="network", message="Could not reach the server.", detail=str(exc))


async def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Adapter implementations
# ---------------------------------------------------------------------------


async def _list_openai_like(definition: ProviderDefinition, cfg: ProviderConfig) -> list[ModelInfo]:
    base = _resolve_base_url(definition, cfg)
    if not base:
        raise _MissingField("base_url")
    url = f"{base}/models"
    headers = _auth_headers(definition, cfg)
    data = await _get_json(url, headers=headers)
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[ModelInfo] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not model_id:
            continue
        out.append(
            ModelInfo(
                id=model_id,
                label=model_id,
                capability=_classify_capability(definition.id, model_id),
            )
        )
    return out


async def _list_ollama(definition: ProviderDefinition, cfg: ProviderConfig) -> list[ModelInfo]:
    base = _resolve_base_url(definition, cfg)
    if not base:
        raise _MissingField("base_url")
    # Ollama lives at the root (e.g. http://localhost:11434), not /v1.
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    url = f"{root}/api/tags"
    data = await _get_json(url)
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    out: list[ModelInfo] = []
    for raw in models:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("model") or "").strip()
        if not name:
            continue
        out.append(
            ModelInfo(
                id=name,
                label=name,
                capability=_classify_capability("ollama", name),
            )
        )
    return out


async def _list_anthropic(definition: ProviderDefinition, cfg: ProviderConfig) -> list[ModelInfo]:
    base = _resolve_base_url(definition, cfg) or "https://api.anthropic.com/v1"
    url = f"{base}/models"
    headers = _auth_headers(definition, cfg)
    data = await _get_json(url, headers=headers)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[ModelInfo] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id:
            continue
        display = str(raw.get("display_name") or model_id)
        out.append(ModelInfo(id=model_id, label=display, capability="chat"))
    return out


async def _list_azure_deployments(definition: ProviderDefinition, cfg: ProviderConfig) -> list[ModelInfo]:
    base = _resolve_base_url(definition, cfg)
    if not base:
        raise _MissingField("base_url")
    api_version = str(cfg.extras.get("api_version") or "").strip()
    if not api_version:
        raise _MissingField("api_version")
    url = f"{base}/openai/deployments"
    headers = _auth_headers(definition, cfg)
    data = await _get_json(url, headers=headers, params={"api-version": api_version})
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[ModelInfo] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        deployment_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not deployment_id:
            continue
        model_name = str(raw.get("model") or "")
        label = f"{deployment_id} ({model_name})" if model_name else deployment_id
        cap = _classify_capability("openai", model_name) if model_name else "unknown"
        out.append(ModelInfo(id=deployment_id, label=label, capability=cap))
    return out


class _MissingField(Exception):
    def __init__(self, field_key: str) -> None:
        super().__init__(field_key)
        self.field_key = field_key


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def list_models(cfg: ProviderConfig) -> list[ModelInfo]:
    definition = get_provider(cfg.provider_id)
    if definition is None:
        raise ValueError(f"Unknown provider: {cfg.provider_id}")
    strategy = definition.test_strategy
    if strategy == "list_models":
        return await _list_openai_like(definition, cfg)
    if strategy == "ollama_tags":
        return await _list_ollama(definition, cfg)
    if strategy == "anthropic_models":
        return await _list_anthropic(definition, cfg)
    if strategy == "azure_deployments":
        return await _list_azure_deployments(definition, cfg)
    raise ValueError(f"Unsupported test strategy: {strategy}")


async def test_connection(cfg: ProviderConfig) -> TestResult:
    """Call list_models and convert any error into a structured TestResult.

    Success is defined as "the server answered with a syntactically valid
    model list". An empty list is still considered ok (some LiteLLM proxies
    report nothing until you configure routes).
    """

    definition = get_provider(cfg.provider_id)
    if definition is None:
        return TestResult(ok=False, code="unknown", message=f"Unknown provider: {cfg.provider_id}")

    # Required-field validation up front so we can give precise errors.
    for f in definition.fields:
        if not f.required:
            continue
        if f.key == "api_key":
            if not (cfg.api_key or "").strip():
                return TestResult(ok=False, code="missing_field", message=f"{f.label} is required.")
        elif f.key == "base_url":
            if not (cfg.base_url or "").strip():
                return TestResult(ok=False, code="missing_field", message=f"{f.label} is required.")
        else:
            if not str(cfg.extras.get(f.key) or "").strip():
                return TestResult(ok=False, code="missing_field", message=f"{f.label} is required.")

    try:
        models = await list_models(cfg)
    except _MissingField as exc:
        return TestResult(ok=False, code="missing_field", message=f"Missing required field: {exc.field_key}.")
    except httpx.HTTPStatusError as exc:
        return _map_http_error(exc)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return _map_transport_error(exc)
    except ValueError as exc:
        return TestResult(ok=False, code="bad_response", message=str(exc))
    except Exception as exc:  # noqa: BLE001 - last-resort normalization
        return TestResult(ok=False, code="unknown", message="Unexpected error", detail=str(exc))

    suffix = f" Found {len(models)} model(s)." if models else " No models returned by the server."
    return TestResult(ok=True, message=f"Connected to {definition.label}.{suffix}")


async def safe_list_models(cfg: ProviderConfig) -> tuple[list[ModelInfo], TestResult | None]:
    """Return models plus an error-result if listing failed.

    When the call succeeds, the second element is ``None``. This lets the
    route layer surface the same structured error codes as ``test_connection``
    without re-running the request.
    """

    try:
        return await list_models(cfg), None
    except _MissingField as exc:
        return [], TestResult(ok=False, code="missing_field", message=f"Missing required field: {exc.field_key}.")
    except httpx.HTTPStatusError as exc:
        return [], _map_http_error(exc)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return [], _map_transport_error(exc)
    except ValueError as exc:
        return [], TestResult(ok=False, code="bad_response", message=str(exc))
    except Exception as exc:  # noqa: BLE001
        return [], TestResult(ok=False, code="unknown", message="Unexpected error", detail=str(exc))
