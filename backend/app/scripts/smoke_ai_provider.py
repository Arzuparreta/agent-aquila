"""End-to-end smoke test for a user's configured AI provider.

This is the "did I wire my key right?" tool: it runs against the **same
clients** the agent loop uses (``LLMClient.chat_with_tools`` for the agent,
``LLMClient.chat_completion(response_format_json=True)`` for the triage
classifier, ``EmbeddingClient.embed_texts`` for RAG) so a green run here
means the harness will work end-to-end.

It performs three independent checks, prints a per-check verdict, and
exits with code 0 only if all three pass:

1. **Tool calling** — the contract the agent depends on. We send a
   minimal palette (``echo`` + ``final_answer``) with
   ``tool_choice="required"``. Pass = the model returned at least one
   tool call with a parseable name. (Raw HTTP / parsing errors fail
   fast; a model that ignores ``required`` and returns plain text is
   also a fail because the agent loop relies on it.)
2. **JSON mode** — what the inbox triage uses. We ask for a strict JSON
   verdict; pass = the response parses as JSON with the expected key.
3. **Embeddings** — what RAG / semantic-search uses. We embed two short
   strings; pass = we got two vectors back, both non-empty floats. We
   also report the raw dimension so you can confirm
   ``embedding_vector.pad_embedding`` will adapt it to the
   pgvector(1536) column without truncation.

Run from ``backend/`` (inside the ``api`` container, or any shell with
the project venv + DATABASE_URL pointing at the live db)::

    python -m app.scripts.smoke_ai_provider --email me@example.com

Use ``--user-id 1`` if you'd rather pick by id. Use ``--skip embeddings``
to skip a check (e.g. when the provider has no embedding model
configured yet).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.user_ai_provider_config import UserAIProviderConfig
from app.services.ai_provider_config_service import AIProviderConfigService
from app.services.ai_providers import get_provider, normalize_provider_id
from app.services.embedding_client import EmbeddingClient
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService


# ANSI helpers — no external dep, degrades silently when piped.
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}OK{_RESET}   {msg}")


def _fail(msg: str, detail: str | None = None) -> None:
    print(f"  {_RED}FAIL{_RESET} {msg}")
    if detail:
        for line in detail.splitlines()[:6]:
            print(f"       {_DIM}{line}{_RESET}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}WARN{_RESET} {msg}")


def _section(title: str) -> None:
    print(f"\n{title}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": (
                "Return the input text verbatim. Use this when the user asks you "
                "to repeat or echo something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The exact text to echo back.",
                    }
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": (
                "Deliver the user-facing reply. Call this exactly once to end "
                "the turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The reply to show the user.",
                    }
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
]


async def _check_tool_calling(api_key: str, settings_row: Any) -> bool:
    print("Tool calling (agent contract)")
    try:
        resp = await LLMClient.chat_with_tools(
            api_key,
            settings_row,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a test harness. Every turn MUST end in a tool "
                        "call. Use 'echo' to repeat the user's text, then "
                        "'final_answer' to confirm."
                    ),
                },
                {
                    "role": "user",
                    "content": "Echo the word: ping",
                },
            ],
            tools=_TOOLS,
            tool_choice="required",
            temperature=0.0,
        )
    except Exception as exc:
        _fail("HTTP / parsing error during chat_with_tools", str(exc))
        return False

    if not resp.has_tool_calls:
        _fail(
            "model returned text instead of a tool call (tool_choice='required' was ignored)",
            f"content={resp.content[:200]!r}",
        )
        return False

    names = [tc.name for tc in resp.tool_calls]
    if not all(n in {"echo", "final_answer"} for n in names):
        _fail(f"model invented tool names: {names}")
        return False

    _ok(f"got {len(resp.tool_calls)} tool call(s): {names}")
    for tc in resp.tool_calls:
        if not isinstance(tc.arguments, dict):
            _fail(f"tool call {tc.name!r} has non-dict arguments: {tc.arguments!r}")
            return False
    _ok("all tool-call arguments parsed as dicts")
    return True


async def _check_json_mode(api_key: str, settings_row: Any) -> bool:
    print("JSON mode (triage / classifier contract)")
    try:
        raw = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Reply with ONLY a JSON object: "
                        '{"category": "actionable" | "informational" | "noise"}.'
                    ),
                },
                {
                    "role": "user",
                    "content": "Subject: Festival booking inquiry — please send a quote.",
                },
            ],
            temperature=0.0,
            response_format_json=True,
        )
    except Exception as exc:
        # Some providers (esp. some Ollama models) reject response_format.
        # Retry without it: the triage service tolerates loose JSON.
        _warn(f"response_format=json_object rejected: {exc}; retrying without it")
        try:
            raw = await LLMClient.chat_completion(
                api_key,
                settings_row,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Reply with ONLY a JSON object: "
                            '{"category": "actionable" | "informational" | "noise"}. '
                            "No prose, no code fences."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Subject: Festival booking inquiry — please send a quote.",
                    },
                ],
                temperature=0.0,
            )
        except Exception as inner:
            _fail("HTTP error during chat_completion", str(inner))
            return False

    raw = (raw or "").strip()
    # Tolerate ```json fences``` since the triage parser does too.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"response was not valid JSON: {exc}", raw[:300])
        return False

    if not isinstance(parsed, dict) or "category" not in parsed:
        _fail("JSON did not contain expected key 'category'", raw[:300])
        return False

    _ok(f"parsed JSON, category={parsed['category']!r}")
    return True


async def _check_embeddings(api_key: str, settings_row: Any) -> bool:
    print("Embeddings (RAG / semantic-search contract)")
    if not settings_row.embedding_model:
        _warn("no embedding_model configured; skipping (set one in Settings → Modelo de IA)")
        return True
    try:
        vectors = await EmbeddingClient.embed_texts(
            api_key, settings_row, ["hola mundo", "festival booking inquiry"]
        )
    except Exception as exc:
        _fail("HTTP error during embed_texts", str(exc))
        return False

    if len(vectors) != 2:
        _fail(f"expected 2 vectors, got {len(vectors)}")
        return False
    if not vectors[0] or not vectors[1]:
        _fail("at least one returned vector is empty")
        return False
    if not all(isinstance(x, (int, float)) for x in vectors[0][:8]):
        _fail("vector entries are not numbers", repr(vectors[0][:5]))
        return False

    dim = len(vectors[0])
    from app.core.config import settings as app_settings

    target = app_settings.embedding_dimensions
    if dim == target:
        _ok(f"got 2 vectors of dim {dim} (matches pgvector({target}) exactly)")
    elif dim < target:
        _ok(
            f"got 2 vectors of dim {dim}; pad_embedding() will zero-pad to {target}. "
            f"Compatible with pgvector({target})."
        )
    else:
        _ok(
            f"got 2 vectors of dim {dim}; pad_embedding() will TRUNCATE to {target}. "
            f"Works but you lose information — consider a model that emits ≤ {target} dims."
        )
    return True


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _resolve_user(db: AsyncSession, *, email: str | None, user_id: int | None) -> User:
    if user_id is not None:
        row = await db.get(User, user_id)
        if row is None:
            raise SystemExit(f"No user with id={user_id}")
        return row
    if email is not None:
        res = await db.execute(select(User).where(User.email == email))
        row = res.scalar_one_or_none()
        if row is None:
            raise SystemExit(f"No user with email={email!r}")
        return row
    # Fall back to the only user in single-user installs.
    res = await db.execute(select(User).limit(2))
    rows = res.scalars().all()
    if len(rows) == 1:
        return rows[0]
    raise SystemExit("Multiple users exist; pick one with --email or --user-id.")


def _row_as_settings_proxy(row: UserAIProviderConfig) -> Any:
    """Adapt a ``UserAIProviderConfig`` to the duck-typed settings shape the
    LLM/Embedding clients expect (``provider_kind``, ``base_url``,
    ``chat_model``, ``embedding_model``, ``classify_model``, ``extras``).
    Cheap and dependency-free so the smoke script doesn't need to mutate
    the live ``user_ai_settings`` mirror.
    """

    class _Proxy:
        provider_kind = row.provider_kind
        base_url = row.base_url
        chat_model = row.chat_model
        embedding_model = row.embedding_model
        classify_model = row.classify_model
        ai_disabled = False
        extras = row.extras or {}

    return _Proxy()


async def _smoke_one_config(
    row: UserAIProviderConfig, *, skipped: set[str]
) -> dict[str, bool | None]:
    """Run all three checks against a single saved config row."""
    try:
        api_key = AIProviderConfigService.decrypt_api_key(row) or ""
    except Exception as exc:  # noqa: BLE001
        _fail("could not decrypt stored API key", str(exc))
        return {"tools": False, "json": False, "embeddings": False}

    settings_row = _row_as_settings_proxy(row)
    results: dict[str, bool | None] = {"tools": None, "json": None, "embeddings": None}
    if "tools" not in skipped:
        _section("[1/3] Tool calling")
        results["tools"] = await _check_tool_calling(api_key, settings_row)
    if "json" not in skipped:
        _section("[2/3] JSON mode")
        results["json"] = await _check_json_mode(api_key, settings_row)
    if "embeddings" not in skipped:
        _section("[3/3] Embeddings")
        results["embeddings"] = await _check_embeddings(api_key, settings_row)
    return results


def _print_table(rows: list[tuple[str, str, dict[str, bool | None]]]) -> None:
    header = ("Provider", "Chat model", "Tools", "JSON", "Embed")
    widths = [len(h) for h in header]
    fmt_rows: list[tuple[str, str, str, str, str]] = []
    for kind, chat_model, results in rows:
        rendered = (
            kind,
            chat_model or "—",
            _pretty(results.get("tools")),
            _pretty(results.get("json")),
            _pretty(results.get("embeddings")),
        )
        fmt_rows.append(rendered)
        for i, cell in enumerate(rendered):
            widths[i] = max(widths[i], _visible_len(cell))

    line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    sep = "-+-".join("-" * widths[i] for i in range(len(widths)))
    print()
    print(line)
    print(sep)
    for r in fmt_rows:
        print(" | ".join(_ljust_visible(r[i], widths[i]) for i in range(len(r))))
    print()


def _pretty(v: bool | None) -> str:
    if v is True:
        return f"{_GREEN}OK{_RESET}"
    if v is False:
        return f"{_RED}FAIL{_RESET}"
    return f"{_DIM}—{_RESET}"


def _visible_len(text: str) -> int:
    out = 0
    in_esc = False
    for ch in text:
        if ch == "\033":
            in_esc = True
            continue
        if in_esc:
            if ch == "m":
                in_esc = False
            continue
        out += 1
    return out


def _ljust_visible(text: str, width: int) -> str:
    return text + " " * max(0, width - _visible_len(text))


async def main_async(args: argparse.Namespace) -> int:
    skipped = set(args.skip or [])
    if args.all:
        async with AsyncSessionLocal() as db:
            user = await _resolve_user(db, email=args.email, user_id=args.user_id)
            configs = await AIProviderConfigService.list_configs(db, user)
            active = await AIProviderConfigService.get_active(db, user)
            print(f"User: {user.email} (id={user.id})  ·  {len(configs)} saved provider(s)")
            results_table: list[tuple[str, str, dict[str, bool | None]]] = []
            for cfg in configs:
                marker = "  [active]" if active and active.id == cfg.id else ""
                _section(f"== {cfg.provider_kind}{marker} ==")
                results = await _smoke_one_config(cfg, skipped=skipped)
                results_table.append((cfg.provider_kind + marker, cfg.chat_model, results))
        if not configs:
            print(f"{_YELLOW}No saved provider configs for this user yet.{_RESET}")
            return 2
        _print_table(results_table)
        any_failed = any(v is False for _, _, r in results_table for v in r.values())
        if any_failed:
            print(f"{_RED}Smoke test FAILED for at least one provider.{_RESET}")
            return 1
        print(f"{_GREEN}All saved providers passed smoke tests.{_RESET}")
        return 0

    async with AsyncSessionLocal() as db:
        user = await _resolve_user(db, email=args.email, user_id=args.user_id)
        settings_row = await UserAISettingsService.get_or_create(db, user)
        api_key = await UserAISettingsService.get_api_key(db, user) or ""

        provider_id = normalize_provider_id(settings_row.provider_kind)
        definition = get_provider(provider_id)
        provider_label = definition.label if definition else provider_id

    print(f"User           : {user.email} (id={user.id})")
    print(f"Provider       : {provider_label}  ({provider_id})")
    print(f"Base URL       : {settings_row.base_url or (definition.default_base_url if definition else '?')}")
    print(f"Chat model     : {settings_row.chat_model or '(unset)'}")
    print(f"Classify model : {settings_row.classify_model or '(falls back to chat_model)'}")
    print(f"Embedding model: {settings_row.embedding_model or '(unset)'}")
    print(f"AI disabled    : {settings_row.ai_disabled}")

    if settings_row.ai_disabled:
        print(f"\n{_RED}AI is disabled for this user — flip the toggle in Settings → Modelo de IA.{_RESET}")
        return 2

    if (
        definition is not None
        and definition.auth_kind != "none"
        and not api_key
    ):
        print(f"\n{_RED}No API key on file for this provider.{_RESET}")
        return 2

    results: dict[str, bool | None] = {"tools": None, "json": None, "embeddings": None}

    if "tools" not in skipped:
        _section("[1/3] Tool calling")
        results["tools"] = await _check_tool_calling(api_key, settings_row)
    if "json" not in skipped:
        _section("[2/3] JSON mode")
        results["json"] = await _check_json_mode(api_key, settings_row)
    if "embeddings" not in skipped:
        _section("[3/3] Embeddings")
        results["embeddings"] = await _check_embeddings(api_key, settings_row)

    print()
    failures = [k for k, v in results.items() if v is False]
    if failures:
        print(f"{_RED}Smoke test FAILED{_RESET}: {', '.join(failures)}")
        return 1
    print(f"{_GREEN}Smoke test PASSED{_RESET} — provider is fully wired for the agent harness.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", help="User email to test (defaults to the only user when there is one).")
    parser.add_argument("--user-id", type=int, help="User id to test.")
    parser.add_argument(
        "--skip",
        action="append",
        choices=["tools", "json", "embeddings"],
        help="Skip a specific check. Repeatable.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Iterate every saved provider config for this user and print a results table.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
