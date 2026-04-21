"""Structured post-turn memory extraction (OpenClaw-style durable facts).

Runs after a completed agent reply: one JSON-mode chat completion, then
``AgentMemoryService.upsert`` for each extracted row. Gated by
``AGENT_MEMORY_POST_TURN_*`` and optional heuristics to avoid LLM cost on
routine turns.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

_MAX_KEY_LEN = 200
_MAX_CONTENT_LEN = 8000
_MAX_MEMORIES = 12

# User text: remember / name / preference signals (EN + ES).
_USER_MEMORY_HINT = re.compile(
    r"(?:^|\b)(?:remember|recuerda|recuerde|recuerdas|don'?t\s+forget|no\s+olvides|"
    r"prefer|prefiero|prefieres|preference|preferencia|"
    r"my\s+name\s+is|me\s+llamo|ll[aá]mame|ll[aá]mate|your\s+name\s+is|tu\s+nombre|"
    r"te\s+llamas|how\s+should\s+i\s+call|c[oó]mo\s+te\s+llamo|"
    r"\byou\s+are\s+|\beres\s+|you'?re\s+the\s+|"
    r"call\s+me|call\s+yourself|"
    r"guarda\s+en\s+memoria|guardar\s+en\s+memoria|"
    r"i\s+want\s+you\s+to\s+remember|quiero\s+que\s+recuerdes)(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Assistant text: claimed persistence (often without a real tool call).
_ASSISTANT_MEMORY_PROMISE = re.compile(
    r"(?:^|\b)(?:guardo\s+en\s+memoria|lo\s+guardo|guardar[eé]\s+en\s+memoria|"
    r"i['’]?ll\s+save|i\s+will\s+save|saved\s+to\s+memory|"
    r"lo\s+memorizo|memorizar[eé])(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

_EXTRACTION_SYSTEM = """You extract durable facts for a personal assistant's persistent key-value memory.
Return ONLY a JSON object with this exact shape:
{"memories":[{"key":"string","content":"string","importance":0}]}

Rules:
- "memories" may be an empty array if nothing durable should be stored.
- Keys: lowercase, dot-separated segments, max 200 characters. Use prefixes such as
  user.profile.*, agent.identity.*, memory.durable.*, prefs.* — never raw PII buckets.
- Content: short plain text; one main fact per entry.
- importance: integer 0-10 (use 8-10 when the user explicitly asked to remember, or for stable identity).
- Do NOT store passwords, API keys, tokens, or full third-party message bodies.
- If the user assigns the assistant display names in Spanish and/or English, use keys like
  agent.identity.display_name_es and agent.identity.display_name_en, or a single agent.identity.names
  with both names in the content.
- Do not duplicate the same fact under many keys; prefer one canonical key per fact."""


@dataclass(frozen=True)
class PostTurnMemoryResult:
    skipped: bool
    reason: str
    upserts: int


def heuristic_wants_post_turn_extraction(user_message: str, assistant_message: str) -> bool:
    """Return True when the last exchange likely contains durable memory."""
    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if not u and not a:
        return False
    if _USER_MEMORY_HINT.search(u):
        return True
    if _ASSISTANT_MEMORY_PROMISE.search(a):
        return True
    # Short identity-style turns (e.g. "Eres Agente Áquila en español...")
    if len(u) <= 600 and (
        re.search(r"\b(agente|agent|águila|aquila|assistant|asistente)\b", u, re.I)
        and re.search(r"\b(eres|you are|llam|name|nombre|call)\b", u, re.I)
    ):
        return True
    return False


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{[\s\S]*\}\s*$", text)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _normalize_memory_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("memories")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:_MAX_MEMORIES]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        content = str(item.get("content") or "").strip()
        if not key or not content:
            continue
        key = key[:_MAX_KEY_LEN]
        content = content[:_MAX_CONTENT_LEN]
        imp = item.get("importance", 0)
        try:
            importance = max(0, min(10, int(imp)))
        except (TypeError, ValueError):
            importance = 0
        out.append({"key": key, "content": content, "importance": importance})
    return out


async def maybe_ingest_post_turn_memory(
    db: AsyncSession,
    user: User,
    *,
    user_message: str,
    assistant_message: str,
) -> PostTurnMemoryResult:
    """Optionally extract and upsert memories from the last exchange. Never raises."""
    rt = await resolve_for_user(db, user)
    if not rt.agent_memory_post_turn_enabled:
        return PostTurnMemoryResult(True, "disabled", 0)

    mode = (rt.agent_memory_post_turn_mode or "heuristic").strip().lower()
    if mode not in ("heuristic", "always"):
        mode = "heuristic"

    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if not a:
        return PostTurnMemoryResult(True, "empty_assistant", 0)

    if mode == "heuristic" and not heuristic_wants_post_turn_extraction(u, a):
        return PostTurnMemoryResult(True, "heuristic_skip", 0)

    settings_row = await UserAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False) or settings_row.ai_disabled:
        return PostTurnMemoryResult(True, "ai_paused_or_disabled", 0)

    api_key = await UserAISettingsService.get_api_key(db, user)
    if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
        return PostTurnMemoryResult(True, "no_api_key", 0)

    user_block = u if u else "(empty)"
    assistant_block = a if a else "(empty)"
    user_prompt = (
        "Extract durable memories from this single exchange only.\n\n"
        f"USER:\n{user_block}\n\nASSISTANT:\n{assistant_block}\n\n"
        'If nothing should be persisted, return exactly: {"memories":[]}'
    )

    try:
        raw = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format_json=True,
        )
    except Exception:
        logger.exception("post_turn_memory: LLM extraction failed user_id=%s", user.id)
        return PostTurnMemoryResult(False, "llm_error", 0)

    payload = _parse_json_object(raw)
    items = _normalize_memory_items(payload)
    if not items:
        logger.info(
            "post_turn_memory: no items user_id=%s mode=%s reason=empty_extraction",
            user.id,
            mode,
        )
        return PostTurnMemoryResult(True, "empty_extraction", 0)

    upserts = 0
    for it in items:
        try:
            await AgentMemoryService.upsert(
                db,
                user,
                key=it["key"],
                content=it["content"],
                importance=int(it.get("importance") or 0),
            )
            upserts += 1
        except Exception:
            logger.exception(
                "post_turn_memory: upsert failed user_id=%s key=%s",
                user.id,
                it.get("key"),
            )

    logger.info(
        "post_turn_memory: done user_id=%s mode=%s upserts=%s",
        user.id,
        mode,
        upserts,
    )
    return PostTurnMemoryResult(False, "ok", upserts)
